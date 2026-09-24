from dataclasses import dataclass
from django.db import transaction

from accounts.models import Workspace
from avitotask.models import AvitoAccount, AvitoListing
from avitotask.services.ad_editing import AdEditingError
from avitotask.services.ad_lifecycle import (
    ACTION_DELETE,
    ACTION_PAUSE,
    ENTITY_TYPE_AVITO_LISTING,
    bulk_update_ads_lifecycle,
)

LIFECYCLE_ACTION_BY_AUTOMATION_ACTION = {
    "pause": ACTION_PAUSE,
    # В avitotask архивирование исторически называется delete.
    "archive": ACTION_DELETE,
}

ACTIONABLE_LISTING_SOURCES = {
    AvitoListing.Source.SERVICE,
    AvitoListing.Source.AVITO_EXCEL,
}


@dataclass(frozen=True, slots=True)
class AvitoListingActionResult:
    """Результат успешно применённого локального lifecycle-действия."""

    listing_id: int
    action_type: str
    updated: bool
    required_export_revision: int


class AvitoListingActionError(RuntimeError):
    """Безопасная предметная ошибка применения действия к объявлению."""

    def __init__(self, *, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def apply_listing_action(
        *,
        workspace: Workspace,
        avito_account: AvitoAccount,
        listing: AvitoListing,
        action_type: str,
) -> AvitoListingActionResult:
    """
    Применяет pause/archive через существующий lifecycle-сервис avitotask.

    Успешное выполнение подтверждает только изменение локального состояния
    объявления и постановку CSV на пересборку. Оно не доказывает, что Avito
    уже снял объявление с публикации.

    Перед production необходимо отдельно проверить на тестовом аккаунте,
    достаточно ли исключения объявления из CSV для pause/archive. Если Avito
    требует другой команды или состояния строки фида, этот контракт нужно
    изменить по отдельному ТЗ.
    """

    lifecycle_action = LIFECYCLE_ACTION_BY_AUTOMATION_ACTION.get(
        action_type,
    )
    if lifecycle_action is None:
        raise AvitoListingActionError(
            code="unsupported_action",
            message="Действие не поддерживается для объявлений Avito.",
        )

    if (
            avito_account.workspace_id != workspace.id
            or listing.workspace_id != workspace.id
            or listing.avito_account_id != avito_account.id
    ):
        raise AvitoListingActionError(
            code="listing_scope_mismatch",
            message="Объявление недоступно в выбранном workspace и аккаунте.",
        )

    if (
            listing.management_status
            != AvitoListing.ManagementStatus.MANAGED
            or listing.source not in ACTIONABLE_LISTING_SOURCES
            or (
            listing.source == AvitoListing.Source.SERVICE
            and listing.publication_id is None
    )
    ):
        raise AvitoListingActionError(
            code="listing_not_actionable",
            message="Объявление не поддерживает это действие.",
        )

    try:
        with transaction.atomic():
            lifecycle_result = bulk_update_ads_lifecycle(
                workspace=workspace,
                avito_account=avito_account,
                items=[
                    {
                        "entity_type": ENTITY_TYPE_AVITO_LISTING,
                        "id": listing.id,
                    },
                ],
                action=lifecycle_action,
            )

            if lifecycle_result["updated"] != 1:
                raise AvitoListingActionError(
                    code="listing_not_actionable",
                    message="Объявление не было изменено.",
                )

            required_export_revision = lifecycle_result.get(
                "required_export_revision",
            )
            if (
                    not isinstance(required_export_revision, int)
                    or required_export_revision < 1
            ):
                raise AvitoListingActionError(
                    code="invalid_export_revision",
                    message=(
                        "Изменение объявления не создало корректную "
                        "ревизию экспорта."
                    ),
                )
    except AdEditingError as error:
        raise AvitoListingActionError(
            code="lifecycle_rejected",
            message="Не удалось изменить состояние объявления.",
        ) from error

    return AvitoListingActionResult(
        listing_id=listing.id,
        action_type=action_type,
        updated=True,
        required_export_revision=required_export_revision,
    )
