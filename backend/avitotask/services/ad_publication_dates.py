from datetime import date, datetime, timedelta

from django.db import transaction
from django.utils import timezone

from avitotask.services.ad_export_state import (
    mark_creative_publications_export_dirty,
    mark_publication_export_dirty,
)

from avitotask.models import AdCreative, AdPublication, AvitoListing

DATE_END_FIELD = "DateEnd"
PUBLICATION_EXTENSION_DAYS = 30


class AdPublicationDateError(ValueError):
    pass


def parse_avito_date(value):
    if not value:
        return None

    if isinstance(value, datetime):
        return normalize_datetime_to_local_date(value)

    if isinstance(value, date):
        return value

    raw_value = str(value).strip()
    if not raw_value:
        return None

    try:
        return normalize_datetime_to_local_date(
            datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        )
    except ValueError:
        pass

    for date_format in (
            "%d.%m.%Y",
            "%d.%m.%y",
            "%Y-%m-%d",
            "%d.%m.%Y %H:%M:%S",
            "%d.%m.%Y %H:%M",
            "%d.%m.%y %H:%M:%S",
            "%d.%m.%y %H:%M",
    ):
        try:
            parsed = datetime.strptime(raw_value, date_format)
        except ValueError:
            continue

        return normalize_datetime_to_local_date(parsed)

    return None


def normalize_datetime_to_local_date(value):
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_current_timezone())

    return timezone.localtime(value).date()


def format_avito_date(value):
    if value is None:
        return ""

    if isinstance(value, datetime):
        value = normalize_datetime_to_local_date(value)

    return value.isoformat()


def set_legacy_date_end(payload, published_end):
    result = dict(payload or {})

    if published_end is None:
        result.pop(DATE_END_FIELD, None)
        result.pop("date_end", None)
        return result

    result[DATE_END_FIELD] = format_avito_date(published_end)
    result.pop("date_end", None)

    return result


def resolve_initial_creative_published_end(*, base_data, option_data):
    explicit_end = (
            get_legacy_date_end(base_data)
            or get_legacy_date_end(option_data)
    )

    if explicit_end is not None:
        return explicit_end, AdCreative.PublishedEndSource.CREATIVE

    return (
        timezone.localdate() + timedelta(days=PUBLICATION_EXTENSION_DAYS),
        AdCreative.PublishedEndSource.DEFAULT,
    )


def get_legacy_date_end(payload):
    if not isinstance(payload, dict):
        return None

    return parse_avito_date(
        payload.get(DATE_END_FIELD)
        or payload.get("date_end")
    )


def build_publication_default_date_end(publication):
    created_at = publication.created_at or timezone.now()
    created_date = normalize_datetime_to_local_date(created_at)

    return created_date + timedelta(days=PUBLICATION_EXTENSION_DAYS)


def get_publication_override_date_end(publication):
    if publication.published_end is not None:
        if (
                publication.published_end_source
                == AdPublication.PublishedEndSource.PUBLICATION
        ):
            return publication.published_end

        return None

    return get_legacy_date_end(publication.overrides)


def get_creative_base_date_end(creative):
    if creative.published_end is not None:
        if (
                creative.published_end_source
                == AdCreative.PublishedEndSource.CREATIVE
        ):
            return creative.published_end

        return None

    return (
            get_legacy_date_end(creative.base_data)
            or get_legacy_date_end(creative.option_data)
    )


def get_publication_effective_date_end(publication):
    if publication.published_end is not None:
        return publication.published_end

    return (
            get_publication_override_date_end(publication)
            or get_creative_base_date_end(publication.creative)
            or build_publication_default_date_end(publication)
    )


def get_publication_date_end_source(publication):
    if publication.published_end is not None:
        return publication.published_end_source

    if get_publication_override_date_end(publication):
        return AdPublication.PublishedEndSource.PUBLICATION

    if get_creative_base_date_end(publication.creative):
        return AdPublication.PublishedEndSource.CREATIVE

    return AdPublication.PublishedEndSource.DEFAULT


def get_creative_effective_date_end(creative):
    if creative.published_end is not None:
        return creative.published_end

    creative_date_end = get_creative_base_date_end(creative)

    if creative_date_end:
        return creative_date_end

    publication_dates = []

    publications = AdPublication.objects.filter(
        workspace=creative.workspace,
        creative=creative,
    ).only(
        "id",
        "created_at",
        "overrides",
        "published_end",
        "published_end_source",
    )

    for publication in publications:
        if get_publication_override_date_end(publication):
            continue

        publication_dates.append(
            build_publication_default_date_end(publication)
        )

    if publication_dates:
        return max(publication_dates)

    return normalize_datetime_to_local_date(
        creative.created_at,
    ) + timedelta(days=PUBLICATION_EXTENSION_DAYS)


def extend_date_end(current_date_end, *, days=PUBLICATION_EXTENSION_DAYS):
    base_date = current_date_end or timezone.localdate()
    today = timezone.localdate()

    if base_date < today:
        base_date = today

    return base_date + timedelta(days=days)


def sync_linked_listing_published_end(publication):
    listing = (
        AvitoListing.objects
        .select_for_update()
        .filter(
            publication=publication,
            source=AvitoListing.Source.SERVICE,
        )
        .first()
    )

    if listing is None:
        return

    listing.published_end = publication.published_end
    listing.base_data = set_legacy_date_end(
        listing.base_data,
        publication.published_end,
    )
    listing.save(
        update_fields=[
            "published_end",
            "base_data",
            "updated_at",
        ]
    )


def sync_linked_listings_published_end(publications):
    published_end_by_id = {
        publication.id: publication.published_end
        for publication in publications
    }

    if not published_end_by_id:
        return

    listings = list(
        AvitoListing.objects
        .select_for_update()
        .filter(
            source=AvitoListing.Source.SERVICE,
            publication_id__in=published_end_by_id,
        )
    )

    now = timezone.now()

    for listing in listings:
        published_end = published_end_by_id[listing.publication_id]

        listing.published_end = published_end
        listing.base_data = set_legacy_date_end(
            listing.base_data,
            published_end,
        )
        listing.updated_at = now

    if listings:
        AvitoListing.objects.bulk_update(
            listings,
            ["published_end", "base_data", "updated_at"],
        )


def extend_ad_creative_publications(
        *,
        creative_id,
        workspace,
        days=PUBLICATION_EXTENSION_DAYS,
):
    with transaction.atomic():
        creative = AdCreative.objects.select_for_update().get(
            id=creative_id,
            workspace=workspace,
        )

        next_date_end = extend_date_end(
            get_creative_effective_date_end(creative),
            days=days,
        )

        creative.published_end = next_date_end
        creative.published_end_source = (
            AdCreative.PublishedEndSource.CREATIVE
        )
        creative.base_data = set_legacy_date_end(
            creative.base_data,
            next_date_end,
        )
        creative.save(
            update_fields=[
                "published_end",
                "published_end_source",
                "base_data",
                "updated_at",
            ]
        )

        publications = list(
            AdPublication.objects
            .select_for_update()
            .filter(
                workspace=workspace,
                creative=creative,
                published_end_source__in=[
                    AdPublication.PublishedEndSource.DEFAULT,
                    AdPublication.PublishedEndSource.CREATIVE,
                ],
            )
        )

        now = timezone.now()

        for publication in publications:
            overrides = dict(publication.overrides or {})
            overrides.pop(DATE_END_FIELD, None)
            overrides.pop("date_end", None)

            publication.published_end = next_date_end
            publication.published_end_source = (
                AdPublication.PublishedEndSource.CREATIVE
            )
            publication.overrides = overrides
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

        mark_creative_publications_export_dirty(creative=creative)

        return creative


def extend_ad_publication(
        *,
        publication_id,
        workspace,
        days=PUBLICATION_EXTENSION_DAYS,
):
    with transaction.atomic():
        publication = (
            AdPublication.objects
            .select_for_update()
            .select_related(
                "creative",
                "avito_account",
            )
            .get(
                id=publication_id,
                workspace=workspace,
            )
        )

        next_date_end = extend_date_end(
            get_publication_effective_date_end(publication),
            days=days,
        )

        publication.published_end = next_date_end
        publication.published_end_source = (
            AdPublication.PublishedEndSource.PUBLICATION
        )
        publication.overrides = set_legacy_date_end(
            publication.overrides,
            next_date_end,
        )
        publication.save(
            update_fields=[
                "published_end",
                "published_end_source",
                "overrides",
                "updated_at",
            ]
        )

        sync_linked_listing_published_end(publication)
        mark_publication_export_dirty(publication)

        return publication


def inherit_creative_date_end_for_publication(
        *,
        publication_id,
        workspace,
):
    with transaction.atomic():
        publication = (
            AdPublication.objects
            .select_for_update()
            .select_related(
                "creative",
                "avito_account",
            )
            .get(
                id=publication_id,
                workspace=workspace,
            )
        )

        creative_end = get_creative_effective_date_end(
            publication.creative,
        )

        overrides = dict(publication.overrides or {})
        overrides.pop(DATE_END_FIELD, None)
        overrides.pop("date_end", None)

        has_changes = (
                publication.published_end != creative_end
                or publication.published_end_source
                != AdPublication.PublishedEndSource.CREATIVE
                or publication.overrides != overrides
        )

        if not has_changes:
            return publication

        publication.published_end = creative_end
        publication.published_end_source = (
            AdPublication.PublishedEndSource.CREATIVE
        )
        publication.overrides = overrides
        publication.save(
            update_fields=[
                "published_end",
                "published_end_source",
                "overrides",
                "updated_at",
            ]
        )

        sync_linked_listing_published_end(publication)
        mark_publication_export_dirty(publication)

        return publication
