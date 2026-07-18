from avitotask.models import (
    AdCreative,
    AdPublication,
    AvitoListing,
)
from avitotask.services.ad_generation import AdGenerationError, normalize_address

from django.db import transaction

from avitotask.services.ad_export_state import (
    mark_creative_publications_export_dirty,
    mark_publication_export_dirty,
)
from avitotask.services.ad_export_queue import queue_avito_account_csv_exports


class AdEditingError(AdGenerationError):
    """Ошибка редактирования объявления."""


def update_ad_publication(
        *,
        publication_id,
        workspace,
        overrides=None,
        address=None,
        status=None,
):
    """
    Редактирует только одну конкретную публикацию.

    Общий AdCreative не меняется, поэтому остальные адреса этого же объявления
    не затрагиваются.
    """

    publication = AdPublication.objects.select_related(
        'workspace',
        'creative',
        'avito_account',
    ).get(
        id=publication_id,
        workspace=workspace,
    )
    update_fields = []

    if overrides is not None:
        if not isinstance(overrides, dict):
            raise AdEditingError("Overrides должен быть словарем")
        current_overrides = dict(publication.overrides or {})
        current_overrides.update(overrides)

        publication.overrides = current_overrides
        update_fields.append("overrides")

    if address is not None:
        address_text, address_data = normalize_address(address)

        publication.address = address_text
        publication.address_data = address_data
        update_fields.extend(["address", "address_data"])

    if status is not None:
        if status not in AdPublication.Status.values:
            raise AdEditingError("Некорректный статус публикации.")

        publication.status = status
        update_fields.append("status")

    if not update_fields:
        raise AdEditingError("Нет данных для обновления публикации.")

    update_fields.append("updated_at")
    publication.save(update_fields=update_fields)

    mark_publication_export_dirty(publication)

    return publication


def update_ad_creative(
        *,
        creative_id,
        workspace,
        option_category=None,
        title=None,
        description=None,
        image_urls=None,
        base_data=None,
        option_data=None,
        clear_publication_override_fields=None,
        expected_updated_at=None,
):
    """
    Массово редактирует общий креатив объявления.

    Если поле очищается из overrides публикаций, то индивидуальные публикации
    снова начинают использовать новое общее значение из AdCreative.
    """

    with transaction.atomic():
        creative = AdCreative.objects.select_for_update().get(
            id=creative_id,
            workspace=workspace,
        )

        if (
                expected_updated_at is not None
                and creative.updated_at != expected_updated_at
        ):
            raise AdEditingError(
                "Креатив был изменен другим пользователем. Обновите страницу и повторите изменения."
            )

        update_fields = []

        option_category_changed = (
                option_category is not None
                and creative.option_category_id != option_category.id
        )

        if option_category is not None:
            creative.option_category = option_category
            update_fields.append("option_category")

        if title is not None:
            creative.title = title
            update_fields.append("title")

        if description is not None:
            creative.description = description
            update_fields.append("description")

        if image_urls is not None:
            if not isinstance(image_urls, list):
                raise AdEditingError("image_urls должен быть списком.")
            creative.image_urls = image_urls
            update_fields.append("image_urls")

        if base_data is not None:
            if not isinstance(base_data, dict):
                raise AdEditingError("base_data должен быть словарем.")
            current_base_data = dict(creative.base_data or {})
            current_base_data.update(base_data)

            creative.base_data = current_base_data
            update_fields.append("base_data")

        if option_data is not None:
            if not isinstance(option_data, dict):
                raise AdEditingError(
                    "option_data должен быть словарем."
                )

            if option_category_changed:
                # При смене категории полностью удаляем параметры старой
                # категории. Frontend присылает полный набор параметров,
                # разрешённых для новой категории.
                creative.option_data = dict(option_data)
            else:
                # При обычном редактировании сохраняем неизвестные legacy-поля.
                current_option_data = dict(creative.option_data or {})
                current_option_data.update(option_data)
                creative.option_data = current_option_data

            update_fields.append("option_data")

        if not update_fields:
            raise AdEditingError("Нет данных для обновления креатива.")

        update_fields.append("updated_at")
        creative.save(update_fields=update_fields)

        if option_category is not None:
            AvitoListing.objects.filter(
                source=AvitoListing.Source.SERVICE,
                publication__creative=creative,
            ).update(
                option_category=option_category,
            )

        if clear_publication_override_fields:
            clear_overrides_for_creative_publications(
                creative=creative,
                fields=clear_publication_override_fields,
            )

        mark_creative_publications_export_dirty(creative=creative)

        return creative


def clear_overrides_for_creative_publications(*, creative, fields):
    fields = set(fields)

    publications = AdPublication.objects.filter(
        workspace=creative.workspace,
        creative=creative,
    ).only("id", "overrides")

    publications_to_update = []

    for publication in publications:
        overrides = dict(publication.overrides or {})
        original_overrides = dict(overrides)

        for field in fields:
            overrides.pop(field, None)

        if overrides != original_overrides:
            publication.overrides = overrides
            publications_to_update.append(publication)

    if publications_to_update:
        AdPublication.objects.bulk_update(
            publications_to_update,
            ["overrides", "updated_at"]
        )


def delete_ad_creative(*, creative_id, workspace):
    with transaction.atomic():
        creative = AdCreative.objects.select_for_update().get(
            id=creative_id,
            workspace=workspace,
        )

        avito_account_ids = list(
            AdPublication.objects
            .filter(workspace=workspace, creative=creative)
            .values_list("avito_account_id", flat=True)
            .distinct()
        )

        creative.delete()
        queue_avito_account_csv_exports(avito_account_ids)
