from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from . import catalog

GROUP_NODE_TYPE = "group"
CONDITION_NODE_TYPE = "condition"

GROUP_OPERATORS = frozenset({
    "and",
    "or",
})

GROUP_FIELDS = frozenset({
    "type",
    "operators",
    "children",
})

CONDITION_FIELDS = frozenset({
    "type",
    "metric",
    "aggregation",
    "window_days",
    "comparator",
    "value",
})

REQUIRED_CONDITION_FIELDS = (
    "metric",
    "aggregation",
    "window_days",
    "comparator",
    "value",
)


@dataclass(slots=True)
class _ValidationContext:
    """Состояние одного прохода по дереву условий."""

    ancestor_ids: set[int] = field(default_factory=set)
    condition_count: int = 0


class ConditionTreeValidationError(ValueError):
    """Ошибка в структуре или значениях дерева условий автоматизации."""

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


class ActionValidationError(ValueError):
    """Ошибка типа или конфигурации действия автоматизации."""

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


def validate_condition_tree(
        condition_tree: Any,
) -> Any:
    """
    Проверяет дерево условий без изменения исходного объекта.

    Структура, листовые значения и ограничения проверяются за один
    рекурсивный проход.
    """

    if (
            not isinstance(condition_tree, Mapping)
            or condition_tree.get("type") != GROUP_NODE_TYPE
    ):
        _raise_validation_error(
            code="invalid_root",
            path="condition_tree",
            message=(
                "Корень дерева условий должен быть объектом типа group."
            ),
        )

    _validate_node(
        node=condition_tree,
        path="condition_tree",
        depth=1,
        context=_ValidationContext(),
    )

    return condition_tree


def validate_action(
        action_type: Any,
        action_config: Any,
) -> Any:
    """
    Проверяет тип и конфигурацию действия без изменения объекта.

    Допустимые действия и поля конфигурации берутся из каталога модуля.
    """

    if not _is_registered_code(
            action_type,
            catalog.ACTIONS_BY_CODE,
    ):
        raise ActionValidationError(
            code="unknown_action",
            path="action.type",
            message="Действие не зарегистрировано в модуле объявлений.",
        )

    if not isinstance(action_config, Mapping):
        raise ActionValidationError(
            code="invalid_action_config",
            path="action.config",
            message="Конфигурация действия должна быть объектом.",
        )

    action_definition = catalog.ACTIONS_BY_CODE[action_type]
    unknown_fields = [
        field
        for field in action_config
        if field not in action_definition.config_fields
    ]

    if unknown_fields:
        unknown_field = min(
            unknown_fields,
            key=lambda field: str(field),
        )

        raise ActionValidationError(
            code="unknown_action_config_field",
            path=f"action.config.{unknown_field}",
            message=(
                f"Поле {unknown_field!r} не поддерживается "
                f"действием {action_type!r}."
            ),
        )

    return action_config


def _validate_node(
        *,
        node: Any,
        path: str,
        depth: int,
        context: _ValidationContext,
) -> None:
    if not isinstance(node, Mapping):
        _raise_validation_error(
            code="invalid_node",
            path=path,
            message="Узел дерева условий должен быть объектом.",
        )

    node_id = id(node)
    if node_id in context.ancestor_ids:
        _raise_validation_error(
            code="cyclic_tree",
            path=path,
            message=(
                "Дерево условий не должно содержать циклические ссылки."
            ),
        )

    context.ancestor_ids.add(node_id)

    try:
        node_type = node.get("type")

        if node_type == GROUP_NODE_TYPE:
            _validate_group(
                node=node,
                path=path,
                depth=depth,
                context=context,
            )
            return

        if node_type == CONDITION_NODE_TYPE:
            _validate_condition(
                node=node,
                path=path,
                context=context,
            )
            return

        _raise_validation_error(
            code="unknown_node_type",
            path=path,
            message="Узел дерева условий имеет неизвестный тип.",
        )
    finally:
        context.ancestor_ids.remove(node_id)


def _validate_group(
        *,
        node: Mapping[str, Any],
        path: str,
        depth: int,
        context: _ValidationContext,
) -> None:
    _reject_unknown_fields(
        node=node,
        allowed_fields=GROUP_FIELDS,
        path=path,
    )

    if "operators" not in node:
        _raise_validation_error(
            code="missing_field",
            path=f"{path}.operators",
            message="В группе условий отсутствует список операторов.",
        )

    operators = node["operators"]

    if not isinstance(operators, list):
        _raise_validation_error(
            code="invalid_operators",
            path=f"{path}.operators",
            message="Операторы группы должны быть переданы списком.",
        )

    if "children" not in node:
        _raise_validation_error(
            code="missing_field",
            path=f"{path}.children",
            message="В группе условий отсутствует список дочерних узлов.",
        )

    children = node["children"]

    if not isinstance(children, list):
        _raise_validation_error(
            code="invalid_children",
            path=f"{path}.children",
            message=(
                "Дочерние узлы группы условий должны быть переданы списком."
            ),
        )

    if not children:
        _raise_validation_error(
            code="empty_children",
            path=f"{path}.children",
            message=(
                "Группа условий должна содержать хотя бы один дочерний узел."
            ),
        )

    if len(operators) != len(children) - 1:
        _raise_validation_error(
            code="invalid_operators_count",
            path=f"{path}.operators",
            message=(
                "Количество операторов должно быть на один меньше "
                "количества дочерних узлов."
            ),
        )

    for index, operator in enumerate(operators):
        if (
                not isinstance(operator, str)
                or operator not in GROUP_OPERATORS
        ):
            _raise_validation_error(
                code="invalid_operator",
                path=f"{path}.operators[{index}]",
                message=(
                    "Оператор группы условий должен иметь "
                    "значение and или or."
                ),
            )

    for index, child in enumerate(children):
        child_path = f"{path}.children[{index}]"

        if (
                depth == 1
                and isinstance(child, Mapping)
                and child.get("type") == CONDITION_NODE_TYPE
        ):
            _raise_validation_error(
                code="invalid_root_child",
                path=child_path,
                message="Корень дерева может содержать только группы.",
            )

        if (
                depth > 1
                and isinstance(child, Mapping)
                and child.get("type") == GROUP_NODE_TYPE
        ):
            _raise_validation_error(
                code="nested_group",
                path=child_path,
                message=(
                    "Пользовательская группа может содержать "
                    "только условия."
                ),
            )

        _validate_node(
            node=child,
            path=child_path,
            depth=depth + 1,
            context=context,
        )


def _validate_condition(
        *,
        node: Mapping[str, Any],
        path: str,
        context: _ValidationContext,
) -> None:
    _reject_unknown_fields(
        node=node,
        allowed_fields=CONDITION_FIELDS,
        path=path,
    )
    _require_condition_fields(
        node=node,
        path=path,
    )

    context.condition_count += 1
    if (
            context.condition_count
            > catalog.CONDITION_LIMITS["max_conditions"]
    ):
        _raise_validation_error(
            code="max_conditions_exceeded",
            path=path,
            message=(
                "Превышено максимально допустимое количество условий."
            ),
        )

    metric_code = node["metric"]
    if not _is_registered_code(
            metric_code,
            catalog.METRICS_BY_CODE,
    ):
        _raise_validation_error(
            code="unknown_metric",
            path=f"{path}.metric",
            message="Метрика условия не зарегистрирована.",
        )

    aggregation_code = node["aggregation"]
    if not _is_registered_code(
            aggregation_code,
            catalog.AGGREGATIONS_BY_CODE,
    ):
        _raise_validation_error(
            code="unknown_aggregation",
            path=f"{path}.aggregation",
            message="Агрегация условия не зарегистрирована.",
        )

    metric_definition = catalog.METRICS_BY_CODE[metric_code]
    if aggregation_code not in metric_definition.allowed_aggregations:
        _raise_validation_error(
            code="aggregation_not_allowed",
            path=f"{path}.aggregation",
            message=(
                "Выбранная агрегация недоступна для указанной метрики."
            ),
        )

    comparator_code = node["comparator"]
    if not _is_registered_code(
            comparator_code,
            catalog.COMPARATORS_BY_CODE,
    ):
        _raise_validation_error(
            code="unknown_comparator",
            path=f"{path}.comparator",
            message="Оператор сравнения не зарегистрирован.",
        )

    _validate_window_days(
        value=node["window_days"],
        path=f"{path}.window_days",
    )
    _validate_condition_value(
        value=node["value"],
        path=f"{path}.value",
    )


def _require_condition_fields(
        *,
        node: Mapping[str, Any],
        path: str,
) -> None:
    for field_name in REQUIRED_CONDITION_FIELDS:
        if field_name not in node:
            _raise_validation_error(
                code="missing_field",
                path=f"{path}.{field_name}",
                message=(
                    f"В условии отсутствует обязательное поле "
                    f"{field_name!r}."
                ),
            )


def _validate_window_days(
        *,
        value: Any,
        path: str,
) -> None:
    min_window_days = catalog.CONDITION_LIMITS["min_window_days"]
    max_window_days = catalog.CONDITION_LIMITS["max_window_days"]

    if (
            type(value) is not int
            or value < min_window_days
            or value > max_window_days
    ):
        _raise_validation_error(
            code="invalid_window_days",
            path=path,
            message=(
                "Период условия должен быть целым числом "
                f"от {min_window_days} до {max_window_days}."
            ),
        )


def _validate_condition_value(
        *,
        value: Any,
        path: str,
) -> None:
    if type(value) is not int or value < 0:
        _raise_validation_error(
            code="invalid_value",
            path=path,
            message=(
                "Значение условия должно быть целым неотрицательным числом."
            ),
        )


def _is_registered_code(
        value: Any,
        registry: Mapping[str, Any],
) -> bool:
    return isinstance(value, str) and value in registry


def _reject_unknown_fields(
        *,
        node: Mapping[str, Any],
        allowed_fields: frozenset[str],
        path: str,
) -> None:
    unknown_fields = [
        field
        for field in node
        if field not in allowed_fields
    ]

    if not unknown_fields:
        return

    unknown_field = min(
        unknown_fields,
        key=lambda field: str(field),
    )

    _raise_validation_error(
        code="unknown_field",
        path=f"{path}.{unknown_field}",
        message=(
            f"Поле {unknown_field!r} не поддерживается "
            "в этом узле дерева условий."
        ),
    )


def _raise_validation_error(
        *,
        code: str,
        path: str,
        message: str,
) -> None:
    raise ConditionTreeValidationError(
        code=code,
        path=path,
        message=message,
    )
