from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from avitotask.models import (
    AdCreative,
    AdPublication,
    AvitoListing,
)
from avitotask.services.ad_generation import (
    AdGenerationError,
    normalize_address,
)
from avitotask.services.ad_publication_dates import (
    DATE_END_FIELD,
    PUBLICATION_EXTENSION_DAYS,
    get_creative_effective_date_end,
    parse_avito_date,
    set_legacy_date_end,
    sync_linked_listing_published_end,
    sync_linked_listings_published_end,
)
from avitotask.services.ad_export_state import (
    mark_creative_publications_export_dirty,
    mark_publication_export_dirty,
)
from avitotask.services.ad_export_queue import (
    queue_avito_account_csv_exports,
)


class AdEditingError(AdGenerationError):
    """Ошибка редактирования объявления."""


DATE_END_FIELDS = {DATE_END_FIELD, "date_end"}


def extract_date_end_patch(payload):
    if not isinstance(payload, dict):
        return False, None

    for field in (DATE_END_FIELD, "date_end"):
        if field not in payload:
            continue

        raw_value = payload.get(field)

        if raw_value is None or not str(raw_value).strip():
            return True, None

        published_end = parse_avito_date(raw_value)

        if published_end is None:
            raise AdEditingError(
                "DateEnd должен быть корректной календарной датой."
            )

        return True, published_end

    return False, None


def remove_legacy_date_end(payload):
    result = dict(payload or {})

    for field in DATE_END_FIELDS:
        result.pop(field, None)

    return result


def get_publication_source_from_creative(creative):
    if (
            creative.published_end_source
            == AdCreative.PublishedEndSource.DEFAULT
    ):
        return AdPublication.PublishedEndSource.DEFAULT

    return AdPublication.PublishedEndSource.CREATIVE


def sync_creative_date_to_publications(
        *,
        creative,
        include_individual,
):
    queryset = (
        AdPublication.objects
        .select_for_update()
        .filter(
            workspace=creative.workspace,
            creative=creative,
        )
    )

    if not include_individual:
        queryset = queryset.filter(
            published_end_source__in=[
                AdPublication.PublishedEndSource.DEFAULT,
                AdPublication.PublishedEndSource.CREATIVE,
            ],
        )

    publications = list(queryset)
    now = timezone.now()
    publication_source = get_publication_source_from_creative(creative)

    for publication in publications:
        publication.published_end = creative.published_end
        publication.published_end_source = publication_source
        publication.overrides = remove_legacy_date_end(
            publication.overrides,
        )
        publication.updated_at = now

    if publications:
        AdPublication.objects.bulk_update(
            publications,
            [
                "published_end",
                "published_end_source",
                "overrides",
                "updated_at",
            ],
        )
        sync_linked_listings_published_end(publications)


def update_ad_publication(
        *,
        publication_id,
        workspace,
        overrides=None,
        address=None,
        status=None,
):
    with transaction.atomic():
        publication = (
            AdPublication.objects
            .select_for_update()
            .select_related(
                "workspace",
                "creative",
                "avito_account",
            )
            .get(
                id=publication_id,
                workspace=workspace,
            )
        )
        update_fields = []
        published_end_changed = False

        if overrides is not None:
            if not isinstance(overrides, dict):
                raise AdEditingError("Overrides должен быть словарем")

            has_date_end, incoming_date_end = extract_date_end_patch(
                overrides,
            )

            current_overrides = dict(publication.overrides or {})
            current_overrides.update(overrides)
            current_overrides = remove_legacy_date_end(
                current_overrides,
            )

            if has_date_end:
                if incoming_date_end is None:
                    publication.published_end = (
                        get_creative_effective_date_end(
                            publication.creative,
                        )
                    )
                    publication.published_end_source = (
                        AdPublication.PublishedEndSource.CREATIVE
                    )
                else:
                    publication.published_end = incoming_date_end
                    publication.published_end_source = (
                        AdPublication.PublishedEndSource.PUBLICATION
                    )
                    current_overrides = set_legacy_date_end(
                        current_overrides,
                        incoming_date_end,
                    )

                update_fields.extend([
                    "published_end",
                    "published_end_source",
                ])
                published_end_changed = True

            publication.overrides = current_overrides
            update_fields.append("overrides")

        if address is not None:
            address_text, address_data = normalize_address(address)

            publication.address = address_text
            publication.address_data = address_data
            update_fields.extend(["address", "address_data"])

        if status is not None:
            if status not in AdPublication.Status.values:
                raise AdEditingError(
                    "Некорректный статус публикации."
                )

            publication.status = status
            update_fields.append("status")

        if not update_fields:
            raise AdEditingError(
                "Нет данных для обновления публикации."
            )

        update_fields.append("updated_at")
        publication.save(update_fields=list(dict.fromkeys(update_fields)))

        if published_end_changed:
            sync_linked_listing_published_end(publication)

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

        base_has_date_end, base_date_end = extract_date_end_patch(
            base_data,
        )
        option_has_date_end, option_date_end = extract_date_end_patch(
            option_data,
        )

        has_date_end = base_has_date_end or option_has_date_end
        incoming_date_end = (
            base_date_end
            if base_has_date_end
            else option_date_end
        )

        previous_published_end = creative.published_end
        previous_published_end_source = (
            creative.published_end_source
        )

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
                creative.option_data = dict(option_data)
            else:
                current_option_data = dict(
                    creative.option_data or {},
                )
                current_option_data.update(option_data)
                creative.option_data = current_option_data

            update_fields.append("option_data")

        if has_date_end:
            if incoming_date_end is None:
                creative.published_end = (
                        timezone.localdate()
                        + timedelta(days=PUBLICATION_EXTENSION_DAYS)
                )
                creative.published_end_source = (
                    AdCreative.PublishedEndSource.DEFAULT
                )
            else:
                creative.published_end = incoming_date_end

                if (
                        incoming_date_end != previous_published_end
                        or previous_published_end is None
                ):
                    creative.published_end_source = (
                        AdCreative.PublishedEndSource.CREATIVE
                    )

            creative.base_data = set_legacy_date_end(
                creative.base_data,
                creative.published_end,
            )
            creative.option_data = remove_legacy_date_end(
                creative.option_data,
            )

            update_fields.extend([
                "base_data",
                "option_data",
                "published_end",
                "published_end_source",
            ])

        published_end_changed = (
                creative.published_end != previous_published_end
                or creative.published_end_source
                != previous_published_end_source
        )

        if not update_fields:
            raise AdEditingError(
                "Нет данных для обновления креатива."
            )

        update_fields.append("updated_at")
        creative.save(
            update_fields=list(dict.fromkeys(update_fields)),
        )

        clear_fields = set(
            clear_publication_override_fields or [],
        )
        reset_individual_date_end = bool(
            clear_fields & DATE_END_FIELDS
        )
        regular_clear_fields = clear_fields - DATE_END_FIELDS

        if regular_clear_fields:
            clear_overrides_for_creative_publications(
                creative=creative,
                fields=regular_clear_fields,
            )

        if published_end_changed or reset_individual_date_end:
            sync_creative_date_to_publications(
                creative=creative,
                include_individual=reset_individual_date_end,
            )

        if option_category is not None:
            AvitoListing.objects.filter(
                source=AvitoListing.Source.SERVICE,
                publication__creative=creative,
            ).update(
                option_category=option_category,
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
    now = timezone.now()

    for publication in publications:
        overrides = dict(publication.overrides or {})
        original_overrides = dict(overrides)

        for field in fields:
            overrides.pop(field, None)

        if overrides != original_overrides:
            publication.overrides = overrides
            publication.updated_at = now
            publications_to_update.append(publication)

    if publications_to_update:
        AdPublication.objects.bulk_update(
            publications_to_update,
            ["overrides", "updated_at"],
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
