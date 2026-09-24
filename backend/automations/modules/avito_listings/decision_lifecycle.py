from dataclasses import dataclass

from django.db import OperationalError, transaction
from django.utils import timezone

from automations.models import (
    AutomationRun,
    AvitoListingDecision,
    AvitoListingRunResult,
)

STALE_REASON_MESSAGES = {
    "automation_not_enabled": (
        "Автоматизация больше не включена."
    ),
    "automation_version_changed": (
        "Версия автоматизации изменилась после создания решения."
    ),
    "listing_missing": (
        "Объявление больше не существует."
    ),
    "listing_scope_changed": (
        "Объявление больше не принадлежит выбранному аккаунту."
    ),
    "listing_not_managed": (
        "Объявление больше не управляется сервисом."
    ),
    "listing_not_published": (
        "Объявление больше не ожидает публикации."
    ),
    "active_period_changed": (
        "Период активности объявления изменился."
    ),
    "listing_has_unfinished_effect": (
        "Над объявлением уже выполняется другое действие."
    ),
    "condition_not_matched": (
        "Условие автоматизации больше не выполняется."
    ),
    "listing_source_not_actionable": (
        "Источник объявления больше не поддерживает автоматические действия."
    ),
    "listing_publication_missing": (
        "Связанная публикация объявления больше не существует."
    ),
}

ACTION_FAILURE_MESSAGES = {
    "unsupported_action": (
        "Сохранённое действие больше не поддерживается."
    ),
    "listing_scope_mismatch": (
        "Объявление больше не принадлежит выбранному аккаунту."
    ),
    "listing_not_actionable": (
        "Объявление больше не поддерживает выбранное действие."
    ),
    "lifecycle_rejected": (
        "Сервис управления объявлениями отклонил действие."
    ),
    "invalid_export_revision": (
        "Действие не создало корректную ревизию экспорта."
    ),
}


@dataclass(frozen=True, slots=True)
class DecisionTransitionResult:
    """Результат перехода состояния решения."""

    decision: AvitoListingDecision
    changed: bool


class DecisionTransitionError(RuntimeError):
    """Контролируемая ошибка перехода состояния решения."""

    def __init__(self, *, code: str, message: str):
        self.code = code
        super().__init__(message)


def reject_decision(
        *,
        workspace,
        run_id: int,
        decision_id: int,
        rejected_by,
        rejected_at=None,
) -> DecisionTransitionResult:
    """
    Отклоняет ожидающее подтверждения решение.

    Объявление при отклонении не изменяется. Решение, запуск и типизированный
    результат блокируются только на время короткой транзакции.
    """
    transition_at = rejected_at or timezone.now()

    if timezone.is_naive(transition_at):
        raise DecisionTransitionError(
            code="invalid_transition_time",
            message="Время перехода должно содержать часовой пояс.",
        )

    if rejected_by is None:
        raise DecisionTransitionError(
            code="invalid_actor",
            message="Для отклонения решения необходим пользователь.",
        )

    try:
        with transaction.atomic():
            return _reject_locked_decision(
                workspace=workspace,
                run_id=run_id,
                decision_id=decision_id,
                rejected_by=rejected_by,
                transition_at=transition_at,
            )
    except OperationalError as error:
        if not is_lock_conflict(error):
            raise

        raise DecisionTransitionError(
            code="resource_busy",
            message=(
                "Решение сейчас обрабатывается другим запросом. "
                "Повторите попытку позже."
            ),
        ) from error


def _expire_locked_pending_decision(
        *,
        workspace_id: int,
        run_id: int,
        decision_id: int,
        expired_at,
) -> DecisionTransitionResult:
    decision = _get_locked_decision(
        workspace_id=workspace_id,
        run_id=run_id,
        decision_id=decision_id,
    )

    if decision is None:
        raise DecisionTransitionError(
            code="decision_not_found",
            message="Решение не найдено в текущем рабочем пространстве.",
        )

    if decision.status != AvitoListingDecision.Status.PENDING_APPROVAL:
        return DecisionTransitionResult(
            decision=decision,
            changed=False,
        )

    if decision.expires_at > expired_at:
        return DecisionTransitionResult(
            decision=decision,
            changed=False,
        )

    automation_run = _get_locked_run(
        workspace_id=workspace_id,
        run_id=run_id,
    )
    run_result = _get_locked_run_result(
        workspace_id=workspace_id,
        run_id=run_id,
    )

    if automation_run.status != AutomationRun.Status.WAITING_APPROVAL:
        raise DecisionTransitionError(
            code="invalid_run_state",
            message="Запуск больше не ожидает подтверждения решений.",
        )

    _expire_decision(
        decision=decision,
        transition_at=expired_at,
    )

    pending_approval = _count_pending_decisions(
        run_id=automation_run.id,
    )
    _update_pending_approval(
        run_result=run_result,
        pending_approval=pending_approval,
    )

    if pending_approval == 0:
        _finish_run_after_last_pending_decision(
            automation_run=automation_run,
            transition_at=expired_at,
        )

    return DecisionTransitionResult(
        decision=decision,
        changed=True,
    )


def expire_decision(
        *,
        workspace_id: int,
        run_id: int,
        decision_id: int,
        expired_at,
) -> DecisionTransitionResult:
    """
    Закрывает ожидающее решение, если срок подтверждения уже истёк.

    Повторный вызов и решение с будущим expires_at ничего не изменяют.
    """
    if timezone.is_naive(expired_at):
        raise DecisionTransitionError(
            code="invalid_transition_time",
            message="Время перехода должно содержать часовой пояс.",
        )

    try:
        with transaction.atomic():
            return _expire_locked_pending_decision(
                workspace_id=workspace_id,
                run_id=run_id,
                decision_id=decision_id,
                expired_at=expired_at,
            )
    except OperationalError as error:
        if not is_lock_conflict(error):
            raise

        raise DecisionTransitionError(
            code="resource_busy",
            message=(
                "Решение сейчас обрабатывается другим запросом. "
                "Повторите попытку позже."
            ),
        ) from error


def mark_decision_stale(
        *,
        workspace_id: int,
        run_id: int,
        decision_id: int,
        stale_at,
        reason: str,
) -> DecisionTransitionResult:
    """Терминально закрывает устаревшее ожидающее решение."""

    if timezone.is_naive(stale_at):
        raise DecisionTransitionError(
            code="invalid_transition_time",
            message="Время перехода должно содержать часовой пояс.",
        )

    error_message = STALE_REASON_MESSAGES.get(reason)
    if error_message is None:
        raise DecisionTransitionError(
            code="invalid_stale_reason",
            message="Передана неизвестная причина устаревания решения.",
        )

    try:
        with transaction.atomic():
            return _mark_locked_pending_decision_stale(
                workspace_id=workspace_id,
                run_id=run_id,
                decision_id=decision_id,
                stale_at=stale_at,
                error_message=error_message,
            )
    except OperationalError as error:
        if not is_lock_conflict(error):
            raise

        raise DecisionTransitionError(
            code="resource_busy",
            message=(
                "Решение сейчас обрабатывается другим запросом. "
                "Повторите попытку позже."
            ),
        ) from error


def _mark_locked_pending_decision_stale(
        *,
        workspace_id: int,
        run_id: int,
        decision_id: int,
        stale_at,
        error_message: str,
) -> DecisionTransitionResult:
    decision = _get_locked_decision(
        workspace_id=workspace_id,
        run_id=run_id,
        decision_id=decision_id,
    )

    if decision is None:
        raise DecisionTransitionError(
            code="decision_not_found",
            message="Решение не найдено в текущем рабочем пространстве.",
        )

    if decision.status != AvitoListingDecision.Status.PENDING_APPROVAL:
        return DecisionTransitionResult(
            decision=decision,
            changed=False,
        )

    automation_run = _get_locked_run(
        workspace_id=workspace_id,
        run_id=run_id,
    )
    run_result = _get_locked_run_result(
        workspace_id=workspace_id,
        run_id=run_id,
    )

    if automation_run.status != AutomationRun.Status.WAITING_APPROVAL:
        raise DecisionTransitionError(
            code="invalid_run_state",
            message="Запуск больше не ожидает подтверждения решений.",
        )

    decision.status = AvitoListingDecision.Status.STALE
    decision.terminal_at = stale_at
    decision.error_code = "stale"
    decision.error_message = error_message
    decision.save(
        update_fields=[
            "status",
            "terminal_at",
            "error_code",
            "error_message",
            "updated_at",
        ],
    )

    pending_approval = _count_pending_decisions(
        run_id=automation_run.id,
    )
    _update_pending_approval(
        run_result=run_result,
        pending_approval=pending_approval,
    )

    if pending_approval == 0:
        _finish_run_after_last_pending_decision(
            automation_run=automation_run,
            transition_at=stale_at,
        )

    return DecisionTransitionResult(
        decision=decision,
        changed=True,
    )


def _reject_locked_decision(
        *,
        workspace,
        run_id: int,
        decision_id: int,
        rejected_by,
        transition_at,
) -> DecisionTransitionResult:
    decision = _get_locked_decision(
        workspace_id=workspace.pk,
        run_id=run_id,
        decision_id=decision_id,
    )

    if decision is None:
        raise DecisionTransitionError(
            code="decision_not_found",
            message="Решение не найдено в текущем рабочем пространстве.",
        )

    if decision.status in {
        AvitoListingDecision.Status.REJECTED,
        AvitoListingDecision.Status.EXPIRED,
    }:
        return DecisionTransitionResult(
            decision=decision,
            changed=False,
        )

    if decision.status != AvitoListingDecision.Status.PENDING_APPROVAL:
        raise DecisionTransitionError(
            code="invalid_decision_state",
            message=(
                "Отклонить можно только решение, ожидающее подтверждения."
            ),
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
        raise DecisionTransitionError(
            code="invalid_run_state",
            message="Запуск больше не ожидает подтверждения решений.",
        )

    if transition_at >= decision.expires_at:
        _expire_decision(
            decision=decision,
            transition_at=transition_at,
        )
    else:
        _reject_pending_decision(
            decision=decision,
            rejected_by=rejected_by,
            transition_at=transition_at,
        )

    pending_approval = _count_pending_decisions(
        run_id=automation_run.id,
    )
    _update_pending_approval(
        run_result=run_result,
        pending_approval=pending_approval,
    )

    if pending_approval == 0:
        _finish_run_after_last_pending_decision(
            automation_run=automation_run,
            transition_at=transition_at,
        )

    return DecisionTransitionResult(
        decision=decision,
        changed=True,
    )


def _get_locked_decision(
        *,
        workspace_id: int,
        run_id: int,
        decision_id: int,
):
    return (
        AvitoListingDecision.objects
        .select_for_update(nowait=True)
        .filter(
            id=decision_id,
            run_id=run_id,
            workspace_id=workspace_id,
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
        raise DecisionTransitionError(
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
        raise DecisionTransitionError(
            code="invalid_run_state",
            message="У запуска отсутствует типизированный результат.",
        ) from error


def _reject_pending_decision(
        *,
        decision: AvitoListingDecision,
        rejected_by,
        transition_at,
) -> None:
    decision.status = AvitoListingDecision.Status.REJECTED
    decision.rejected_by = rejected_by
    decision.rejected_at = transition_at
    decision.terminal_at = transition_at
    decision.save(
        update_fields=[
            "status",
            "rejected_by",
            "rejected_at",
            "terminal_at",
            "updated_at",
        ],
    )


def _expire_decision(
        *,
        decision: AvitoListingDecision,
        transition_at,
) -> None:
    decision.status = AvitoListingDecision.Status.EXPIRED
    decision.rejected_by = None
    decision.rejected_at = None
    decision.terminal_at = transition_at
    decision.save(
        update_fields=[
            "status",
            "rejected_by",
            "rejected_at",
            "terminal_at",
            "updated_at",
        ],
    )


def _count_pending_decisions(*, run_id: int) -> int:
    return AvitoListingDecision.objects.filter(
        run_id=run_id,
        status=AvitoListingDecision.Status.PENDING_APPROVAL,
    ).count()


def _update_pending_approval(
        *,
        run_result: AvitoListingRunResult,
        pending_approval: int,
) -> None:
    if run_result.pending_approval == pending_approval:
        return

    run_result.pending_approval = pending_approval
    run_result.save(
        update_fields=[
            "pending_approval",
            "updated_at",
        ],
    )


def _finish_run_after_last_pending_decision(
        *,
        automation_run: AutomationRun,
        transition_at,
) -> None:
    decision_statuses = set(
        AvitoListingDecision.objects.filter(
            run_id=automation_run.id,
        ).values_list("status", flat=True),
    )

    has_pending_effect = bool(
        decision_statuses
        & {
            AvitoListingDecision.Status.APPLYING,
            AvitoListingDecision.Status.EFFECT_PENDING,
        }
    )

    if has_pending_effect:
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

        automation_run.finished_at = transition_at

    automation_run.save(
        update_fields=[
            "status",
            "finished_at",
            "updated_at",
        ],
    )


def is_lock_conflict(error: OperationalError) -> bool:
    """
    Отличает PostgreSQL lock-not-available от других ошибок соединения.

    SQLSTATE 55P03 возвращается при неудачном select_for_update(nowait=True).
    Проверка текста оставлена для совместимости с обёртками драйвера,
    которые не передают SQLSTATE наружу.
    """
    cause = error.__cause__
    sqlstate = (
            getattr(cause, "sqlstate", None)
            or getattr(cause, "pgcode", None)
    )

    if sqlstate == "55P03":
        return True

    return "could not obtain lock" in str(error).lower()


def fail_decision_after_action_error(
        *,
        workspace_id: int,
        run_id: int,
        decision_id: int,
        failed_at,
        approved_by,
        reason: str,
) -> DecisionTransitionResult:
    """
    Терминально закрывает решение после постоянной ошибки действия.

    Само действие к этому моменту должно быть полностью откачено. Переход
    выполняется отдельной короткой транзакцией и сохраняет факт ручного
    подтверждения для аудита.
    """
    if timezone.is_naive(failed_at):
        raise DecisionTransitionError(
            code="invalid_transition_time",
            message="Время перехода должно содержать часовой пояс.",
        )

    if approved_by is None:
        raise DecisionTransitionError(
            code="invalid_actor",
            message="Для подтверждения решения необходим пользователь.",
        )

    error_message = ACTION_FAILURE_MESSAGES.get(reason)
    if error_message is None:
        raise DecisionTransitionError(
            code="invalid_action_failure_reason",
            message="Передана неизвестная причина ошибки действия.",
        )

    try:
        with transaction.atomic():
            decision = _get_locked_decision(
                workspace_id=workspace_id,
                run_id=run_id,
                decision_id=decision_id,
            )

            if decision is None:
                raise DecisionTransitionError(
                    code="decision_not_found",
                    message=(
                        "Решение не найдено в текущем рабочем пространстве."
                    ),
                )

            if decision.status == AvitoListingDecision.Status.FAILED:
                return DecisionTransitionResult(
                    decision=decision,
                    changed=False,
                )

            if (
                    decision.status
                    != AvitoListingDecision.Status.PENDING_APPROVAL
            ):
                raise DecisionTransitionError(
                    code="invalid_decision_state",
                    message=(
                        "Ошибка действия может быть сохранена только "
                        "для ожидающего решения."
                    ),
                )

            automation_run = _get_locked_run(
                workspace_id=workspace_id,
                run_id=run_id,
            )
            run_result = _get_locked_run_result(
                workspace_id=workspace_id,
                run_id=run_id,
            )

            if (
                    automation_run.status
                    != AutomationRun.Status.WAITING_APPROVAL
            ):
                raise DecisionTransitionError(
                    code="invalid_run_state",
                    message=(
                        "Запуск больше не ожидает подтверждения решений."
                    ),
                )

            decision.status = AvitoListingDecision.Status.FAILED
            decision.approved_by = approved_by
            decision.approved_at = failed_at
            decision.action_applied_at = None
            decision.required_export_revision = None
            decision.terminal_at = failed_at
            decision.error_code = "action_failed"
            decision.error_message = error_message
            decision.save(
                update_fields=[
                    "status",
                    "approved_by",
                    "approved_at",
                    "action_applied_at",
                    "required_export_revision",
                    "terminal_at",
                    "error_code",
                    "error_message",
                    "updated_at",
                ],
            )

            pending_approval = _count_pending_decisions(
                run_id=automation_run.id,
            )
            failed_actions = AvitoListingDecision.objects.filter(
                run_id=automation_run.id,
                status=AvitoListingDecision.Status.FAILED,
            ).count()

            run_result.pending_approval = pending_approval
            run_result.failed_actions = failed_actions
            run_result.save(
                update_fields=[
                    "pending_approval",
                    "failed_actions",
                    "updated_at",
                ],
            )

            if pending_approval == 0:
                _finish_run_after_last_pending_decision(
                    automation_run=automation_run,
                    transition_at=failed_at,
                )

            return DecisionTransitionResult(
                decision=decision,
                changed=True,
            )
    except OperationalError as error:
        if not is_lock_conflict(error):
            raise

        raise DecisionTransitionError(
            code="resource_busy",
            message=(
                "Решение сейчас обрабатывается другим запросом. "
                "Повторите попытку позже."
            ),
        ) from error
