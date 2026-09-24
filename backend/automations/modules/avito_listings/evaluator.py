from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from .validators import (
    CONDITION_NODE_TYPE,
    GROUP_NODE_TYPE,
    validate_condition_tree,
)


@dataclass(frozen=True, slots=True)
class MetricWindow:
    """Уникальное статистическое окно одной метрики."""

    metric: str
    aggregation: str
    window_days: int
    date_from: date
    date_to: date


@dataclass(frozen=True, slots=True)
class CompiledCondition:
    """Подготовленное листовое условие."""

    window: MetricWindow
    comparator: str
    value: int


@dataclass(frozen=True, slots=True)
class CompiledGroup:
    """Подготовленная логическая группа условий."""

    operators: tuple[str, ...]
    children: tuple["CompiledNode", ...]


CompiledNode = CompiledCondition | CompiledGroup


@dataclass(frozen=True, slots=True)
class CompiledConditionPlan:
    """
    Неизменяемый план вычисления дерева условий.

    План создаётся один раз для запуска и затем применяется ко всем
    объявлениям без повторного разбора JSON.
    """

    as_of_date: date
    root: CompiledGroup
    windows: tuple[MetricWindow, ...]


class ConditionPlanCompilationError(ValueError):
    """Ошибка подготовки плана вычисления условий."""

    def __init__(
            self,
            *,
            code: str,
            path: str,
            message: str,
    ):
        self.code = code
        self.path = path
        super().__init__(message)


class MissingMetricValueError(LookupError):
    """Для вычисления отсутствует значение обязательного окна."""

    def __init__(self, window: MetricWindow):
        self.window = window
        super().__init__(
            "Отсутствует подготовленное значение метрики "
            f"{window.metric!r} за {window.window_days} дней.",
        )


class InvalidMetricValueError(ValueError):
    """Selector передал evaluator некорректное значение метрики."""

    def __init__(
            self,
            *,
            window: MetricWindow,
            value: Any,
    ):
        self.window = window
        self.value = value
        super().__init__(
            "Подготовленное значение метрики должно быть "
            f"целым неотрицательным числом: {value!r}.",
        )


def compile_condition_plan(
        condition_tree: Any,
        *,
        as_of_date: date,
) -> CompiledConditionPlan:
    """
    Валидирует и компилирует JSON-дерево в неизменяемый план.

    Текущий день не входит в статистические окна. Одинаковые сочетания
    метрики, агрегации и периода используют один объект MetricWindow.
    """

    if type(as_of_date) is not date:
        raise ConditionPlanCompilationError(
            code="invalid_as_of_date",
            path="as_of_date",
            message="Дата запуска должна быть календарной датой.",
        )

    validate_condition_tree(condition_tree)

    windows_by_key: dict[
        tuple[str, str, int],
        MetricWindow,
    ] = {}

    root = _compile_group(
        node=condition_tree,
        as_of_date=as_of_date,
        windows_by_key=windows_by_key,
    )

    return CompiledConditionPlan(
        as_of_date=as_of_date,
        root=root,
        windows=tuple(windows_by_key.values()),
    )


def evaluate_condition_plan(
        plan: CompiledConditionPlan,
        metrics_by_window: Mapping[MetricWindow, int],
) -> bool:
    """
    Вычисляет подготовленный план над метриками одного объявления.

    Перед вычислением проверяются все окна, включая ветки `or`. Поэтому
    истинная первая ветка не может скрыть отсутствие coverage второй ветки.
    """

    _validate_prepared_metric_values(
        windows=plan.windows,
        metrics_by_window=metrics_by_window,
    )

    return _evaluate_group(
        group=plan.root,
        metrics_by_window=metrics_by_window,
    )


def _compile_group(
        *,
        node: Mapping[str, Any],
        as_of_date: date,
        windows_by_key: dict[
            tuple[str, str, int],
            MetricWindow,
        ],
) -> CompiledGroup:
    return CompiledGroup(
        operators=tuple(node["operators"]),
        children=tuple(
            _compile_node(
                node=child,
                as_of_date=as_of_date,
                windows_by_key=windows_by_key,
            )
            for child in node["children"]
        ),
    )


def _compile_node(
        *,
        node: Mapping[str, Any],
        as_of_date: date,
        windows_by_key: dict[
            tuple[str, str, int],
            MetricWindow,
        ],
) -> CompiledNode:
    if node["type"] == GROUP_NODE_TYPE:
        return _compile_group(
            node=node,
            as_of_date=as_of_date,
            windows_by_key=windows_by_key,
        )

    if node["type"] == CONDITION_NODE_TYPE:
        return _compile_condition(
            node=node,
            as_of_date=as_of_date,
            windows_by_key=windows_by_key,
        )

    raise ConditionPlanCompilationError(
        code="unknown_node_type",
        path="condition_tree",
        message="Невозможно скомпилировать неизвестный тип узла.",
    )


def _compile_condition(
        *,
        node: Mapping[str, Any],
        as_of_date: date,
        windows_by_key: dict[
            tuple[str, str, int],
            MetricWindow,
        ],
) -> CompiledCondition:
    window_key = (
        node["metric"],
        node["aggregation"],
        node["window_days"],
    )

    window = windows_by_key.get(window_key)
    if window is None:
        window = MetricWindow(
            metric=node["metric"],
            aggregation=node["aggregation"],
            window_days=node["window_days"],
            date_from=(
                    as_of_date
                    - timedelta(days=node["window_days"])
            ),
            date_to=as_of_date - timedelta(days=1),
        )
        windows_by_key[window_key] = window

    return CompiledCondition(
        window=window,
        comparator=node["comparator"],
        value=node["value"],
    )


def _validate_prepared_metric_values(
        *,
        windows: tuple[MetricWindow, ...],
        metrics_by_window: Mapping[MetricWindow, int],
) -> None:
    for window in windows:
        if window not in metrics_by_window:
            raise MissingMetricValueError(window)

        value = metrics_by_window[window]
        if type(value) is not int or value < 0:
            raise InvalidMetricValueError(
                window=window,
                value=value,
            )


def _evaluate_group(
        *,
        group: CompiledGroup,
        metrics_by_window: Mapping[MetricWindow, int],
) -> bool:
    child_results = [
        _evaluate_node(
            node=child,
            metrics_by_window=metrics_by_window,
        )
        for child in group.children
    ]

    segment_results = [child_results[0]]

    for operator, child_result in zip(
            group.operators,
            child_results[1:],
    ):
        if operator == "and":
            segment_results[-1] = (
                    segment_results[-1] and child_result
            )
            continue

        if operator == "or":
            segment_results.append(child_result)
            continue

        raise RuntimeError(
            "Неизвестный оператор compiled-группы: "
            f"{operator!r}.",
        )

    return any(segment_results)


def _evaluate_node(
        *,
        node: CompiledNode,
        metrics_by_window: Mapping[MetricWindow, int],
) -> bool:
    if isinstance(node, CompiledGroup):
        return _evaluate_group(
            group=node,
            metrics_by_window=metrics_by_window,
        )

    actual_value = metrics_by_window[node.window]

    return _compare_values(
        comparator=node.comparator,
        actual_value=actual_value,
        expected_value=node.value,
    )


def _compare_values(
        *,
        comparator: str,
        actual_value: int,
        expected_value: int,
) -> bool:
    if comparator == "lt":
        return actual_value < expected_value

    if comparator == "lte":
        return actual_value <= expected_value

    if comparator == "eq":
        return actual_value == expected_value

    if comparator == "gte":
        return actual_value >= expected_value

    if comparator == "gt":
        return actual_value > expected_value

    raise RuntimeError(
        f"Неизвестный comparator compiled-условия: {comparator!r}.",
    )
