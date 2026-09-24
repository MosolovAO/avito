from dataclasses import dataclass
from datetime import date
from typing import Any

from django.utils import timezone

from automations.models import AvitoListingDecision
from avitotask.models import AvitoListing

from .decision_lifecycle import (
    expire_decision,
    mark_decision_stale,
)
from .evaluator import (
    CompiledConditionPlan,
    compile_condition_plan,
    evaluate_condition_plan,
)
from .metric_aggregation import aggregate_listing_metric_windows
from .selectors import (
    get_account_stats_readiness,
    partition_listing_ids_by_coverage,
)


@dataclass(frozen=True, slots=True)
class DecisionRecheckResult:
    """Результат повторной проверки решения перед подтверждением."""

    decision: AvitoListingDecision
    outcome: str
    reason: str | None
    changed: bool
    as_of_date: date | None
    metrics_snapshot: tuple[dict[str, Any], ...]


class DecisionRecheckError(RuntimeError):
    """Контролируемая ошибка повторной проверки решения."""

    def __init__(self, *, code: str, message: str):
        self.code = code
        super().__init__(message)


def recheck_decision_before_approval(
        *,
        workspace,
        run_id: int,
        decision_id: int,
        checked_at,
) -> DecisionRecheckResult:
    """
    Повторно проверяет решение без удержания row locks во время статистики.

    Терминальные stale/expired-переходы выполняются отдельными короткими
    транзакциями в decision_lifecycle.
    """
    if timezone.is_naive(checked_at):
        raise DecisionRecheckError(
            code="invalid_check_time",
            message="Время проверки должно содержать часовой пояс.",
        )

    decision = _get_scoped_decision(
        workspace_id=workspace.pk,
        run_id=run_id,
        decision_id=decision_id,
    )

    if decision is None:
        raise DecisionRecheckError(
            code="decision_not_found",
            message="Решение не найдено в текущем рабочем пространстве.",
        )

    if decision.status != AvitoListingDecision.Status.PENDING_APPROVAL:
        return _unchanged_result(decision=decision)

    if checked_at >= decision.expires_at:
        transition = expire_decision(
            workspace_id=workspace.pk,
            run_id=run_id,
            decision_id=decision_id,
            expired_at=checked_at,
        )
        return DecisionRecheckResult(
            decision=transition.decision,
            outcome=(
                "expired"
                if transition.changed
                else "unchanged"
            ),
            reason=None,
            changed=transition.changed,
            as_of_date=None,
            metrics_snapshot=(),
        )

    stale_reason = get_decision_hard_stale_reason(
        decision=decision,
        workspace_id=workspace.pk,
    )
    if stale_reason is not None:
        return _mark_stale(
            decision=decision,
            checked_at=checked_at,
            reason=stale_reason,
        )

    as_of_date = timezone.localdate(checked_at)
    plan = compile_condition_plan(
        decision.condition_snapshot,
        as_of_date=as_of_date,
    )

    account_readiness = get_account_stats_readiness(
        workspace=decision.workspace,
        avito_account=decision.avito_account,
        plan=plan,
    )
    if not account_readiness.is_ready:
        return _insufficient_data_result(
            decision=decision,
            as_of_date=as_of_date,
            reason="insufficient_account_coverage",
        )

    coverage = partition_listing_ids_by_coverage(
        workspace=decision.workspace,
        avito_account=decision.avito_account,
        listing_ids=(decision.listing_id,),
        plan=plan,
    )
    if not coverage.covered_listing_ids:
        return _insufficient_data_result(
            decision=decision,
            as_of_date=as_of_date,
            reason="insufficient_listing_coverage",
        )

    aggregations = aggregate_listing_metric_windows(
        workspace=decision.workspace,
        avito_account=decision.avito_account,
        listing_ids=(decision.listing_id,),
        plan=plan,
    )
    aggregation = aggregations[0]

    if not evaluate_condition_plan(
            plan,
            aggregation.metrics_by_window,
    ):
        return _mark_stale(
            decision=decision,
            checked_at=checked_at,
            reason="condition_not_matched",
        )

    return DecisionRecheckResult(
        decision=decision,
        outcome="ready",
        reason=None,
        changed=False,
        as_of_date=as_of_date,
        metrics_snapshot=_build_metrics_snapshot(
            plan=plan,
            metrics_by_window=aggregation.metrics_by_window,
        ),
    )


def _get_scoped_decision(
        *,
        workspace_id: int,
        run_id: int,
        decision_id: int,
):
    return (
        AvitoListingDecision.objects
        .select_related(
            "workspace",
            "avito_account",
            "automation",
            "listing",
        )
        .filter(
            id=decision_id,
            run_id=run_id,
            workspace_id=workspace_id,
            run__workspace_id=workspace_id,
            automation__workspace_id=workspace_id,
            avito_account__workspace_id=workspace_id,
        )
        .first()
    )


def get_decision_hard_stale_reason(
        *,
        decision: AvitoListingDecision,
        workspace_id: int,
) -> str | None:
    """
    Проверяет только быстрое текущее состояние без чтения статистики.

    Approval повторяет эту проверку после блокировки объявления, чтобы
    изменение между read-only recheck и action не привело к устаревшему
    действию.
    """
    if decision.automation.state != decision.automation.State.ENABLED:
        return "automation_not_enabled"

    if decision.automation.version != decision.automation_version:
        return "automation_version_changed"

    listing = decision.listing
    if listing is None:
        return "listing_missing"

    if (
            listing.workspace_id != workspace_id
            or listing.avito_account_id != decision.avito_account_id
    ):
        return "listing_scope_changed"

    if (
            listing.management_status
            != AvitoListing.ManagementStatus.MANAGED
    ):
        return "listing_not_managed"

    if listing.source not in {
        AvitoListing.Source.SERVICE,
        AvitoListing.Source.AVITO_EXCEL,
    }:
        return "listing_source_not_actionable"

    if (
            listing.source == AvitoListing.Source.SERVICE
            and listing.publication_id is None
    ):
        return "listing_publication_missing"

    if listing.desired_status != AvitoListing.DesiredStatus.PUBLISH:
        return "listing_not_published"

    if listing.active_since != decision.active_since_snapshot:
        return "active_period_changed"

    has_unfinished_effect = (
        AvitoListingDecision.objects
        .filter(
            workspace_id=workspace_id,
            avito_account_id=decision.avito_account_id,
            listing_id=listing.id,
            status__in=(
                AvitoListingDecision.Status.APPLYING,
                AvitoListingDecision.Status.EFFECT_PENDING,
            ),
        )
        .exists()
    )
    if has_unfinished_effect:
        return "listing_has_unfinished_effect"

    return None


def _mark_stale(
        *,
        decision: AvitoListingDecision,
        checked_at,
        reason: str,
) -> DecisionRecheckResult:
    transition = mark_decision_stale(
        workspace_id=decision.workspace_id,
        run_id=decision.run_id,
        decision_id=decision.id,
        stale_at=checked_at,
        reason=reason,
    )

    if not transition.changed:
        return _unchanged_result(decision=transition.decision)

    return DecisionRecheckResult(
        decision=transition.decision,
        outcome="stale",
        reason=reason,
        changed=True,
        as_of_date=None,
        metrics_snapshot=(),
    )


def _insufficient_data_result(
        *,
        decision: AvitoListingDecision,
        as_of_date: date,
        reason: str,
) -> DecisionRecheckResult:
    return DecisionRecheckResult(
        decision=decision,
        outcome="insufficient_data",
        reason=reason,
        changed=False,
        as_of_date=as_of_date,
        metrics_snapshot=(),
    )


def _unchanged_result(
        *,
        decision: AvitoListingDecision,
) -> DecisionRecheckResult:
    return DecisionRecheckResult(
        decision=decision,
        outcome="unchanged",
        reason=None,
        changed=False,
        as_of_date=None,
        metrics_snapshot=(),
    )


def _build_metrics_snapshot(
        *,
        plan: CompiledConditionPlan,
        metrics_by_window,
) -> tuple[dict[str, Any], ...]:
    """Формирует безопасные значения свежих статистических окон."""

    return tuple(
        {
            "metric": window.metric,
            "aggregation": window.aggregation,
            "window_days": window.window_days,
            "date_from": window.date_from.isoformat(),
            "date_to": window.date_to.isoformat(),
            "value": metrics_by_window[window],
        }
        for window in plan.windows
    )
