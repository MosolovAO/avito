from datetime import date, datetime, timedelta

from django.db import transaction
from django.utils import timezone

from avitotask.models import AdCreative, AdPublication
from avitotask.services.ad_export_state import (
    mark_creative_publications_export_dirty,
    mark_publication_export_dirty,
)

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


def build_publication_default_date_end(publication):
    created_at = publication.created_at or timezone.now()
    created_date = normalize_datetime_to_local_date(created_at)

    return created_date + timedelta(days=PUBLICATION_EXTENSION_DAYS)


def get_publication_override_date_end(publication):
    return parse_avito_date((publication.overrides or {}).get(DATE_END_FIELD))


def get_creative_base_date_end(creative):
    return parse_avito_date((creative.base_data or {}).get(DATE_END_FIELD))


def get_publication_effective_date_end(publication):
    return (
            get_publication_override_date_end(publication)
            or get_creative_base_date_end(publication.creative)
            or build_publication_default_date_end(publication)
    )


def get_publication_date_end_source(publication):
    if get_publication_override_date_end(publication):
        return "publication"

    if get_creative_base_date_end(publication.creative):
        return "creative"

    return "default"


def get_creative_effective_date_end(creative):
    creative_date_end = get_creative_base_date_end(creative)
    if creative_date_end:
        return creative_date_end

    publication_dates = []

    publications = AdPublication.objects.filter(
        workspace=creative.workspace,
        creative=creative,
    ).only("id", "created_at", "overrides")

    for publication in publications:
        if get_publication_override_date_end(publication):
            continue

        publication_dates.append(build_publication_default_date_end(publication))

    if publication_dates:
        return max(publication_dates)

    return normalize_datetime_to_local_date(creative.created_at) + timedelta(
        days=PUBLICATION_EXTENSION_DAYS
    )


def extend_date_end(current_date_end, *, days=PUBLICATION_EXTENSION_DAYS):
    base_date = current_date_end or timezone.localdate()
    today = timezone.localdate()

    if base_date < today:
        base_date = today

    return base_date + timedelta(days=days)


def extend_ad_creative_publications(*, creative_id, workspace, days=PUBLICATION_EXTENSION_DAYS):
    with transaction.atomic():
        creative = AdCreative.objects.select_for_update().get(
            id=creative_id,
            workspace=workspace,
        )

        next_date_end = extend_date_end(
            get_creative_effective_date_end(creative),
            days=days,
        )

        base_data = dict(creative.base_data or {})
        base_data[DATE_END_FIELD] = format_avito_date(next_date_end)

        creative.base_data = base_data
        creative.save(update_fields=["base_data", "updated_at"])

        mark_creative_publications_export_dirty(creative=creative)

        return creative


def extend_ad_publication(*, publication_id, workspace, days=PUBLICATION_EXTENSION_DAYS):
    with transaction.atomic():
        publication = AdPublication.objects.select_for_update().select_related(
            "creative",
            "avito_account",
        ).get(
            id=publication_id,
            workspace=workspace,
        )

        next_date_end = extend_date_end(
            get_publication_effective_date_end(publication),
            days=days,
        )

        overrides = dict(publication.overrides or {})
        overrides[DATE_END_FIELD] = format_avito_date(next_date_end)

        publication.overrides = overrides
        publication.save(update_fields=["overrides", "updated_at"])

        mark_publication_export_dirty(publication)

        return publication


def inherit_creative_date_end_for_publication(*, publication_id, workspace):
    with transaction.atomic():
        publication = AdPublication.objects.select_for_update().select_related(
            "creative",
            "avito_account",
        ).get(
            id=publication_id,
            workspace=workspace,
        )

        overrides = dict(publication.overrides or {})

        if DATE_END_FIELD not in overrides:
            return publication

        overrides.pop(DATE_END_FIELD, None)

        publication.overrides = overrides
        publication.save(update_fields=["overrides", "updated_at"])

        mark_publication_export_dirty(publication)

        return publication
