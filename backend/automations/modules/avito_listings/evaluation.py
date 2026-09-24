from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from itertools import islice
from types import MappingProxyType
from typing import Any

from accounts.models import Workspace
from avitotask.models import AvitoAccount

from .evaluator import (
    CompiledConditionPlan,
    MetricWindow,
    evaluate_condition_plan,
)
from .metric_aggregation import (
    aggregate_listing_metric_windows,
)
from .selectors import (
    get_listing_selection_snapshot,
    partition_listing_ids_by_coverage,
    select_eligible_listing_rows,
)

EVALUATION_CHUNK_SIZE = 500
MIN_ACTIONS_PER_RUN = 1
MAX_ACTIONS_PER_RUN = 100


@dataclass(frozen=True, slots=True)
class EvaluatedListingMatch:
    """Совпавшее объявление, выбранное в пределах лимита запуска."""

    listing_id: int
    active_since: datetime
    metrics_by_window: Mapping[MetricWindow, int]


@dataclass(frozen=True, slots=True)
class ListingEvaluationResult:
    """Неизменяемый результат полного вычисления объявлений."""

    target_max_id_snapshot: int

    checked: int
    ineligible: int
    insufficient_coverage: int
    not_matched: int
    matched: int
    deferred_by_run_limit: int

    selected_matches: tuple[EvaluatedListingMatch, ...]


class InvalidEvaluationLimitError(ValueError):
    """Некорректный лимит действий одного запуска."""

    def __init__(self, *, max_actions_per_run: Any):
        self.max_actions_per_run = max_actions_per_run
        super().__init__(
            "Лимит действий одного запуска должен быть целым "
            f"числом от {MIN_ACTIONS_PER_RUN} "
            f"до {MAX_ACTIONS_PER_RUN}.",
        )


class ListingSelectionChangedError(RuntimeError):
    """
    Выборка выросла относительно snapshot во время вычисления.

    Ошибка защищает счётчики от отрицательного `ineligible`. Следующий
    запуск создаст новый snapshot и повторно вычислит объявления.
    """

    def __init__(self, *, checked: int, eligible: int):
        self.checked = checked
        self.eligible = eligible
        super().__init__(
            "Количество eligible-объявлений превысило исходное "
            f"количество managed-объявлений: {eligible} > {checked}.",
        )


def evaluate_listing_candidates(
        *,
        workspace: Workspace,
        avito_account: AvitoAccount,
        plan: CompiledConditionPlan,
        max_actions_per_run: int,
) -> ListingEvaluationResult:
    """
    Пакетно вычисляет объявления без записи результата в базу данных.

    Функция используется как общее вычислительное ядро будущих preview
    и manual run. Она не создаёт decisions, не меняет объявления и не
    сохраняет частичный результат при исключении.
    """

    _validate_action_limit(max_actions_per_run)

    snapshot = get_listing_selection_snapshot(
        workspace=workspace,
        avito_account=avito_account,
    )

    checked = snapshot.checked
    eligible = 0
    insufficient_coverage = 0
    not_matched = 0
    matched = 0
    selected_matches: list[EvaluatedListingMatch] = []

    eligible_rows = (
        select_eligible_listing_rows(
            workspace=workspace,
            avito_account=avito_account,
            plan=plan,
            target_max_id_snapshot=(
                snapshot.target_max_id_snapshot
            ),
        )
        .iterator(chunk_size=EVALUATION_CHUNK_SIZE)
    )

    for chunk in _iter_chunks(
            eligible_rows,
            chunk_size=EVALUATION_CHUNK_SIZE,
    ):
        eligible += len(chunk)

        if eligible > checked:
            raise ListingSelectionChangedError(
                checked=checked,
                eligible=eligible,
            )

        chunk_rows_by_id = {
            row["id"]: row
            for row in chunk
        }
        chunk_listing_ids = tuple(chunk_rows_by_id)

        coverage = partition_listing_ids_by_coverage(
            workspace=workspace,
            avito_account=avito_account,
            listing_ids=chunk_listing_ids,
            plan=plan,
        )

        insufficient_coverage += len(
            coverage.insufficient_listing_ids,
        )

        if not coverage.covered_listing_ids:
            continue

        aggregations = aggregate_listing_metric_windows(
            workspace=workspace,
            avito_account=avito_account,
            listing_ids=coverage.covered_listing_ids,
            plan=plan,
        )

        for aggregation in aggregations:
            is_matched = evaluate_condition_plan(
                plan,
                aggregation.metrics_by_window,
            )

            if not is_matched:
                not_matched += 1
                continue

            matched += 1

            if len(selected_matches) >= max_actions_per_run:
                continue

            listing_row = chunk_rows_by_id[
                aggregation.listing_id
            ]
            selected_matches.append(
                EvaluatedListingMatch(
                    listing_id=aggregation.listing_id,
                    active_since=listing_row["active_since"],
                    metrics_by_window=MappingProxyType(
                        dict(aggregation.metrics_by_window),
                    ),
                ),
            )

    ineligible = checked - eligible

    return ListingEvaluationResult(
        target_max_id_snapshot=(
            snapshot.target_max_id_snapshot
        ),
        checked=checked,
        ineligible=ineligible,
        insufficient_coverage=insufficient_coverage,
        not_matched=not_matched,
        matched=matched,
        deferred_by_run_limit=(
                matched - len(selected_matches)
        ),
        selected_matches=tuple(selected_matches),
    )


def _validate_action_limit(max_actions_per_run: Any) -> None:
    if (
            type(max_actions_per_run) is not int
            or max_actions_per_run < MIN_ACTIONS_PER_RUN
            or max_actions_per_run > MAX_ACTIONS_PER_RUN
    ):
        raise InvalidEvaluationLimitError(
            max_actions_per_run=max_actions_per_run,
        )


def _iter_chunks(
        rows: Iterable[dict[str, Any]],
        *,
        chunk_size: int,
) -> Iterable[tuple[dict[str, Any], ...]]:
    """Лениво разделяет конечный queryset на ограниченные пакеты."""

    iterator = iter(rows)

    while True:
        chunk = tuple(islice(iterator, chunk_size))
        if not chunk:
            return

        yield chunk
