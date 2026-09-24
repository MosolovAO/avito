from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


MODULE_TYPE = "avito_listings"


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    """Описание метрики, доступной в условиях автоматизации."""

    code: str
    label: str
    description: str
    value_type: str
    allowed_aggregations: tuple[str, ...]
    stats_field: str
    coverage_from_field: str
    coverage_through_field: str


@dataclass(frozen=True, slots=True)
class AggregationDefinition:
    """Описание способа объединения дневных значений метрики."""

    code: str
    label: str


@dataclass(frozen=True, slots=True)
class ComparatorDefinition:
    """Описание допустимого сравнения агрегированного значения."""

    code: str
    symbol: str
    label: str


@dataclass(frozen=True, slots=True)
class ActionDefinition:
    """Описание действия модуля объявлений Avito."""

    code: str
    label: str
    description: str
    config_fields: tuple[str, ...] = ()


_metric_definitions = (
    MetricDefinition(
        code="views",
        label="Просмотры",
        description=(
            "Сумма просмотров объявления за выбранный период."
        ),
        value_type="integer",
        allowed_aggregations=("sum",),
        stats_field="views",
        coverage_from_field="coverage_from",
        coverage_through_field="finalized_through",
    ),
    MetricDefinition(
        code="contacts",
        label="Контакты",
        description=(
            "Сумма контактов по объявлению за выбранный период."
        ),
        value_type="integer",
        allowed_aggregations=("sum",),
        stats_field="contacts",
        coverage_from_field="coverage_from",
        coverage_through_field="finalized_through",
    ),
)

_aggregation_definitions = (
    AggregationDefinition(
        code="sum",
        label="Сумма",
    ),
)

_comparator_definitions = (
    ComparatorDefinition(
        code="lt",
        symbol="<",
        label="Меньше",
    ),
    ComparatorDefinition(
        code="lte",
        symbol="<=",
        label="Меньше или равно",
    ),
    ComparatorDefinition(
        code="eq",
        symbol="=",
        label="Равно",
    ),
    ComparatorDefinition(
        code="gte",
        symbol=">=",
        label="Больше или равно",
    ),
    ComparatorDefinition(
        code="gt",
        symbol=">",
        label="Больше",
    ),
)

_action_definitions = (
    ActionDefinition(
        code="pause",
        label="Приостановить",
        description=(
            "Временно скрыть объявление с возможностью восстановления."
        ),
    ),
    ActionDefinition(
        code="archive",
        label="Архивировать",
        description=(
            "Окончательно снять объявление в рамках автоматизации."
        ),
    ),
)


METRICS_BY_CODE: Mapping[str, MetricDefinition] = MappingProxyType({
    definition.code: definition
    for definition in _metric_definitions
})

AGGREGATIONS_BY_CODE: Mapping[
    str,
    AggregationDefinition,
] = MappingProxyType({
    definition.code: definition
    for definition in _aggregation_definitions
})

COMPARATORS_BY_CODE: Mapping[
    str,
    ComparatorDefinition,
] = MappingProxyType({
    definition.code: definition
    for definition in _comparator_definitions
})

ACTIONS_BY_CODE: Mapping[str, ActionDefinition] = MappingProxyType({
    definition.code: definition
    for definition in _action_definitions
})

CONDITION_LIMITS: Mapping[str, int] = MappingProxyType({
    "min_window_days": 1,
    "max_window_days": 365,
    "max_conditions": 50,
})


def build_catalog_payload() -> dict:
    """
    Возвращает безопасное JSON-представление каталога для будущего API.

    В payload не попадают Python-функции, пути импорта и внутренние
    сведения о структуре ORM-запросов.
    """

    return {
        "module_type": MODULE_TYPE,
        "label": "Объявления Avito",
        "metrics": [
            {
                "code": definition.code,
                "label": definition.label,
                "description": definition.description,
                "value_type": definition.value_type,
                "allowed_aggregations": list(
                    definition.allowed_aggregations,
                ),
            }
            for definition in METRICS_BY_CODE.values()
        ],
        "aggregations": [
            {
                "code": definition.code,
                "label": definition.label,
            }
            for definition in AGGREGATIONS_BY_CODE.values()
        ],
        "comparators": [
            {
                "code": definition.code,
                "symbol": definition.symbol,
                "label": definition.label,
            }
            for definition in COMPARATORS_BY_CODE.values()
        ],
        "actions": [
            {
                "code": definition.code,
                "label": definition.label,
                "description": definition.description,
                "config_schema": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            }
            for definition in ACTIONS_BY_CODE.values()
        ],
        "condition_limits": dict(CONDITION_LIMITS),
    }