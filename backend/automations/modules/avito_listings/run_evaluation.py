from dataclasses import dataclass
from typing import Any
from django.utils import timezone
from datetime import timedelta

from automations.models import (
    AutomationRun,
    AvitoListingDecision,
    AvitoListingRunResult,
)

from avitotask.models import AvitoListing

from .evaluation import (
    ListingEvaluationResult,
    evaluate_listing_candidates,
)
from .evaluator import (
    CompiledConditionPlan,
    compile_condition_plan,
)
from .run_readiness import InvalidAvitoListingRunResultError

MAX_PREVIEW_EXAMPLES = 20


@dataclass(frozen=True, slots=True)
class AvitoListingRunEvaluation:
    """Полностью вычисленный, но ещё не сохранённый результат run."""

    plan: CompiledConditionPlan
    evaluation: ListingEvaluationResult
    examples_snapshot: tuple[dict[str, Any], ...]


def evaluate_run(
        *,
        run: AutomationRun,
) -> AvitoListingRunEvaluation:
    """
    Вычисляет typed result по зафиксированным snapshots.

    Функция выполняет только чтение. Счётчики и примеры записываются
    отдельным вызовом после успешного завершения всего evaluator.
    """

    run_result = _get_scoped_run_result(run=run)

    plan = compile_condition_plan(
        run_result.condition_snapshot,
        as_of_date=run_result.as_of_date,
    )
    evaluation = evaluate_listing_candidates(
        workspace=run_result.workspace,
        avito_account=run_result.avito_account,
        plan=plan,
        max_actions_per_run=(
            run_result.max_actions_per_run_snapshot
        ),
    )
    examples_snapshot = _build_examples_snapshot(
        run_result=run_result,
        plan=plan,
        evaluation=evaluation,
    )

    return AvitoListingRunEvaluation(
        plan=plan,
        evaluation=evaluation,
        examples_snapshot=examples_snapshot,
    )


def save_run_evaluation(
        *,
        run: AutomationRun,
        outcome: AvitoListingRunEvaluation,
) -> str:
    """
    Атомарно сохраняет вычисленный результат и решения execute run.

    Вызывающий executor обязан открыть короткую транзакцию и
    заблокировать AutomationRun до вызова этой функции.
    """

    run_result = (
        AvitoListingRunResult.objects
        .select_for_update()
        .filter(
            run_id=run.id,
            workspace_id=run.workspace_id,
            avito_account__workspace_id=run.workspace_id,
        )
        .first()
    )
    if run_result is None:
        raise InvalidAvitoListingRunResultError(
            run_id=run.id,
        )

    evaluation = outcome.evaluation

    pending_approval = 0
    if run.run_kind == AutomationRun.RunKind.EXECUTE:
        pending_approval = _create_pending_decisions(
            run=run,
            run_result=run_result,
            outcome=outcome,
        )

    run_result.target_max_id_snapshot = (
        evaluation.target_max_id_snapshot
    )
    run_result.checked = evaluation.checked
    run_result.ineligible = evaluation.ineligible
    run_result.insufficient_coverage = (
        evaluation.insufficient_coverage
    )
    run_result.not_matched = evaluation.not_matched
    run_result.matched = evaluation.matched
    run_result.deferred_by_run_limit = (
        evaluation.deferred_by_run_limit
    )
    run_result.pending_approval = pending_approval
    run_result.examples_snapshot = list(
        outcome.examples_snapshot,
    )
    run_result.save(
        update_fields=[
            "target_max_id_snapshot",
            "checked",
            "ineligible",
            "insufficient_coverage",
            "not_matched",
            "matched",
            "deferred_by_run_limit",
            "pending_approval",
            "examples_snapshot",
            "updated_at",
        ],
    )

    if pending_approval:
        return AutomationRun.Status.WAITING_APPROVAL

    return AutomationRun.Status.COMPLETED


def _create_pending_decisions(
        *,
        run: AutomationRun,
        run_result: AvitoListingRunResult,
        outcome: AvitoListingRunEvaluation,
) -> int:
    """Пакетно создаёт решения только для существующих объявлений."""

    selected_matches = outcome.evaluation.selected_matches
    if not selected_matches:
        return 0

    listing_ids = tuple(
        match.listing_id
        for match in selected_matches
    )
    listing_rows_by_id = {
        row["id"]: row
        for row in (
            AvitoListing.objects
            .filter(
                workspace_id=run.workspace_id,
                avito_account_id=run_result.avito_account_id,
                id__in=listing_ids,
            )
            .values(
                "id",
                "avito_id",
                "title",
            )
        )
    }

    expires_at = (
            timezone.now()
            + timedelta(
        minutes=(
            run_result.approval_ttl_minutes_snapshot
        ),
    )
    )
    decisions = []

    for match in selected_matches:
        listing_row = listing_rows_by_id.get(match.listing_id)
        if listing_row is None:
            continue

        decisions.append(
            AvitoListingDecision(
                run=run,
                automation_id=run.automation_id,
                workspace_id=run.workspace_id,
                avito_account_id=run_result.avito_account_id,
                listing_id=match.listing_id,
                listing_id_snapshot=match.listing_id,
                listing_snapshot={
                    "avito_id": listing_row["avito_id"],
                    "title": listing_row["title"],
                },
                status=(
                    AvitoListingDecision.Status.PENDING_APPROVAL
                ),
                automation_version=run.automation_version,
                active_since_snapshot=match.active_since,
                condition_snapshot=run_result.condition_snapshot,
                metrics_snapshot=_build_metrics_snapshot(
                    match=match,
                    plan=outcome.plan,
                ),
                action_snapshot=run_result.action_snapshot,
                expires_at=expires_at,
            )
        )

    if decisions:
        AvitoListingDecision.objects.bulk_create(
            decisions,
            batch_size=100,
        )

    return len(decisions)


def _get_scoped_run_result(
        *,
        run: AutomationRun,
) -> AvitoListingRunResult:
    run_result = (
        AvitoListingRunResult.objects
        .select_related(
            "workspace",
            "avito_account",
        )
        .filter(
            run_id=run.id,
            workspace_id=run.workspace_id,
            avito_account__workspace_id=run.workspace_id,
        )
        .first()
    )
    if run_result is None:
        raise InvalidAvitoListingRunResultError(
            run_id=run.id,
        )

    return run_result


def _build_metrics_snapshot(
        *,
        match,
        plan: CompiledConditionPlan,
) -> list[dict[str, Any]]:
    """Формирует безопасный snapshot метрик одного совпадения."""

    return [
        {
            "metric": window.metric,
            "aggregation": window.aggregation,
            "window_days": window.window_days,
            "date_from": window.date_from.isoformat(),
            "date_to": window.date_to.isoformat(),
            "value": match.metrics_by_window[window],
        }
        for window in plan.windows
    ]


def _build_examples_snapshot(
        *,
        run_result: AvitoListingRunResult,
        plan,
        evaluation: ListingEvaluationResult,
) -> tuple[dict[str, Any], ...]:
    selected_matches = evaluation.selected_matches[
                       :MAX_PREVIEW_EXAMPLES
                       ]
    if not selected_matches:
        return ()

    listing_ids = tuple(
        match.listing_id
        for match in selected_matches
    )
    listing_rows_by_id = {
        row["id"]: row
        for row in (
            AvitoListing.objects
            .filter(
                workspace_id=run_result.workspace_id,
                avito_account_id=run_result.avito_account_id,
                id__in=listing_ids,
            )
            .values(
                "id",
                "avito_id",
                "title",
            )
        )
    }

    examples: list[dict[str, Any]] = []

    for match in selected_matches:
        listing_row = listing_rows_by_id.get(match.listing_id)
        if listing_row is None:
            continue

        metrics = _build_metrics_snapshot(
            match=match,
            plan=plan,
        )

        examples.append({
            "listing_id": match.listing_id,
            "avito_id": listing_row["avito_id"],
            "title": listing_row["title"],
            "active_since": timezone.localtime(
                match.active_since,
            ).isoformat(),
            "metrics": metrics,
            "matched": True,
        })

    return tuple(examples)
