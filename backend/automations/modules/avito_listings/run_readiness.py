from automations.models import (
    AutomationRun,
    AvitoListingRunResult,
)

from .evaluator import compile_condition_plan
from .selectors import (
    AccountStatsReadiness,
    get_account_stats_readiness,
)


class InvalidAvitoListingRunResultError(RuntimeError):
    """Типизированный результат run отсутствует или нарушает workspace scope."""

    def __init__(self, *, run_id: int):
        self.run_id = run_id
        super().__init__(
            "Не удалось получить корректный результат "
            f"модуля объявлений Avito для run {run_id}.",
        )


def get_run_data_readiness(
        *,
        run: AutomationRun,
) -> AccountStatsReadiness:
    """
    Проверяет готовность статистики по зафиксированным данным run.

    Текущая конфигурация автоматизации намеренно не читается:
    вычисление должно воспроизводить snapshots, созданные вместе с run.
    """

    run_result = (
        AvitoListingRunResult.objects
        .select_related("avito_account")
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

    plan = compile_condition_plan(
        run_result.condition_snapshot,
        as_of_date=run_result.as_of_date,
    )

    return get_account_stats_readiness(
        workspace=run_result.workspace,
        avito_account=run_result.avito_account,
        plan=plan,
    )
