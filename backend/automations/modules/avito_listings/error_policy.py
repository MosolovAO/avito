from automations.error_policy import RunErrorClassification

from .evaluation import (
    InvalidEvaluationLimitError,
    ListingSelectionChangedError,
)
from .evaluator import (
    ConditionPlanCompilationError,
    InvalidMetricValueError,
    MissingMetricValueError,
)
from .run_lease import RunLeaseTargetError
from .run_readiness import InvalidAvitoListingRunResultError
from .validators import (
    ActionValidationError,
    ConditionTreeValidationError,
)

VALIDATION_ERRORS = (
    ConditionTreeValidationError,
    ActionValidationError,
    ConditionPlanCompilationError,
)

CONFIGURATION_ERRORS = (
    InvalidAvitoListingRunResultError,
    InvalidEvaluationLimitError,
    MissingMetricValueError,
    InvalidMetricValueError,
    RunLeaseTargetError,
)


def classify_run_error(
        error: Exception,
) -> RunErrorClassification | None:
    """
    Классифицирует только ошибки модуля объявлений Avito.

    Неизвестные исключения возвращаются общему executor-у, который
    обработает их как internal_error без раскрытия исходного сообщения.
    """

    if isinstance(error, VALIDATION_ERRORS):
        return RunErrorClassification(
            error_code="validation_error",
            retryable=False,
            safe_message=(
                "Конфигурация условий автоматизации "
                "не прошла проверку."
            ),
        )

    if isinstance(error, CONFIGURATION_ERRORS):
        return RunErrorClassification(
            error_code="configuration_error",
            retryable=False,
            safe_message=(
                "Run содержит некорректную конфигурацию модуля."
            ),
        )

    if isinstance(error, ListingSelectionChangedError):
        return RunErrorClassification(
            error_code="stale",
            retryable=False,
            safe_message=(
                "Состояние объявлений изменилось во время "
                "вычисления run."
            ),
        )

    return None
