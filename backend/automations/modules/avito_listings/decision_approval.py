from dataclasses import dataclass

from django.db import OperationalError, transaction
from django.utils import timezone

from automations.models import (
    AutomationRun,
    AvitoListingDecision,
    AvitoListingRunResult,
)
from avitotask.models import AdPublication, AvitoListing

from .actions import (
    AvitoListingActionError,
    apply_listing_action,
)
from .decision_lifecycle import (
    DecisionTransitionError,
    expire_decision,
    fail_decision_after_action_error,
    is_lock_conflict,
    mark_decision_stale,
)
from .decision_recheck import (
    DecisionRecheckError,
    get_decision_hard_stale_reason,
    recheck_decision_before_approval,
)


@dataclass(frozen=True, slots=True)
class DecisionApprovalResult:
    """Результат попытки подтверждения одного решения."""

    decision: AvitoListingDecision
    outcome: str
    reason: str | None
    changed: bool
    required_export_revision: int | None


class DecisionApprovalError(RuntimeError):
    """Контролируемая ошибка подтверждения решения."""

    def __init__(self, *, code: str, message: str):
        self.code = code
        super().__init__(message)


def approve_decision(
        *,
        workspace,
        run_id: int,
        decision_id: int,
        approved_by,
        approved_at=None,
) -> DecisionApprovalResult:
    """
    Перепроверяет и применяет одно решение в короткой транзакции.

    Статистика читается до захвата row locks. После блокировки повторно
    проверяется только быстрое текущее состояние объявления.
    """
    transition_at = approved_at or timezone.now()

    if timezone.is_naive(transition_at):
        raise DecisionApprovalError(
            code="invalid_approval_time",
            message="Время подтверждения должно содержать часовой пояс.",
        )

    if approved_by is None:
        raise DecisionApprovalError(
            code="invalid_actor",
            message="Для подтверждения решения необходим пользователь.",
        )

    try:
        recheck_result = recheck_decision_before_approval(
            workspace=workspace,
            run_id=run_id,
            decision_id=decision_id,
            checked_at=transition_at,
        )
    except (DecisionRecheckError, DecisionTransitionError) as error:
        raise DecisionApprovalError(
            code=error.code,
            message=str(error),
        ) from error

    if recheck_result.outcome != "ready":
        return DecisionApprovalResult(
            decision=recheck_result.decision,
            outcome=recheck_result.outcome,
            reason=recheck_result.reason,
            changed=recheck_result.changed,
            required_export_revision=(
                recheck_result.decision.required_export_revision
            ),
        )

    try:
        with transaction.atomic():
            return _approve_locked_decision(
                workspace=workspace,
                run_id=run_id,
                decision_id=decision_id,
                approved_by=approved_by,
                transition_at=transition_at,
            )
    except AvitoListingActionError as error:
        return _fail_after_action_error(
            workspace=workspace,
            run_id=run_id,
            decision_id=decision_id,
            approved_by=approved_by,
            transition_at=transition_at,
            error=error,
        )
    except DecisionTransitionError as error:
        raise DecisionApprovalError(
            code=error.code,
            message=str(error),
        ) from error
    except OperationalError as error:
        if not is_lock_conflict(error):
            raise

        raise DecisionApprovalError(
            code="resource_busy",
            message=(
                "Решение или объявление сейчас обрабатывается. "
                "Повторите попытку позже."
            ),
        ) from error


def _approve_locked_decision(
        *,
        workspace,
        run_id: int,
        decision_id: int,
        approved_by,
        transition_at,
) -> DecisionApprovalResult:
    decision = (
        AvitoListingDecision.objects
        .select_for_update(nowait=True)
        .select_related(
            "automation",
            "avito_account",
        )
        .filter(
            id=decision_id,
            run_id=run_id,
            workspace_id=workspace.pk,
            run__workspace_id=workspace.pk,
            automation__workspace_id=workspace.pk,
            avito_account__workspace_id=workspace.pk,
        )
        .first()
    )

    if decision is None:
        raise DecisionApprovalError(
            code="decision_not_found",
            message="Решение не найдено в текущем рабочем пространстве.",
        )

    if decision.status != AvitoListingDecision.Status.PENDING_APPROVAL:
        return DecisionApprovalResult(
            decision=decision,
            outcome="unchanged",
            reason=None,
            changed=False,
            required_export_revision=decision.required_export_revision,
        )

    if transition_at >= decision.expires_at:
        transition = expire_decision(
            workspace_id=workspace.pk,
            run_id=run_id,
            decision_id=decision_id,
            expired_at=transition_at,
        )
        return DecisionApprovalResult(
            decision=transition.decision,
            outcome="expired" if transition.changed else "unchanged",
            reason=None,
            changed=transition.changed,
            required_export_revision=None,
        )

    listing = _get_locked_listing(
        decision=decision,
        workspace_id=workspace.pk,
    )
    if listing is None:
        return _mark_stale(
            decision=decision,
            transition_at=transition_at,
            reason="listing_missing",
        )

    decision.listing = listing

    stale_reason = get_decision_hard_stale_reason(
        decision=decision,
        workspace_id=workspace.pk,
    )
    if stale_reason is not None:
        return _mark_stale(
            decision=decision,
            transition_at=transition_at,
            reason=stale_reason,
        )

    if listing.source == AvitoListing.Source.SERVICE:
        publication_exists = (
            AdPublication.objects
            .select_for_update(nowait=True)
            .filter(
                id=listing.publication_id,
                workspace_id=workspace.pk,
                avito_account_id=decision.avito_account_id,
            )
            .exists()
        )
        if not publication_exists:
            return _mark_stale(
                decision=decision,
                transition_at=transition_at,
                reason="listing_publication_missing",
            )

    automation_run = _get_locked_run(
        workspace_id=workspace.pk,
        run_id=run_id,
    )
    run_result = _get_locked_run_result(
        workspace_id=workspace.pk,
        run_id=run_id,
    )

    if automation_run.status != AutomationRun.Status.WAITING_APPROVAL:
        raise DecisionApprovalError(
            code="invalid_run_state",
            message="Запуск больше не ожидает подтверждения решений.",
        )

    decision.status = AvitoListingDecision.Status.APPLYING
    decision.approved_by = approved_by
    decision.approved_at = transition_at
    decision.save(
        update_fields=[
            "status",
            "approved_by",
            "approved_at",
            "updated_at",
        ],
    )

    action_snapshot = decision.action_snapshot
    action_type = (
        action_snapshot.get("type")
        if isinstance(action_snapshot, dict)
        else None
    )
    action_result = apply_listing_action(
        workspace=workspace,
        avito_account=decision.avito_account,
        listing=listing,
        action_type=action_type,
    )

    decision.status = AvitoListingDecision.Status.EFFECT_PENDING
    decision.action_applied_at = transition_at
    decision.required_export_revision = (
        action_result.required_export_revision
    )
    decision.error_code = ""
    decision.error_message = ""
    decision.save(
        update_fields=[
            "status",
            "action_applied_at",
            "required_export_revision",
            "error_code",
            "error_message",
            "updated_at",
        ],
    )

    pending_approval = AvitoListingDecision.objects.filter(
        run_id=automation_run.id,
        status=AvitoListingDecision.Status.PENDING_APPROVAL,
    ).count()

    if run_result.pending_approval != pending_approval:
        run_result.pending_approval = pending_approval
        run_result.save(
            update_fields=[
                "pending_approval",
                "updated_at",
            ],
        )

    if pending_approval == 0:
        automation_run.status = AutomationRun.Status.EFFECT_PENDING
        automation_run.finished_at = None
        automation_run.save(
            update_fields=[
                "status",
                "finished_at",
                "updated_at",
            ],
        )

    return DecisionApprovalResult(
        decision=decision,
        outcome="effect_pending",
        reason=None,
        changed=True,
        required_export_revision=(
            action_result.required_export_revision
        ),
    )


def _get_locked_listing(
        *,
        decision: AvitoListingDecision,
        workspace_id: int,
):
    if decision.listing_id is None:
        return None

    return (
        AvitoListing.objects
        .select_for_update(
            nowait=True,
            of=("self",),
        )
        .filter(
            id=decision.listing_id,
            workspace_id=workspace_id,
            avito_account_id=decision.avito_account_id,
        )
        .first()
    )


def _get_locked_run(
        *,
        workspace_id: int,
        run_id: int,
) -> AutomationRun:
    try:
        return (
            AutomationRun.objects
            .select_for_update(nowait=True)
            .get(
                id=run_id,
                workspace_id=workspace_id,
            )
        )
    except AutomationRun.DoesNotExist as error:
        raise DecisionApprovalError(
            code="decision_not_found",
            message="Запуск автоматизации не найден.",
        ) from error


def _get_locked_run_result(
        *,
        workspace_id: int,
        run_id: int,
) -> AvitoListingRunResult:
    try:
        return (
            AvitoListingRunResult.objects
            .select_for_update(nowait=True)
            .get(
                run_id=run_id,
                workspace_id=workspace_id,
            )
        )
    except AvitoListingRunResult.DoesNotExist as error:
        raise DecisionApprovalError(
            code="invalid_run_state",
            message="У запуска отсутствует типизированный результат.",
        ) from error


def _mark_stale(
        *,
        decision: AvitoListingDecision,
        transition_at,
        reason: str,
) -> DecisionApprovalResult:
    transition = mark_decision_stale(
        workspace_id=decision.workspace_id,
        run_id=decision.run_id,
        decision_id=decision.id,
        stale_at=transition_at,
        reason=reason,
    )
    return DecisionApprovalResult(
        decision=transition.decision,
        outcome="stale" if transition.changed else "unchanged",
        reason=reason if transition.changed else None,
        changed=transition.changed,
        required_export_revision=None,
    )


def _fail_after_action_error(
        *,
        workspace,
        run_id: int,
        decision_id: int,
        approved_by,
        transition_at,
        error: AvitoListingActionError,
) -> DecisionApprovalResult:
    try:
        transition = fail_decision_after_action_error(
            workspace_id=workspace.pk,
            run_id=run_id,
            decision_id=decision_id,
            failed_at=transition_at,
            approved_by=approved_by,
            reason=error.code,
        )
    except DecisionTransitionError as transition_error:
        raise DecisionApprovalError(
            code=transition_error.code,
            message=str(transition_error),
        ) from transition_error

    return DecisionApprovalResult(
        decision=transition.decision,
        outcome="failed",
        reason=error.code,
        changed=transition.changed,
        required_export_revision=None,
    )
