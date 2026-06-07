from avitotask.models import AvitoListing
from avitotask.services.ad_editing import AdEditingError
from avitotask.services.ad_export_state import mark_avito_accounts_export_dirty
from django.utils import timezone

from avitotask.services.ad_publication_dates import (
    DATE_END_FIELD,
    extend_date_end,
    format_avito_date,
    parse_avito_date,
)


def update_avito_listing(
        *,
        listing_id,
        workspace,
        title=None,
        description=None,
        address=None,
        status=None,
        image_urls=None,
        base_data=None,
        option_data=None,
        management_status=None,
        desired_status=None,
):
    listing = AvitoListing.objects.select_related("avito_account").get(
        id=listing_id,
        workspace=workspace,
    )

    if listing.source != AvitoListing.Source.AVITO_EXCEL:
        raise AdEditingError("Редактировать напрямую можно только объявления, импортированные из XLSX Avito.")

    if listing.management_status not in [
        AvitoListing.ManagementStatus.MANAGED,
        AvitoListing.ManagementStatus.OUT_OF_SYNC,
    ]:
        raise AdEditingError("Это объявление не находится под управлением сервиса.")

    update_fields = []

    if title is not None:
        listing.title = title
        update_fields.append("title")

    if description is not None:
        listing.description = description
        update_fields.append("description")

    if address is not None:
        listing.address = address
        update_fields.append("address")

    if status is not None:
        listing.status = status
        update_fields.append("status")

    if image_urls is not None:
        if not isinstance(image_urls, list):
            raise AdEditingError("image_urls должен быть списком.")
        listing.image_urls = image_urls
        update_fields.append("image_urls")

    if base_data is not None:
        if not isinstance(base_data, dict):
            raise AdEditingError("base_data должен быть словарем.")
        current_base_data = dict(listing.base_data or {})
        current_base_data.update(base_data)
        listing.base_data = current_base_data
        update_fields.append("base_data")

    if option_data is not None:
        if not isinstance(option_data, dict):
            raise AdEditingError("option_data должен быть словарем.")
        current_option_data = dict(listing.option_data or {})
        current_option_data.update(option_data)
        listing.option_data = current_option_data
        update_fields.append("option_data")

    if management_status is not None:
        if management_status not in AvitoListing.ManagementStatus.values:
            raise AdEditingError("Некорректный статус управления объявлением.")
        listing.management_status = management_status
        update_fields.append("management_status")

    if desired_status is not None:
        if desired_status not in AvitoListing.DesiredStatus.values:
            raise AdEditingError("Некорректное желаемое состояние объявления.")
        listing.desired_status = desired_status
        update_fields.append("desired_status")

    if not update_fields:
        raise AdEditingError("Нет данных для обновления объявления.")

    update_fields.append("updated_at")
    listing.save(update_fields=update_fields)

    mark_avito_accounts_export_dirty([listing.avito_account_id])

    return listing


def get_avito_listing_date_end(listing):
    return parse_avito_date(
        (listing.base_data or {}).get(DATE_END_FIELD)
        or (listing.raw_data or {}).get("AvitoDateEnd")
    )


def get_avito_listing_date_end_source(listing):
    return "avito" if get_avito_listing_date_end(listing) else "none"


def extend_avito_listing_date_end(*, listing_id, workspace):
    listing = AvitoListing.objects.select_related("avito_account").get(
        id=listing_id,
        workspace=workspace,
    )

    if listing.source != AvitoListing.Source.AVITO_EXCEL:
        raise AdEditingError("Продлевать напрямую можно только объявления, импортированные из XLSX Avito.")

    if listing.management_status not in [
        AvitoListing.ManagementStatus.MANAGED,
        AvitoListing.ManagementStatus.OUT_OF_SYNC,
    ]:
        raise AdEditingError("Это объявление не находится под управлением сервиса.")

    next_date_end = extend_date_end(get_avito_listing_date_end(listing))

    base_data = dict(listing.base_data or {})
    base_data[DATE_END_FIELD] = format_avito_date(next_date_end)

    listing.base_data = base_data
    listing.desired_status = AvitoListing.DesiredStatus.PUBLISH
    listing.save(update_fields=["base_data", "desired_status", "updated_at"])

    mark_avito_accounts_export_dirty([listing.avito_account_id])

    return listing


def bulk_update_avito_listing_management_status(
        *,
        workspace,
        avito_account,
        listing_ids,
        management_status,
):
    if avito_account.workspace_id != workspace.id:
        raise AdEditingError("Аккаунт Avito принадлежит другому workspace.")

    if management_status not in AvitoListing.ManagementStatus.values:
        raise AdEditingError("Некорректный статус управления объявлением.")

    queryset = AvitoListing.objects.filter(
        workspace=workspace,
        avito_account=avito_account,
        id__in=listing_ids,
        source=AvitoListing.Source.AVITO_EXCEL,
    )

    found_count = queryset.count()

    updated_count = queryset.update(
        management_status=management_status,
        updated_at=timezone.now(),
    )

    missing_count = len(set(listing_ids)) - found_count

    if updated_count:
        mark_avito_accounts_export_dirty([avito_account.id])

    return {
        "requested": len(listing_ids),
        "matched": found_count,
        "updated": updated_count,
        "missing": missing_count,
        "management_status": management_status.value if hasattr(management_status, "value") else str(management_status),
    }
