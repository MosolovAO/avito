from dataclasses import dataclass

from billiard.exceptions import SoftTimeLimitExceeded
from django.db import InterfaceError, OperationalError


@dataclass(frozen=True, slots=True)
class RunErrorClassification:
    """Безопасная классификация ошибки выполнения run."""

    error_code: str
    retryable: bool
    safe_message: str


def classify_infrastructure_error(
        error: Exception,
) -> RunErrorClassification | None:
    """
    Классифицирует только известные инфраструктурные ошибки.

    Неизвестная ошибка возвращается вызывающему коду для безопасной
    обработки как internal_error без автоматического retry.
    """

    if isinstance(error, (SoftTimeLimitExceeded, TimeoutError)):
        return RunErrorClassification(
            error_code="time_limit",
            retryable=False,
            safe_message=(
                "Вычисление автоматизации превысило допустимое время."
            ),
        )

    if isinstance(error, (OperationalError, InterfaceError)):
        return RunErrorClassification(
            error_code="transient_database_error",
            retryable=True,
            safe_message=(
                "Временная ошибка соединения с базой данных."
            ),
        )

    return None
