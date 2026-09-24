from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from django.db import OperationalError, transaction
from django.utils import timezone

from automations.models import (
    Automation,
    AutomationRun,
    AvitoListingAutomationConfig,
    AvitoListingDecision,
)

from automations.modules.avito_listings.decision_lifecycle import (
    DecisionTransitionError,
    is_lock_conflict,
    mark_decision_stale,
)

from automations.modules.avito_listings.catalog import MODULE_TYPE
from automations.modules.avito_listings.validators import (
    ActionValidationError,
    ConditionTreeValidationError,
)
from automations.registry import (
    UnknownAutomationModuleError,
    get_module_definition,
)
from avitotask.models import AvitoAccount

_UNSET = object()

ALLOWED_MVP_STATES = {
    Automation.State.DRAFT,
    Automation.State.ENABLED,
    Automation.State.DISABLED,
}

CONFIG_FIELDS = {
    "avito_account_id",
    "condition_tree",
    "action",
    "max_actions_per_run",
    "approval_ttl_minutes",
}

REQUIRED_CONFIG_FIELDS = {
    "avito_account_id",
    "condition_tree",
    "action",
}

ACTION_FIELDS = {
    "type",
    "config",
}

CANCELLABLE_RUN_STATUSES = {
    AutomationRun.Status.QUEUED,
    AutomationRun.Status.WAITING_FOR_DATA,
}

RUN_CANCELLATION_MESSAGES = {
    "automation_version_changed": (
        "Запуск отменён из-за изменения конфигурации автоматизации."
    ),
    "automation_not_enabled": (
        "Запуск отменён, потому что автоматизация выключена."
    ),
}


@dataclass(frozen=True, slots=True)
class _ValidatedConfig:
    """Проверенная конфигурация автоматизации объявлений Avito."""

    avito_account: AvitoAccount
    condition_tree: dict[str, Any]
    action_type: str
    action_config: dict[str, Any]
    max_actions_per_run: int
    approval_ttl_minutes: int


class AutomationManagementError(ValueError):
    """Безопасная доменная ошибка управления автоматизацией."""

    def __init__(self, *, code: str, message: str):
        self.code = code
        super().__init__(message)


def create_automation(
        *,
        workspace,
        actor,
        name,
        module_type,
        config,
) -> Automation:
    """Атомарно создаёт draft automation и типизированный config."""
    _validate_actor(actor)
    normalized_name = _normalize_name(name)
    module_definition = _get_supported_module(module_type)

    with transaction.atomic():
        validated_config = _validate_config(
            workspace=workspace,
            module_definition=module_definition,
            config=config,
        )

        automation = Automation.objects.create(
            workspace=workspace,
            module_type=module_type,
            name=normalized_name,
            state=Automation.State.DRAFT,
            execution_mode=Automation.ExecutionMode.MANUAL,
            version=1,
            created_by=actor,
            updated_by=actor,
        )
        AvitoListingAutomationConfig.objects.create(
            automation=automation,
            workspace=workspace,
            avito_account=validated_config.avito_account,
            condition_tree=deepcopy(
                validated_config.condition_tree,
            ),
            action_type=validated_config.action_type,
            action_config=deepcopy(
                validated_config.action_config,
            ),
            max_actions_per_run=(
                validated_config.max_actions_per_run
            ),
            approval_ttl_minutes=(
                validated_config.approval_ttl_minutes
            ),
        )

    return automation


def update_automation(
        *,
        workspace,
        actor,
        automation_id: int,
        name=_UNSET,
        state=_UNSET,
        config=_UNSET,
) -> Automation:
    """
    Атомарно меняет общие поля и типизированную конфигурацию.

    Версия увеличивается только при изменении полей, влияющих на
    вычисление или действие автоматизации.
    """
    _validate_actor(actor)

    with transaction.atomic():
        automation = _get_locked_automation(
            workspace=workspace,
            automation_id=automation_id,
        )

        if automation.state == Automation.State.ARCHIVED:
            raise AutomationManagementError(
                code="automation_archived",
                message="Архивированную автоматизацию нельзя изменить.",
            )

        normalized_name = (
            _normalize_name(name)
            if name is not _UNSET
            else automation.name
        )
        normalized_state = (
            _validate_state(state)
            if state is not _UNSET
            else automation.state
        )

        current_config = None
        validated_config = None
        config_changed = False

        if (
                config is not _UNSET
                or normalized_state == Automation.State.ENABLED
        ):
            current_config = _get_locked_config(
                automation=automation,
                workspace=workspace,
            )

        if config is not _UNSET:
            module_definition = _get_supported_module(
                automation.module_type,
            )
            validated_config = _validate_config(
                workspace=workspace,
                module_definition=module_definition,
                config=config,
            )

            if (
                    validated_config.avito_account.id
                    != current_config.avito_account_id
                    and AutomationRun.objects.filter(
                automation=automation,
            ).exists()
            ):
                raise AutomationManagementError(
                    code="avito_account_immutable",
                    message=(
                        "После первого запуска Avito-аккаунт "
                        "автоматизации изменить нельзя."
                    ),
                )

            config_changed = _config_has_changed(
                current=current_config,
                validated=validated_config,
            )

        elif normalized_state == Automation.State.ENABLED:
            module_definition = _get_supported_module(
                automation.module_type,
            )
            _validate_config(
                workspace=workspace,
                module_definition=module_definition,
                config=_build_config_payload(current_config),
            )

        enables_changed_config = (
                config_changed
                and state is not _UNSET
                and normalized_state == Automation.State.ENABLED
        )

        if (
                config_changed
                and automation.state == Automation.State.ENABLED
                and state is _UNSET
        ):
            normalized_state = Automation.State.DISABLED

        is_enabling = (
                automation.state != Automation.State.ENABLED
                and normalized_state == Automation.State.ENABLED
        )

        if (
                enables_changed_config
                or (
                is_enabling
                and not _has_completed_current_preview(
            automation=automation,
        )
        )
        ):
            raise AutomationManagementError(
                code="preview_required",
                message=(
                    "Перед включением завершите preview "
                    "текущей версии автоматизации."
                ),
            )

        automation_fields = []

        if automation.name != normalized_name:
            automation.name = normalized_name
            automation_fields.append("name")

        state_changed = automation.state != normalized_state
        if state_changed:
            automation.state = normalized_state
            automation_fields.append("state")

        if config_changed:
            automation.version += 1
            automation_fields.append("version")
            _apply_validated_config(
                current=current_config,
                validated=validated_config,
            )

        if automation_fields:
            automation.updated_by = actor
            automation_fields.extend([
                "updated_by",
                "updated_at",
            ])
            automation.save(update_fields=automation_fields)

        close_reason = None

        if config_changed:
            close_reason = "automation_version_changed"
        elif (
                state_changed
                and normalized_state != Automation.State.ENABLED
        ):
            close_reason = "automation_not_enabled"

        if close_reason is not None:
            _close_obsolete_work(
                automation=automation,
                transition_at=timezone.now(),
                reason=close_reason,
            )

    return automation


def archive_automation(
        *,
        workspace,
        actor,
        automation_id: int,
        archived_at=None,
) -> Automation:
    """Выполняет идемпотентную мягкую архивацию automation."""
    _validate_actor(actor)
    transition_at = archived_at or timezone.now()

    if timezone.is_naive(transition_at):
        raise AutomationManagementError(
            code="invalid_archive_time",
            message="Время архивации должно содержать часовой пояс.",
        )

    with transaction.atomic():
        automation = _get_locked_automation(
            workspace=workspace,
            automation_id=automation_id,
        )

        if automation.state == Automation.State.ARCHIVED:
            return automation

        automation.state = Automation.State.ARCHIVED
        automation.archived_at = transition_at
        automation.updated_by = actor
        automation.save(
            update_fields=[
                "state",
                "archived_at",
                "updated_by",
                "updated_at",
            ],
        )

        _close_obsolete_work(
            automation=automation,
            transition_at=transition_at,
            reason="automation_not_enabled",
        )

    return automation


def _close_obsolete_work(
        *,
        automation: Automation,
        transition_at,
        reason: str,
) -> None:
    """
    Закрывает ещё не начатую работу и старые ожидающие решения.

    Evaluating и effect_pending не прерываются: первый работает по snapshot,
    второй уже применил lifecycle-действие и ожидает только CSV-эффект.
    """
    pending_decisions = (
        AvitoListingDecision.objects
        .filter(
            automation=automation,
            status=AvitoListingDecision.Status.PENDING_APPROVAL,
        )
    )
    if reason == "automation_version_changed":
        pending_decisions = pending_decisions.filter(
            automation_version__lt=automation.version,
        )

    decision_refs = list(
        pending_decisions
        .order_by("id")
        .values_list(
            "workspace_id",
            "run_id",
            "id",
        )
    )

    for workspace_id, run_id, decision_id in decision_refs:
        try:
            mark_decision_stale(
                workspace_id=workspace_id,
                run_id=run_id,
                decision_id=decision_id,
                stale_at=transition_at,
                reason=reason,
            )
        except DecisionTransitionError as error:
            if error.code == "resource_busy":
                raise AutomationManagementError(
                    code="resource_busy",
                    message=(
                        "Автоматизация сейчас обрабатывается. "
                        "Повторите изменение позже."
                    ),
                ) from error

            raise AutomationManagementError(
                code="state_transition_failed",
                message=(
                    "Не удалось закрыть устаревшее решение "
                    "автоматизации."
                ),
            ) from error

    cancellable_runs = AutomationRun.objects.filter(
        automation=automation,
        status__in=CANCELLABLE_RUN_STATUSES,
    )
    if reason == "automation_version_changed":
        cancellable_runs = cancellable_runs.filter(
            automation_version__lt=automation.version,
        )

    try:
        locked_runs = list(
            cancellable_runs
            .select_for_update(
                nowait=True,
                of=("self",),
            )
            .only("id")
            .order_by("id")
        )
    except OperationalError as error:
        if not is_lock_conflict(error):
            raise

        raise AutomationManagementError(
            code="resource_busy",
            message=(
                "Запуск автоматизации сейчас обрабатывается. "
                "Повторите изменение позже."
            ),
        ) from error

    run_ids = [run.id for run in locked_runs]
    if not run_ids:
        return

    AutomationRun.objects.filter(id__in=run_ids).update(
        status=AutomationRun.Status.CANCELLED,
        finished_at=transition_at,
        next_attempt_at=None,
        wait_started_at=None,
        run_token=None,
        heartbeat_at=None,
        error_code=reason,
        error_message=RUN_CANCELLATION_MESSAGES[reason],
        updated_at=transition_at,
    )


def _get_locked_automation(
        *,
        workspace,
        automation_id: int,
) -> Automation:
    automation = (
        Automation.objects
        .select_for_update(
            of=("self",),
        )
        .filter(
            id=automation_id,
            workspace=workspace,
        )
        .first()
    )
    if automation is None:
        raise AutomationManagementError(
            code="automation_not_found",
            message="Автоматизация не найдена в текущем workspace.",
        )

    return automation


def _get_locked_config(
        *,
        automation: Automation,
        workspace,
) -> AvitoListingAutomationConfig:
    config = (
        AvitoListingAutomationConfig.objects
        .select_for_update(
            of=("self",),
        )
        .filter(
            automation=automation,
            workspace=workspace,
        )
        .first()
    )
    if config is None:
        raise AutomationManagementError(
            code="invalid_configuration",
            message="У автоматизации отсутствует типизированный config.",
        )

    return config


def _get_supported_module(module_type):
    try:
        module_definition = get_module_definition(module_type)
    except UnknownAutomationModuleError as error:
        raise AutomationManagementError(
            code="unsupported_module",
            message="Предметный модуль автоматизации не поддерживается.",
        ) from error

    if module_type != MODULE_TYPE:
        raise AutomationManagementError(
            code="unsupported_module",
            message="Предметный модуль автоматизации не поддерживается.",
        )

    return module_definition


def _validate_config(
        *,
        workspace,
        module_definition,
        config,
) -> _ValidatedConfig:
    if not isinstance(config, Mapping):
        raise AutomationManagementError(
            code="invalid_configuration",
            message="Конфигурация должна быть объектом.",
        )

    unknown_fields = set(config) - CONFIG_FIELDS
    missing_fields = REQUIRED_CONFIG_FIELDS - set(config)
    if unknown_fields or missing_fields:
        raise AutomationManagementError(
            code="invalid_configuration",
            message=(
                "Конфигурация содержит неизвестные поля "
                "или не содержит обязательные."
            ),
        )

    avito_account_id = config["avito_account_id"]
    if (
            isinstance(avito_account_id, bool)
            or not isinstance(avito_account_id, int)
            or avito_account_id < 1
    ):
        raise AutomationManagementError(
            code="avito_account_not_found",
            message="Avito-аккаунт не найден в текущем workspace.",
        )

    avito_account = (
        AvitoAccount.objects
        .filter(
            id=avito_account_id,
            workspace=workspace,
        )
        .first()
    )
    if avito_account is None:
        raise AutomationManagementError(
            code="avito_account_not_found",
            message="Avito-аккаунт не найден в текущем workspace.",
        )

    condition_tree = config["condition_tree"]
    try:
        module_definition.validate_condition_tree(condition_tree)
    except ConditionTreeValidationError as error:
        raise AutomationManagementError(
            code="invalid_condition_tree",
            message=str(error),
        ) from error

    action = config["action"]
    if (
            not isinstance(action, Mapping)
            or set(action) != ACTION_FIELDS
    ):
        raise AutomationManagementError(
            code="invalid_action",
            message=(
                "Действие должно содержать только поля type и config."
            ),
        )

    action_type = action["type"]
    action_config = action["config"]
    try:
        module_definition.validate_action(
            action_type,
            action_config,
        )
    except ActionValidationError as error:
        raise AutomationManagementError(
            code="invalid_action",
            message=str(error),
        ) from error

    max_actions_per_run = config.get(
        "max_actions_per_run",
        10,
    )
    if (
            isinstance(max_actions_per_run, bool)
            or not isinstance(max_actions_per_run, int)
            or max_actions_per_run < 1
            or max_actions_per_run > 100
    ):
        raise AutomationManagementError(
            code="invalid_run_limit",
            message="Лимит действий должен находиться в диапазоне 1–100.",
        )

    approval_ttl_minutes = config.get(
        "approval_ttl_minutes",
        1440,
    )
    if (
            isinstance(approval_ttl_minutes, bool)
            or not isinstance(approval_ttl_minutes, int)
            or approval_ttl_minutes < 60
            or approval_ttl_minutes > 10080
    ):
        raise AutomationManagementError(
            code="invalid_approval_ttl",
            message=(
                "TTL подтверждения должен находиться "
                "в диапазоне 60–10080 минут."
            ),
        )

    return _ValidatedConfig(
        avito_account=avito_account,
        condition_tree=deepcopy(condition_tree),
        action_type=action_type,
        action_config=deepcopy(action_config),
        max_actions_per_run=max_actions_per_run,
        approval_ttl_minutes=approval_ttl_minutes,
    )


def _normalize_name(name) -> str:
    if not isinstance(name, str):
        raise AutomationManagementError(
            code="invalid_name",
            message="Название автоматизации должно быть строкой.",
        )

    normalized_name = name.strip()
    if not normalized_name or len(normalized_name) > 255:
        raise AutomationManagementError(
            code="invalid_name",
            message=(
                "Название автоматизации должно содержать "
                "от 1 до 255 символов."
            ),
        )

    return normalized_name


def _has_completed_current_preview(
        *,
        automation: Automation,
) -> bool:
    """Проверяет успешный preview текущей версии правила."""

    return AutomationRun.objects.filter(
        automation=automation,
        run_kind=AutomationRun.RunKind.PREVIEW,
        status=AutomationRun.Status.COMPLETED,
        automation_version=automation.version,
        avito_listing_result__isnull=False,
    ).exists()


def _validate_state(state) -> str:
    if state not in ALLOWED_MVP_STATES:
        raise AutomationManagementError(
            code="invalid_state_transition",
            message=(
                "В MVP доступны состояния draft, enabled и disabled. "
                "Для архивации используется отдельная операция."
            ),
        )

    return state


def _validate_actor(actor) -> None:
    if actor is None:
        raise AutomationManagementError(
            code="invalid_actor",
            message="Для изменения автоматизации необходим пользователь.",
        )


def _config_has_changed(
        *,
        current: AvitoListingAutomationConfig,
        validated: _ValidatedConfig,
) -> bool:
    return any((
        current.avito_account_id != validated.avito_account.id,
        current.condition_tree != validated.condition_tree,
        current.action_type != validated.action_type,
        current.action_config != validated.action_config,
        (
                current.max_actions_per_run
                != validated.max_actions_per_run
        ),
        (
                current.approval_ttl_minutes
                != validated.approval_ttl_minutes
        ),
    ))


def _apply_validated_config(
        *,
        current: AvitoListingAutomationConfig,
        validated: _ValidatedConfig,
) -> None:
    current.avito_account = validated.avito_account
    current.condition_tree = deepcopy(validated.condition_tree)
    current.action_type = validated.action_type
    current.action_config = deepcopy(validated.action_config)
    current.max_actions_per_run = validated.max_actions_per_run
    current.approval_ttl_minutes = validated.approval_ttl_minutes
    current.save(
        update_fields=[
            "avito_account",
            "condition_tree",
            "action_type",
            "action_config",
            "max_actions_per_run",
            "approval_ttl_minutes",
            "updated_at",
        ],
    )


def _build_config_payload(
        config: AvitoListingAutomationConfig,
) -> dict[str, Any]:
    return {
        "avito_account_id": config.avito_account_id,
        "condition_tree": deepcopy(config.condition_tree),
        "action": {
            "type": config.action_type,
            "config": deepcopy(config.action_config),
        },
        "max_actions_per_run": config.max_actions_per_run,
        "approval_ttl_minutes": config.approval_ttl_minutes,
    }
