from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4
from datetime import timedelta
import logging

from automations.error_policy import (
    RunErrorClassification,
    classify_infrastructure_error,
)

from django.db import transaction
from django.utils import timezone

from automations.models import AutomationRun
from automations.registry import (
    AutomationModuleDefinition,
    get_module_definition,
)

from .run_readiness import (
    DATA_WAIT_MAX_DURATION,
    cancel_expired_data_wait,
    check_run_data_readiness,
)

from .run_recovery import RUN_HEARTBEAT_TIMEOUT

logger = logging.getLogger(__name__)

RUNNABLE_STATUSES = (
    AutomationRun.Status.QUEUED,
    AutomationRun.Status.WAITING_FOR_DATA,
)

RUN_RETRY_DELAYS = (
    timedelta(seconds=60),
    timedelta(seconds=120),
    timedelta(seconds=240),
)


@dataclass(frozen=True, slots=True)
class RunExecutionResult:
    """Итог одной попытки обработки run."""

    run_id: int
    status: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class _ClaimedRun:
    """Run и token, принадлежащие текущему worker."""

    run: AutomationRun
    run_token: UUID


def execute_run(
        *,
        run_id: int,
) -> RunExecutionResult:
    """
    Проверяет данные, захватывает run, вычисляет и сохраняет результат.

    Долгое вычисление выполняется вне транзакции. Захват и финальное
    сохранение являются двумя отдельными короткими транзакциями.
    """

    current_state = (
        AutomationRun.objects
        .filter(id=run_id)
        .values(
            "status",
            "next_attempt_at",
            "wait_started_at",
            "module_type_snapshot",
        )
        .first()
    )
    if current_state is None:
        return RunExecutionResult(
            run_id=run_id,
            status="skipped",
            reason="run_not_found",
        )

    if current_state["status"] not in RUNNABLE_STATUSES:
        return RunExecutionResult(
            run_id=run_id,
            status="skipped",
            reason="run_not_runnable",
        )

    checked_at = timezone.now()

    if (
            current_state["status"]
            == AutomationRun.Status.WAITING_FOR_DATA
    ):
        wait_started_at = current_state["wait_started_at"]
        if (
                wait_started_at is not None
                and checked_at
                >= wait_started_at + DATA_WAIT_MAX_DURATION
        ):
            cancelled = cancel_expired_data_wait(
                run_id=run_id,
                cancelled_at=checked_at,
            )
            if cancelled:
                return RunExecutionResult(
                    run_id=run_id,
                    status="cancelled",
                    reason="data_wait_expired",
                )

            return RunExecutionResult(
                run_id=run_id,
                status="skipped",
                reason="run_not_runnable",
            )

    next_attempt_at = current_state["next_attempt_at"]
    if (
            next_attempt_at is not None
            and next_attempt_at > checked_at
    ):
        return RunExecutionResult(
            run_id=run_id,
            status=current_state["status"],
            reason="not_due",
        )

    module_definition = None

    try:
        module_definition = get_module_definition(
            current_state["module_type_snapshot"],
        )
        readiness = check_run_data_readiness(
            run_id=run_id,
        )
    except Exception as error:
        return _handle_run_error(
            run_id=run_id,
            run_token=None,
            module_definition=module_definition,
            error=error,
            handled_at=timezone.now(),
        )

    if not readiness.is_ready:
        return RunExecutionResult(
            run_id=run_id,
            status="waiting_for_data",
            reason=readiness.reason,
        )

    try:
        claimed = _claim_run(run_id=run_id)
    except Exception as error:
        return _handle_run_error(
            run_id=run_id,
            run_token=None,
            module_definition=module_definition,
            error=error,
            handled_at=timezone.now(),
        )
    if claimed is None:
        return RunExecutionResult(
            run_id=run_id,
            status="skipped",
            reason="run_not_runnable",
        )

    lease_acquired = False

    try:
        lease_acquired_at = timezone.now()
        lease_acquired = module_definition.acquire_run_lease(
            run=claimed.run,
            run_token=claimed.run_token,
            acquired_at=lease_acquired_at,
        )
        if not lease_acquired:
            conflict_status = _resolve_run_after_error(
                run_id=run_id,
                run_token=claimed.run_token,
                handled_at=lease_acquired_at,
                error_code="account_busy",
                error_message=(
                    "Avito-аккаунт занят другим запуском автоматизации."
                ),
                retryable=True,
            )
            if conflict_status is None:
                return RunExecutionResult(
                    run_id=run_id,
                    status="skipped",
                    reason="lost_ownership",
                )

            return RunExecutionResult(
                run_id=run_id,
                status=conflict_status,
                reason="account_busy",
            )

        outcome = module_definition.evaluate_run(
            run=claimed.run,
        )

        heartbeat_at = timezone.now()
        run_heartbeat_updated = _heartbeat_claimed_run(
            run_id=run_id,
            run_token=claimed.run_token,
            heartbeat_at=heartbeat_at,
        )
        if not run_heartbeat_updated:
            return RunExecutionResult(
                run_id=run_id,
                status="skipped",
                reason="lost_ownership",
            )

        lease_heartbeat_updated = (
            module_definition.heartbeat_run_lease(
                run=claimed.run,
                run_token=claimed.run_token,
                heartbeat_at=heartbeat_at,
            )
        )
        if not lease_heartbeat_updated:
            conflict_status = _resolve_run_after_error(
                run_id=run_id,
                run_token=claimed.run_token,
                handled_at=heartbeat_at,
                error_code="lease_lost",
                error_message=(
                    "Run потерял lease Avito-аккаунта "
                    "до сохранения результата."
                ),
                retryable=True,
            )
            if conflict_status is None:
                return RunExecutionResult(
                    run_id=run_id,
                    status="skipped",
                    reason="lost_ownership",
                )

            return RunExecutionResult(
                run_id=run_id,
                status=conflict_status,
                reason="lease_lost",
            )

        final_status = _complete_run(
            run_id=run_id,
            run_token=claimed.run_token,
            module_definition=module_definition,
            outcome=outcome,
        )
        if final_status is None:
            return RunExecutionResult(
                run_id=run_id,
                status="skipped",
                reason="lost_ownership",
            )

        return RunExecutionResult(
            run_id=run_id,
            status=final_status,
        )
    except Exception as error:
        return _handle_run_error(
            run_id=run_id,
            run_token=claimed.run_token,
            module_definition=module_definition,
            error=error,
            handled_at=timezone.now(),
        )
    finally:
        if lease_acquired:
            try:
                module_definition.release_run_lease(
                    run=claimed.run,
                    run_token=claimed.run_token,
                )
            except Exception:
                # Lease имеет конечный срок и не заблокирует аккаунт
                # навсегда даже при временной ошибке освобождения.
                logger.exception(
                    "Не удалось освободить account lease run_id=%s.",
                    run_id,
                )


def _claim_run(
        *,
        run_id: int,
) -> _ClaimedRun | None:
    with transaction.atomic():
        run = (
            AutomationRun.objects
            .select_for_update()
            .filter(id=run_id)
            .first()
        )
        if run is None or run.status not in RUNNABLE_STATUSES:
            return None

        claimed_at = timezone.now()
        run_token = uuid4()

        run.status = AutomationRun.Status.EVALUATING
        run.run_token = run_token
        run.heartbeat_at = claimed_at
        run.next_attempt_at = (
                claimed_at + RUN_HEARTBEAT_TIMEOUT
        )
        run.error_code = ""
        run.error_message = ""

        update_fields = [
            "status",
            "run_token",
            "heartbeat_at",
            "next_attempt_at",
            "error_code",
            "error_message",
            "updated_at",
        ]

        if run.started_at is None:
            run.started_at = claimed_at
            update_fields.append("started_at")

        run.save(update_fields=update_fields)

    return _ClaimedRun(
        run=run,
        run_token=run_token,
    )


def _heartbeat_claimed_run(
        *,
        run_id: int,
        run_token: UUID,
        heartbeat_at,
) -> bool:
    """Обновляет heartbeat только для run текущего worker."""

    updated = (
        AutomationRun.objects
        .filter(
            id=run_id,
            status=AutomationRun.Status.EVALUATING,
            run_token=run_token,
        )
        .update(
            heartbeat_at=heartbeat_at,
            next_attempt_at=(
                    heartbeat_at + RUN_HEARTBEAT_TIMEOUT
            ),
            updated_at=heartbeat_at,
        )
    )

    return updated == 1


def _handle_run_error(
        *,
        run_id: int,
        run_token: UUID | None,
        module_definition: AutomationModuleDefinition | None,
        error: Exception,
        handled_at,
) -> RunExecutionResult:
    """Классифицирует ошибку и безопасно завершает попытку run."""

    classification = classify_infrastructure_error(error)

    if classification is None and module_definition is not None:
        classification = module_definition.classify_run_error(error)

    if classification is None:
        classification = RunErrorClassification(
            error_code="internal_error",
            retryable=False,
            safe_message=(
                "Внутренняя ошибка выполнения автоматизации."
            ),
        )

    logger.exception(
        "Ошибка выполнения automation run_id=%s, code=%s.",
        run_id,
        classification.error_code,
    )

    resolved_status = _resolve_run_after_error(
        run_id=run_id,
        run_token=run_token,
        handled_at=handled_at,
        error_code=classification.error_code,
        error_message=classification.safe_message,
        retryable=classification.retryable,
    )
    if resolved_status is None:
        return RunExecutionResult(
            run_id=run_id,
            status="skipped",
            reason="lost_ownership",
        )

    return RunExecutionResult(
        run_id=run_id,
        status=resolved_status,
        reason=classification.error_code,
    )


def _resolve_run_after_error(
        *,
        run_id: int,
        run_token: UUID | None,
        handled_at,
        error_code: str,
        error_message: str,
        retryable: bool,
) -> str | None:
    """
    Повторяет временную ошибку или завершает run как failed.

    Изменение разрешено только текущему владельцу token. До claim
    допускается изменение только queued/waiting_for_data run.
    """

    with transaction.atomic():
        run = (
            AutomationRun.objects
            .select_for_update()
            .filter(id=run_id)
            .first()
        )
        if run is None:
            return None

        if run_token is None:
            owns_run = (
                    run.status in RUNNABLE_STATUSES
                    and run.run_token is None
            )
        else:
            owns_run = (
                    run.status == AutomationRun.Status.EVALUATING
                    and run.run_token == run_token
            )

        if not owns_run:
            return None

        run.run_token = None
        run.heartbeat_at = None
        run.error_code = error_code
        run.error_message = error_message

        update_fields = [
            "status",
            "next_attempt_at",
            "run_token",
            "heartbeat_at",
            "error_code",
            "error_message",
            "updated_at",
        ]

        can_retry = (
                retryable
                and run.retry_count < len(RUN_RETRY_DELAYS)
        )

        if can_retry:
            retry_delay = RUN_RETRY_DELAYS[run.retry_count]
            run.status = AutomationRun.Status.QUEUED
            run.retry_count += 1
            run.next_attempt_at = handled_at + retry_delay
            update_fields.append("retry_count")
        else:
            run.status = AutomationRun.Status.FAILED
            run.finished_at = handled_at
            run.next_attempt_at = None
            update_fields.append("finished_at")

        run.save(update_fields=update_fields)

    return run.status


def _complete_run(
        *,
        run_id: int,
        run_token: UUID,
        module_definition: AutomationModuleDefinition,
        outcome: Any,
) -> str | None:
    """Атомарно сохраняет результат и итоговый статус run."""

    with transaction.atomic():
        run = (
            AutomationRun.objects
            .select_for_update()
            .filter(id=run_id)
            .first()
        )
        if (
                run is None
                or run.status != AutomationRun.Status.EVALUATING
                or run.run_token != run_token
        ):
            return None

        final_status = module_definition.save_run_evaluation(
            run=run,
            outcome=outcome,
        )
        if final_status not in {
            AutomationRun.Status.COMPLETED,
            AutomationRun.Status.WAITING_APPROVAL,
        }:
            raise ValueError(
                "Предметный модуль вернул недопустимый "
                "итоговый статус run."
            )

        run.status = final_status
        run.finished_at = (
            timezone.now()
            if final_status == AutomationRun.Status.COMPLETED
            else None
        )
        run.run_token = None
        run.heartbeat_at = None
        run.next_attempt_at = None
        run.error_code = ""
        run.error_message = ""
        run.save(
            update_fields=[
                "status",
                "finished_at",
                "run_token",
                "heartbeat_at",
                "next_attempt_at",
                "error_code",
                "error_message",
                "updated_at",
            ],
        )

    return final_status
