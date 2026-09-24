from dataclasses import dataclass
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from automations.models import AutomationRun
from automations.registry import get_module_definition

READINESS_ALLOWED_STATUSES = (
    AutomationRun.Status.QUEUED,
    AutomationRun.Status.WAITING_FOR_DATA,
)

DATA_WAIT_RETRY_DELAYS = (
    timedelta(minutes=10),
    timedelta(minutes=30),
    timedelta(hours=1),
    timedelta(hours=2),
)
DATA_WAIT_MAX_DURATION = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class RunDataReadiness:
    """Результат проверки готовности данных одного run."""

    run_id: int
    is_ready: bool
    reason: str | None
    required_from: date
    required_to: date
    sync_status: str | None


class RunDataReadinessError(RuntimeError):
    """Контролируемая ошибка проверки готовности данных run."""

    def __init__(
            self,
            *,
            code: str,
            message: str,
            run_id: int,
    ):
        self.code = code
        self.run_id = run_id
        super().__init__(message)


def check_run_data_readiness(
        *,
        run_id: int,
) -> RunDataReadiness:
    """
    Проверяет готовность данных и при необходимости переводит run в ожидание.

    Предметная проверка выполняется без транзакции. Если статистика не
    готова, состояние run сохраняется отдельной короткой транзакцией.
    """

    run = (
        AutomationRun.objects
        .filter(id=run_id)
        .first()
    )
    if run is None:
        raise RunDataReadinessError(
            code="run_not_found",
            message="Run автоматизации не найден.",
            run_id=run_id,
        )

    _validate_run_status(run)

    module_definition = get_module_definition(
        run.module_type_snapshot,
    )
    module_readiness = (
        module_definition.get_run_data_readiness(
            run=run,
        )
    )

    readiness = RunDataReadiness(
        run_id=run.id,
        is_ready=module_readiness.is_ready,
        reason=module_readiness.reason,
        required_from=module_readiness.required_from,
        required_to=module_readiness.required_to,
        sync_status=module_readiness.sync_status,
    )

    if readiness.is_ready:
        return readiness

    _mark_run_waiting_for_data(
        run_id=run.id,
        readiness=readiness,
    )

    return readiness


def _get_data_wait_retry_delay(
        *,
        attempt_count: int,
) -> timedelta:
    """
    Возвращает задержку перед следующей проверкой данных.

    Начиная с четвёртой неуспешной проверки используется постоянная
    задержка два часа, поэтому частота запросов к статистике ограничена.
    """

    delay_index = min(
        attempt_count - 1,
        len(DATA_WAIT_RETRY_DELAYS) - 1,
    )
    return DATA_WAIT_RETRY_DELAYS[delay_index]


def _validate_run_status(run: AutomationRun) -> None:
    if run.status not in READINESS_ALLOWED_STATUSES:
        raise RunDataReadinessError(
            code="invalid_run_state",
            message=(
                "Проверка готовности данных разрешена только для "
                "queued или waiting_for_data run."
            ),
            run_id=run.id,
        )


def _mark_run_waiting_for_data(
        *,
        run_id: int,
        readiness: RunDataReadiness,
) -> None:
    checked_at = timezone.now()

    with transaction.atomic():
        run = (
            AutomationRun.objects
            .select_for_update()
            .filter(id=run_id)
            .first()
        )
        if run is None:
            raise RunDataReadinessError(
                code="run_not_found",
                message="Run автоматизации не найден.",
                run_id=run_id,
            )

        _validate_run_status(run)

        attempt_count = run.data_wait_attempt_count + 1
        retry_delay = _get_data_wait_retry_delay(
            attempt_count=attempt_count,
        )

        run.status = AutomationRun.Status.WAITING_FOR_DATA
        run.data_wait_attempt_count = attempt_count
        run.next_attempt_at = checked_at + retry_delay
        run.error_code = "insufficient_data"
        run.error_message = (
            "Статистика аккаунта не готова для диапазона "
            f"{readiness.required_from.isoformat()} — "
            f"{readiness.required_to.isoformat()}. "
            f"Причина: {readiness.reason or 'unknown'}."
        )

        update_fields = [
            "status",
            "data_wait_attempt_count",
            "next_attempt_at",
            "error_code",
            "error_message",
            "updated_at",
        ]

        if run.wait_started_at is None:
            run.wait_started_at = checked_at
            update_fields.append("wait_started_at")

        run.save(update_fields=update_fields)


def cancel_expired_data_wait(
        *,
        run_id: int,
        cancelled_at=None,
) -> bool:
    """
    Отменяет run, если ожидание статистики достигло 24 часов.

    Возвращает True только тогда, когда текущий вызов действительно
    выполнил переход в cancelled.
    """

    effective_cancelled_at = cancelled_at or timezone.now()

    with transaction.atomic():
        run = (
            AutomationRun.objects
            .select_for_update()
            .filter(id=run_id)
            .first()
        )
        if (
                run is None
                or run.status
                != AutomationRun.Status.WAITING_FOR_DATA
                or run.wait_started_at is None
                or effective_cancelled_at
                < run.wait_started_at + DATA_WAIT_MAX_DURATION
        ):
            return False

        run.status = AutomationRun.Status.CANCELLED
        run.finished_at = effective_cancelled_at
        run.next_attempt_at = None
        run.run_token = None
        run.heartbeat_at = None
        run.error_code = "data_wait_expired"
        run.error_message = (
            "Run отменён: статистика не стала доступна "
            "в течение 24 часов."
        )
        run.save(
            update_fields=[
                "status",
                "finished_at",
                "next_attempt_at",
                "run_token",
                "heartbeat_at",
                "error_code",
                "error_message",
                "updated_at",
            ],
        )

    return True
