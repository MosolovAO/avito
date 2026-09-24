from dataclasses import dataclass
from datetime import timedelta

from django.db import OperationalError, transaction
from django.db.models import Q
from django.utils import timezone

from automations.models import (
    AutomationRun,
    AvitoListingDecision,
    AvitoListingRunResult,
)
from avitotask.models import (
    AdPublication,
    AvitoAccount,
    AvitoListing,
)
from avitotask.services.ad_export_queue import (
    queue_avito_account_csv_exports,
)

from .decision_lifecycle import is_lock_conflict

MAX_RECOVERY_BATCH = 100
MAX_EFFECT_ATTEMPTS = 3
EFFECT_RETRY_DELAY = timedelta(minutes=10)

EXPORT_IN_PROGRESS_STATUSES = {
    AvitoAccount.ExportStatus.DIRTY,
    AvitoAccount.ExportStatus.QUEUED,
    AvitoAccount.ExportStatus.EXPORTING,
}

LISTING_TARGET_BY_ACTION = {
    "pause": AvitoListing.DesiredStatus.PAUSE,
    "archive": AvitoListing.DesiredStatus.ARCHIVE,
}

PUBLICATION_TARGET_BY_ACTION = {
    "pause": AdPublication.Status.PAUSED,
    "archive": AdPublication.Status.ARCHIVED,
}

EXPORT_FAILURE_MESSAGE = (
    "Не удалось создать CSV с требуемым изменением после трёх попыток."
)


@dataclass(frozen=True, slots=True)
class EffectRecoveryResult:
    """Результат одного ограниченного прохода восстановления эффектов."""

    selected: int
    completed: int
    superseded: int
    failed: int
    retries_scheduled: int
    accounts_queued: int
    busy: int


@dataclass(frozen=True, slots=True)
class _DecisionRecoveryResult:
    """Внутренний результат обработки одного решения."""

    outcome: str
    retry_account_id: int | None = None


def recover_pending_listing_effects(
        *,
        recovered_at,
        limit: int = MAX_RECOVERY_BATCH,
) -> EffectRecoveryResult:
    """
    Выполняет один bounded-проход по ожидающим CSV-эффектам.

    Lifecycle-действия здесь никогда не повторяются. Если нужная revision
    ещё не создана, повторно ставится только экспорт аккаунта.
    """
    _validate_recovery_arguments(
        recovered_at=recovered_at,
        limit=limit,
    )

    decision_ids = list(
        AvitoListingDecision.objects
        .filter(
            status=AvitoListingDecision.Status.EFFECT_PENDING,
        )
        .filter(
            Q(next_effect_retry_at__isnull=True)
            | Q(next_effect_retry_at__lte=recovered_at),
        )
        .order_by("id")
        .values_list("id", flat=True)[:limit]
    )

    completed = 0
    superseded = 0
    failed = 0
    retries_scheduled = 0
    busy = 0
    retry_account_ids: set[int] = set()

    for decision_id in decision_ids:
        try:
            result = _recover_one_decision(
                decision_id=decision_id,
                recovered_at=recovered_at,
            )
        except OperationalError as error:
            if not is_lock_conflict(error):
                raise

            busy += 1
            continue

        if result.outcome == "completed":
            completed += 1
        elif result.outcome == "superseded":
            superseded += 1
        elif result.outcome == "failed":
            failed += 1
        elif result.outcome == "retry_scheduled":
            retries_scheduled += 1

        if result.retry_account_id is not None:
            retry_account_ids.add(result.retry_account_id)

    accounts_queued = 0
    if retry_account_ids:
        queue_result = queue_avito_account_csv_exports(
            sorted(retry_account_ids),
        )
        if queue_result == "queued":
            accounts_queued = len(retry_account_ids)

    return EffectRecoveryResult(
        selected=len(decision_ids),
        completed=completed,
        superseded=superseded,
        failed=failed,
        retries_scheduled=retries_scheduled,
        accounts_queued=accounts_queued,
        busy=busy,
    )


def _validate_recovery_arguments(*, recovered_at, limit: int) -> None:
    if timezone.is_naive(recovered_at):
        raise ValueError(
            "Время recovery должно содержать часовой пояс.",
        )

    if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit < 1
            or limit > MAX_RECOVERY_BATCH
    ):
        raise ValueError(
            "Размер recovery batch должен находиться в диапазоне 1–100.",
        )


def _recover_one_decision(
        *,
        decision_id: int,
        recovered_at,
) -> _DecisionRecoveryResult:
    with transaction.atomic():
        decision = (
            AvitoListingDecision.objects
            .select_for_update(
                nowait=True,
                of=("self",),
            )
            .filter(id=decision_id)
            .first()
        )

        if (
                decision is None
                or decision.status
                != AvitoListingDecision.Status.EFFECT_PENDING
        ):
            return _DecisionRecoveryResult(outcome="unchanged")

        listing, publication = _get_locked_action_target(
            decision=decision,
        )
        automation_run, run_result = _get_locked_run_context(
            decision=decision,
        )

        target_matches = _target_state_matches(
            decision=decision,
            listing=listing,
            publication=publication,
        )

        if target_matches is False:
            _finish_locked_effect(
                decision=decision,
                automation_run=automation_run,
                run_result=run_result,
                recovered_at=recovered_at,
                terminal_status=(
                    AvitoListingDecision.Status.SUPERSEDED
                ),
            )
            return _DecisionRecoveryResult(outcome="superseded")

        if target_matches is None:
            _finish_locked_effect(
                decision=decision,
                automation_run=automation_run,
                run_result=run_result,
                recovered_at=recovered_at,
                terminal_status=AvitoListingDecision.Status.FAILED,
                error_code="invalid_effect_state",
                error_message=(
                    "Сохранённое состояние действия больше "
                    "не поддерживается."
                ),
            )
            return _DecisionRecoveryResult(outcome="failed")

        required_revision = decision.required_export_revision
        if (
                not isinstance(required_revision, int)
                or required_revision < 1
        ):
            _finish_locked_effect(
                decision=decision,
                automation_run=automation_run,
                run_result=run_result,
                recovered_at=recovered_at,
                terminal_status=AvitoListingDecision.Status.FAILED,
                error_code="invalid_effect_state",
                error_message=(
                    "У решения отсутствует корректная ревизия экспорта."
                ),
            )
            return _DecisionRecoveryResult(outcome="failed")

        avito_account = _get_locked_account(decision=decision)

        if (
                avito_account.last_exported_revision
                >= required_revision
        ):
            _finish_locked_effect(
                decision=decision,
                automation_run=automation_run,
                run_result=run_result,
                recovered_at=recovered_at,
                terminal_status=AvitoListingDecision.Status.COMPLETED,
            )
            return _DecisionRecoveryResult(outcome="completed")

        if (
                avito_account.is_active
                and avito_account.export_status
                in EXPORT_IN_PROGRESS_STATUSES
        ):
            return _DecisionRecoveryResult(outcome="waiting")

        if decision.effect_attempts >= MAX_EFFECT_ATTEMPTS:
            _finish_locked_effect(
                decision=decision,
                automation_run=automation_run,
                run_result=run_result,
                recovered_at=recovered_at,
                terminal_status=AvitoListingDecision.Status.FAILED,
                error_code="export_failed",
                error_message=EXPORT_FAILURE_MESSAGE,
            )
            return _DecisionRecoveryResult(outcome="failed")

        decision.effect_attempts += 1
        decision.next_effect_retry_at = (
                recovered_at + EFFECT_RETRY_DELAY
        )
        decision.save(
            update_fields=[
                "effect_attempts",
                "next_effect_retry_at",
                "updated_at",
            ],
        )

        return _DecisionRecoveryResult(
            outcome="retry_scheduled",
            retry_account_id=avito_account.id,
        )


def _get_locked_action_target(
        *,
        decision: AvitoListingDecision,
) -> tuple[AvitoListing | None, AdPublication | None]:
    if decision.listing_id is None:
        return None, None

    listing = (
        AvitoListing.objects
        .select_for_update(
            nowait=True,
            of=("self",),
        )
        .filter(
            id=decision.listing_id,
            workspace_id=decision.workspace_id,
            avito_account_id=decision.avito_account_id,
        )
        .first()
    )
    if listing is None:
        return None, None

    publication = None
    if (
            listing.source == AvitoListing.Source.SERVICE
            and listing.publication_id is not None
    ):
        publication = (
            AdPublication.objects
            .select_for_update(
                nowait=True,
                of=("self",),
            )
            .filter(
                id=listing.publication_id,
                workspace_id=decision.workspace_id,
                avito_account_id=decision.avito_account_id,
            )
            .first()
        )

    return listing, publication


def _target_state_matches(
        *,
        decision: AvitoListingDecision,
        listing: AvitoListing | None,
        publication: AdPublication | None,
) -> bool | None:
    """
    Возвращает True для сохранённого действия, False для отменённого.

    None означает повреждённый или больше не поддерживаемый snapshot.
    """
    action_snapshot = decision.action_snapshot
    if not isinstance(action_snapshot, dict):
        return None

    action_type = action_snapshot.get("type")
    listing_target = LISTING_TARGET_BY_ACTION.get(action_type)
    publication_target = PUBLICATION_TARGET_BY_ACTION.get(action_type)
    if listing_target is None or publication_target is None:
        return None

    if listing is None:
        return False

    if (
            listing.management_status
            != AvitoListing.ManagementStatus.MANAGED
    ):
        return False

    if listing.source == AvitoListing.Source.AVITO_EXCEL:
        return listing.desired_status == listing_target

    if listing.source == AvitoListing.Source.SERVICE:
        return (
                publication is not None
                and publication.status == publication_target
        )

    return None


def _get_locked_account(
        *,
        decision: AvitoListingDecision,
) -> AvitoAccount:
    return (
        AvitoAccount.objects
        .select_for_update(
            nowait=True,
            of=("self",),
        )
        .get(
            id=decision.avito_account_id,
            workspace_id=decision.workspace_id,
        )
    )


def _get_locked_run_context(
        *,
        decision: AvitoListingDecision,
) -> tuple[AutomationRun, AvitoListingRunResult]:
    automation_run = (
        AutomationRun.objects
        .select_for_update(
            nowait=True,
            of=("self",),
        )
        .get(
            id=decision.run_id,
            workspace_id=decision.workspace_id,
        )
    )
    run_result = (
        AvitoListingRunResult.objects
        .select_for_update(
            nowait=True,
            of=("self",),
        )
        .get(
            run_id=decision.run_id,
            workspace_id=decision.workspace_id,
        )
    )

    return automation_run, run_result


def _finish_locked_effect(
        *,
        decision: AvitoListingDecision,
        automation_run: AutomationRun,
        run_result: AvitoListingRunResult,
        recovered_at,
        terminal_status: str,
        error_code: str = "",
        error_message: str = "",
) -> None:

    decision.status = terminal_status
    decision.completed_at = (
        recovered_at
        if terminal_status == AvitoListingDecision.Status.COMPLETED
        else None
    )
    decision.terminal_at = recovered_at
    decision.next_effect_retry_at = None
    decision.error_code = error_code
    decision.error_message = error_message
    decision.save(
        update_fields=[
            "status",
            "completed_at",
            "terminal_at",
            "next_effect_retry_at",
            "error_code",
            "error_message",
            "updated_at",
        ],
    )

    decision_statuses = list(
        AvitoListingDecision.objects
        .filter(run_id=automation_run.id)
        .values_list("status", flat=True)
    )

    run_result.completed_actions = decision_statuses.count(
        AvitoListingDecision.Status.COMPLETED,
    )
    run_result.failed_actions = decision_statuses.count(
        AvitoListingDecision.Status.FAILED,
    )
    run_result.pending_approval = decision_statuses.count(
        AvitoListingDecision.Status.PENDING_APPROVAL,
    )
    run_result.save(
        update_fields=[
            "completed_actions",
            "failed_actions",
            "pending_approval",
            "updated_at",
        ],
    )

    _update_run_after_effect(
        automation_run=automation_run,
        decision_statuses=set(decision_statuses),
        recovered_at=recovered_at,
    )


def _update_run_after_effect(
        *,
        automation_run: AutomationRun,
        decision_statuses: set[str],
        recovered_at,
) -> None:
    if (
            AvitoListingDecision.Status.PENDING_APPROVAL
            in decision_statuses
    ):
        automation_run.status = AutomationRun.Status.WAITING_APPROVAL
        automation_run.finished_at = None
    elif decision_statuses & {
        AvitoListingDecision.Status.APPLYING,
        AvitoListingDecision.Status.EFFECT_PENDING,
    }:
        automation_run.status = AutomationRun.Status.EFFECT_PENDING
        automation_run.finished_at = None
    else:
        has_completed = (
                AvitoListingDecision.Status.COMPLETED
                in decision_statuses
        )
        has_failed = (
                AvitoListingDecision.Status.FAILED
                in decision_statuses
        )

        if has_completed and has_failed:
            automation_run.status = AutomationRun.Status.PARTIAL
        elif has_failed:
            automation_run.status = AutomationRun.Status.FAILED
        else:
            automation_run.status = AutomationRun.Status.COMPLETED

        automation_run.finished_at = recovered_at

    automation_run.save(
        update_fields=[
            "status",
            "finished_at",
            "updated_at",
        ],
    )
