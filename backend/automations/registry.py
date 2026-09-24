from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from automations.modules.avito_listings import (
    error_policy as avito_error_policy,
)
from automations.modules.avito_listings import (
    run_lease as avito_run_lease,
)
from automations.modules.avito_listings import (
    catalog as avito_catalog,
)
from automations.modules.avito_listings import (
    run_evaluation as avito_run_evaluation,
)
from automations.modules.avito_listings import (
    run_readiness as avito_run_readiness,
)
from automations.modules.avito_listings import (
    validators as avito_validators,
)

CatalogBuilder = Callable[[], dict[str, Any]]
ConditionTreeValidator = Callable[[Any], Any]
ActionValidator = Callable[[Any, Any], Any]
RunDataReadinessGetter = Callable[..., Any]
RunEvaluator = Callable[..., Any]
RunEvaluationSaver = Callable[..., str]
RunLeaseAcquirer = Callable[..., bool]
RunLeaseHeartbeater = Callable[..., bool]
RunLeaseReleaser = Callable[..., bool]
RunErrorClassifier = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class AutomationModuleDefinition:
    """
    Явное описание зарегистрированного предметного модуля.

    Реестр содержит только реально реализованные capabilities. Новые
    обработчики добавляются в контракт одновременно с их реализацией.
    """

    module_type: str
    build_catalog_payload: CatalogBuilder
    validate_condition_tree: ConditionTreeValidator
    validate_action: ActionValidator
    get_run_data_readiness: RunDataReadinessGetter
    evaluate_run: RunEvaluator
    save_run_evaluation: RunEvaluationSaver
    acquire_run_lease: RunLeaseAcquirer
    heartbeat_run_lease: RunLeaseHeartbeater
    release_run_lease: RunLeaseReleaser
    classify_run_error: RunErrorClassifier


class UnknownAutomationModuleError(LookupError):
    """Запрошенный предметный модуль не зарегистрирован."""

    def __init__(self, module_type: Any):
        self.module_type = module_type
        super().__init__(
            f"Модуль автоматизации {module_type!r} не зарегистрирован.",
        )


_module_definitions = (
    AutomationModuleDefinition(
        module_type=avito_catalog.MODULE_TYPE,
        build_catalog_payload=avito_catalog.build_catalog_payload,
        validate_condition_tree=(
            avito_validators.validate_condition_tree
        ),
        validate_action=avito_validators.validate_action,
        get_run_data_readiness=(
            avito_run_readiness.get_run_data_readiness
        ),
        evaluate_run=avito_run_evaluation.evaluate_run,
        save_run_evaluation=(
            avito_run_evaluation.save_run_evaluation
        ),
        acquire_run_lease=avito_run_lease.acquire_run_lease,
        heartbeat_run_lease=(
            avito_run_lease.heartbeat_run_lease
        ),
        release_run_lease=avito_run_lease.release_run_lease,
        classify_run_error=avito_error_policy.classify_run_error,
    ),
)

MODULES_BY_TYPE: Mapping[
    str,
    AutomationModuleDefinition,
] = MappingProxyType({
    definition.module_type: definition
    for definition in _module_definitions
})


def get_module_definition(
        module_type: Any,
) -> AutomationModuleDefinition:
    """Возвращает только явно зарегистрированный предметный модуль."""

    if not isinstance(module_type, str):
        raise UnknownAutomationModuleError(module_type)

    definition = MODULES_BY_TYPE.get(module_type)
    if definition is None:
        raise UnknownAutomationModuleError(module_type)

    return definition


def build_modules_catalog_payload() -> list[dict[str, Any]]:
    """Возвращает безопасные каталоги зарегистрированных модулей."""

    return [
        definition.build_catalog_payload()
        for definition in MODULES_BY_TYPE.values()
    ]
