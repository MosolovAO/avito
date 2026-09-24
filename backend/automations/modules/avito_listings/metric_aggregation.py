from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from django.db import OperationalError, connection, transaction
from django.db.models import Q, Sum

from accounts.models import Workspace
from analytics.models import AvitoListingDailyStats
from avitotask.models import AvitoAccount

from . import catalog
from .evaluator import CompiledConditionPlan, MetricWindow

DEFAULT_STATEMENT_TIMEOUT_SECONDS = 180
QUERY_CANCELED_SQLSTATE = "57014"


@dataclass(frozen=True, slots=True)
class ListingMetricAggregation:
    """Агрегированные метрики одного объявления."""

    listing_id: int
    metrics_by_window: Mapping[MetricWindow, int]


class MetricAggregationTimeoutError(TimeoutError):
    """SQL-агрегация не завершилась за разрешённое время."""

    def __init__(self, *, timeout_seconds: int):
        self.timeout_seconds = timeout_seconds
        super().__init__(
            "Агрегация статистики объявлений превысила "
            f"лимит {timeout_seconds} секунд.",
        )


def aggregate_listing_metric_windows(
        *,
        workspace: Workspace,
        avito_account: AvitoAccount,
        listing_ids: Iterable[int],
        plan: CompiledConditionPlan,
) -> tuple[ListingMetricAggregation, ...]:
    """
    Пакетно агрегирует метрики объявлений для всех окон плана.

    Функция должна получать только объявления, для которых предыдущий
    этап уже подтвердил полноту coverage. Поэтому отсутствие строки
    дневной статистики внутри окна означает подтверждённый ноль.

    Порядок идентификаторов сохраняется, повторения удаляются.
    """

    ordered_listing_ids = tuple(dict.fromkeys(listing_ids))
    if not ordered_listing_ids:
        return ()

    annotations, aliases_by_window = _build_annotations(plan)

    date_from = min(
        window.date_from
        for window in plan.windows
    )
    date_to = max(
        window.date_to
        for window in plan.windows
    )

    rows = _fetch_rows_with_timeout(
        workspace=workspace,
        avito_account=avito_account,
        listing_ids=ordered_listing_ids,
        date_from=date_from,
        date_to=date_to,
        annotations=annotations,
        timeout_seconds=DEFAULT_STATEMENT_TIMEOUT_SECONDS,
    )
    rows_by_listing_id = {
        row["listing_id"]: row
        for row in rows
    }

    return tuple(
        _build_listing_result(
            listing_id=listing_id,
            row=rows_by_listing_id.get(listing_id),
            plan=plan,
            aliases_by_window=aliases_by_window,
        )
        for listing_id in ordered_listing_ids
    )


def _build_annotations(
        plan: CompiledConditionPlan,
) -> tuple[
    dict[str, Any],
    dict[MetricWindow, str],
]:
    annotations: dict[str, Any] = {}
    aliases_by_window: dict[MetricWindow, str] = {}

    for index, window in enumerate(plan.windows):
        metric_definition = catalog.METRICS_BY_CODE[
            window.metric
        ]
        alias = f"metric_{index}"

        annotations[alias] = Sum(
            metric_definition.stats_field,
            filter=Q(
                date__gte=window.date_from,
                date__lte=window.date_to,
            ),
        )
        aliases_by_window[window] = alias

    return annotations, aliases_by_window


def _fetch_rows_with_timeout(
        *,
        workspace: Workspace,
        avito_account: AvitoAccount,
        listing_ids: tuple[int, ...],
        date_from,
        date_to,
        annotations: Mapping[str, Any],
        timeout_seconds: int,
) -> tuple[dict[str, Any], ...]:
    """
    Выполняет агрегацию с локальным PostgreSQL statement_timeout.

    Вложенный atomic создаёт savepoint, поэтому query_canceled не
    ломает внешнюю транзакцию вызывающего сервиса. Предыдущее значение
    timeout восстанавливается и при успешном выполнении.
    """

    try:
        with transaction.atomic():
            previous_timeout = _get_statement_timeout()
            _set_local_statement_timeout(
                f"{timeout_seconds}s",
            )

            rows = _fetch_aggregated_rows(
                workspace=workspace,
                avito_account=avito_account,
                listing_ids=listing_ids,
                date_from=date_from,
                date_to=date_to,
                annotations=annotations,
            )

            _set_local_statement_timeout(previous_timeout)
            return rows
    except OperationalError as exc:
        if _get_sqlstate(exc) == QUERY_CANCELED_SQLSTATE:
            raise MetricAggregationTimeoutError(
                timeout_seconds=timeout_seconds,
            ) from exc

        raise


def _fetch_aggregated_rows(
        *,
        workspace: Workspace,
        avito_account: AvitoAccount,
        listing_ids: tuple[int, ...],
        date_from,
        date_to,
        annotations: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Выполняет единственный GROUP BY запрос к дневной статистике."""

    queryset = (
        AvitoListingDailyStats.objects
        .filter(
            workspace=workspace,
            listing_id__in=listing_ids,
            listing__workspace=workspace,
            listing__avito_account=avito_account,
            date__gte=date_from,
            date__lte=date_to,
        )
        .values("listing_id")
        .annotate(**annotations)
        .order_by()
    )

    return tuple(queryset)


def _build_listing_result(
        *,
        listing_id: int,
        row: Mapping[str, Any] | None,
        plan: CompiledConditionPlan,
        aliases_by_window: Mapping[MetricWindow, str],
) -> ListingMetricAggregation:
    metrics_by_window = {
        window: _read_metric_value(
            row=row,
            alias=aliases_by_window[window],
        )
        for window in plan.windows
    }

    return ListingMetricAggregation(
        listing_id=listing_id,
        metrics_by_window=MappingProxyType(
            metrics_by_window,
        ),
    )


def _read_metric_value(
        *,
        row: Mapping[str, Any] | None,
        alias: str,
) -> int:
    if row is None:
        return 0

    value = row.get(alias)
    if value is None:
        return 0

    return int(value)


def _get_statement_timeout() -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT current_setting('statement_timeout')",
        )
        row = cursor.fetchone()

    return row[0]


def _set_local_statement_timeout(value: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            (
                "SELECT set_config("
                "'statement_timeout', %s, true"
                ")"
            ),
            [value],
        )


def _get_sqlstate(error: BaseException) -> str | None:
    """
    Ищет PostgreSQL SQLSTATE в исключении Django и его причине.

    Поддерживаются как psycopg 3 с `sqlstate`, так и psycopg 2
    с устаревшим атрибутом `pgcode`.
    """

    current_error: BaseException | None = error
    visited_errors: set[int] = set()

    while (
            current_error is not None
            and id(current_error) not in visited_errors
    ):
        visited_errors.add(id(current_error))

        sqlstate = (
                getattr(current_error, "sqlstate", None)
                or getattr(current_error, "pgcode", None)
        )
        if sqlstate:
            return sqlstate

        current_error = (
                current_error.__cause__
                or current_error.__context__
        )

    return None
