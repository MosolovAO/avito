from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone

from automations.models import (
    Automation,
    AutomationRun,
    AvitoListingAutomationConfig,
    AvitoListingRunResult,
)
from automations.modules.avito_listings.catalog import MODULE_TYPE
from automations.modules.avito_listings.validators import (
    ActionValidationError,
    ConditionTreeValidationError,
)
from automations.registry import get_module_definition

MIN_IDEMPOTENCY_KEY_LENGTH = 1
MAX_IDEMPOTENCY_KEY_LENGTH = 128

OPEN_RUN_STATUSES = (
    AutomationRun.Status.QUEUED,
    AutomationRun.Status.WAITING_FOR_DATA,
    AutomationRun.Status.EVALUATING,
    AutomationRun.Status.WAITING_APPROVAL,
    AutomationRun.Status.EFFECT_PENDING,
)

PREVIEW_ALLOWED_AUTOMATION_STATES = (
    Automation.State.DRAFT,
    Automation.State.DISABLED,
    Automation.State.ENABLED,
)


@dataclass(frozen=True, slots=True)
class RunCreation:
    """Результат идемпотентного создания automation run."""

    run: AutomationRun
    created: bool


class RunCreationError(ValueError):
    """Контролируемая ошибка создания automation run."""

    def __init__(
            self,
            *,
            code: str,
            message: str,
            open_run_id: int | None = None,
    ):
        self.code = code
        self.open_run_id = open_run_id
        super().__init__(message)


def create_or_get_preview_run(
        *,
        workspace,
        automation_id: int,
        created_by,
        idempotency_key: Any,
) -> RunCreation:
    """Создаёт или возвращает существующий preview run."""

    return _create_or_get_run(
        workspace=workspace,
        automation_id=automation_id,
        created_by=created_by,
        idempotency_key=idempotency_key,
        run_kind=AutomationRun.RunKind.PREVIEW,
    )


def create_or_get_manual_run(
        *,
        workspace,
        automation_id: int,
        created_by,
        idempotency_key: Any,
) -> RunCreation:
    """Создаёт или возвращает существующий ручной execute run."""

    return _create_or_get_run(
        workspace=workspace,
        automation_id=automation_id,
        created_by=created_by,
        idempotency_key=idempotency_key,
        run_kind=AutomationRun.RunKind.EXECUTE,
    )


def _create_or_get_run(
        *,
        workspace,
        automation_id: int,
        created_by,
        idempotency_key: Any,
        run_kind: str,
) -> RunCreation:
    """
    Атомарно создаёт run и типизированный результат.

    Повторный запрос с тем же нормализованным idempotency key возвращает
    исходный run без повторной проверки automation и изменения snapshots.
    """

    normalized_key = _normalize_idempotency_key(idempotency_key)

    with transaction.atomic():
        automation = (
            Automation.objects
            .select_for_update()
            .filter(
                id=automation_id,
                workspace=workspace,
            )
            .first()
        )
        if automation is None:
            raise RunCreationError(
                code="automation_not_found",
                message=(
                    "Автоматизация не найдена в текущем workspace."
                ),
            )

        existing_run = (
            AutomationRun.objects
            .filter(
                automation=automation,
                run_kind=run_kind,
                idempotency_key=normalized_key,
            )
            .first()
        )
        if existing_run is not None:
            _dispatch_queued_run_after_commit(existing_run)

            return RunCreation(
                run=existing_run,
                created=False,
            )

        _validate_automation(
            automation,
            run_kind=run_kind,
        )

        open_run = (
            AutomationRun.objects
            .filter(
                automation=automation,
                run_kind=run_kind,
                status__in=OPEN_RUN_STATUSES,
            )
            .only("id")
            .first()
        )
        if open_run is not None:
            raise RunCreationError(
                code=f"open_{run_kind}_conflict",
                message=(
                    "Для автоматизации уже существует "
                    f"незавершённый {run_kind} run."
                ),
                open_run_id=open_run.id,
            )

        config = _get_validated_config(
            automation=automation,
            workspace=workspace,
        )

        condition_snapshot = deepcopy(config.condition_tree)
        action_snapshot = {
            "type": config.action_type,
            "config": deepcopy(config.action_config),
        }

        run = AutomationRun.objects.create(
            automation=automation,
            workspace=workspace,
            run_kind=run_kind,
            trigger=AutomationRun.Trigger.MANUAL,
            execution_mode_snapshot=automation.execution_mode,
            automation_version=automation.version,
            automation_name_snapshot=automation.name,
            module_type_snapshot=automation.module_type,
            status=AutomationRun.Status.QUEUED,
            idempotency_key=normalized_key,
            created_by=created_by,
        )

        AvitoListingRunResult.objects.create(
            run=run,
            workspace=workspace,
            avito_account=config.avito_account,
            as_of_date=timezone.localdate(),
            max_actions_per_run_snapshot=(
                config.max_actions_per_run
            ),
            approval_ttl_minutes_snapshot=(
                config.approval_ttl_minutes
            ),
            condition_snapshot=condition_snapshot,
            action_snapshot=action_snapshot,
        )

        _dispatch_queued_run_after_commit(run)

    return RunCreation(
        run=run,
        created=True,
    )


def _dispatch_queued_run_after_commit(
        run: AutomationRun,
) -> None:
    """
    Ставит queued run в Celery только после commit транзакции.

    Локальный импорт не создаёт циклическую зависимость между сервисом
    создания preview и Celery entrypoint.
    """

    if run.status != AutomationRun.Status.QUEUED:
        return

    run_id = run.id

    def dispatch() -> None:
        from automations.tasks import evaluate_automation_run_task

        evaluate_automation_run_task.delay(run_id)

    transaction.on_commit(dispatch)


def _normalize_idempotency_key(value: Any) -> str:
    if not isinstance(value, str):
        raise RunCreationError(
            code="invalid_idempotency_key",
            message=(
                "Idempotency key должен быть непустой строкой."
            ),
        )

    normalized_key = value.strip()

    if (
            len(normalized_key) < MIN_IDEMPOTENCY_KEY_LENGTH
            or len(normalized_key) > MAX_IDEMPOTENCY_KEY_LENGTH
    ):
        raise RunCreationError(
            code="invalid_idempotency_key",
            message=(
                "Idempotency key должен содержать "
                f"от {MIN_IDEMPOTENCY_KEY_LENGTH} "
                f"до {MAX_IDEMPOTENCY_KEY_LENGTH} символов."
            ),
        )

    return normalized_key


def _validate_automation(
        automation: Automation,
        *,
        run_kind: str,
) -> None:
    if (
            run_kind == AutomationRun.RunKind.PREVIEW
            and automation.state not in PREVIEW_ALLOWED_AUTOMATION_STATES
    ):
        raise RunCreationError(
            code="invalid_automation_state",
            message=(
                "Preview доступен только для draft, "
                "disabled или enabled automation."
            ),
        )

    if (
            run_kind == AutomationRun.RunKind.EXECUTE
            and automation.state != Automation.State.ENABLED
    ):
        raise RunCreationError(
            code="invalid_automation_state",
            message=(
                "Ручной запуск доступен только для "
                "enabled automation."
            ),
        )

    if automation.module_type != MODULE_TYPE:
        raise RunCreationError(
            code="unsupported_module",
            message=(
                "Модуль автоматизации не поддерживает запуск."
            ),
        )


def _get_validated_config(
        *,
        automation: Automation,
        workspace,
) -> AvitoListingAutomationConfig:
    config = (
        AvitoListingAutomationConfig.objects
        .select_related("avito_account")
        .filter(automation=automation)
        .first()
    )
    if config is None:
        raise RunCreationError(
            code="invalid_configuration",
            message=(
                "У автоматизации отсутствует конфигурация "
                "модуля объявлений Avito."
            ),
        )

    if (
            config.workspace_id != workspace.id
            or config.avito_account.workspace_id != workspace.id
    ):
        raise RunCreationError(
            code="invalid_configuration",
            message=(
                "Workspace автоматизации, конфигурации "
                "и Avito-аккаунта должен совпадать."
            ),
        )

    module_definition = get_module_definition(
        automation.module_type,
    )

    try:
        module_definition.validate_condition_tree(
            config.condition_tree,
        )
        module_definition.validate_action(
            config.action_type,
            config.action_config,
        )
    except (
            ConditionTreeValidationError,
            ActionValidationError,
    ) as exc:
        raise RunCreationError(
            code="invalid_configuration",
            message=(
                "Сохранённая конфигурация автоматизации "
                "не прошла валидацию."
            ),
        ) from exc

    return config
