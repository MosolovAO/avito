import csv
import os
import tempfile
from pathlib import Path

from django.conf import settings
from django.utils.text import slugify

from avitotask.models import AdPublication, AvitoListing, ProductOptions
from datetime import timedelta
from django.utils import timezone
from avitotask.services.ad_export_state import (
    mark_avito_account_export_clean,
    mark_avito_account_export_error,
    mark_avito_account_exporting,
)

from avitotask.services.ad_publication_dates import (
    build_publication_default_date_end,
    format_avito_date,
)

IMAGE_URLS_SEPARATOR = " | "
CSV_DELIMITER = ";"
MULTI_VALUE_SEPARATOR = ", "
PUBLICATION_LIFETIME_DAYS = 30
AVITO_EXPORT_BASE_COLUMNS = [
    "Id",
    "DateEnd",
    "AvitoId",
    "Title",
    "ImageUrls",
    "Description",
    "Category",
    "Condition",
    "Price",
    "ListingFee",
    "EMail",
    "ContactPhone",
    "ManagerName",
    "AvitoStatus",
    "CompanyName",
    "ContactMethod",
    "AdType",
    "Availability",
    "Address",
]


def get_publication_avito_id(publication):
    listing = getattr(publication, "avito_listing", None)

    if not listing:
        return ""

    return listing.avito_id or ""


def get_backend_approved_csv_columns():
    option_columns = list(
        ProductOptions.objects
        .exclude(option_title_en__isnull=True)
        .exclude(option_title_en="")
        .order_by("option_title_en")
        .values_list("option_title_en", flat=True)
        .distinct()
    )

    return merge_fieldnames(AVITO_EXPORT_BASE_COLUMNS, option_columns)


def normalize_export_value(value):
    if value is None:
        return ""

    if isinstance(value, list):
        return MULTI_VALUE_SEPARATOR.join(
            str(item).strip()
            for item in value
            if str(item).strip()
        )

    if isinstance(value, dict):
        return ""

    return str(value)


def filter_row_to_approved_columns(row, approved_columns):
    return {
        column: normalize_export_value(row.get(column, ""))
        for column in approved_columns
    }


def build_publication_date_end(publication):
    return format_avito_date(build_publication_default_date_end(publication))


def build_publication_export_row(publication):
    """
    Собирает итоговые данные одной публикации для будущего CSV.

    Приоритет:
    системные поля + creative.base_data + creative.option_data + publication.overrides.
    """

    publication = ensure_publication_relations(publication)
    creative = publication.creative

    row = {
        "Id": publication.row_id,
        "AvitoId": get_publication_avito_id(publication),
        "Title": creative.title,
        "Description": creative.description,
        "ImageUrls": IMAGE_URLS_SEPARATOR.join(creative.image_urls or []),
        "Address": publication.address
    }

    row.update(creative.base_data or {})
    row.update(creative.option_data or {})
    row.update(publication.overrides or {})

    if not row.get("DateEnd"):
        row["DateEnd"] = build_publication_date_end(publication)

    row["Category"] = normalize_export_value(
        (creative.base_data or {}).get("Category")
    )

    return row


def build_listing_export_row(listing):
    """
    Собирает строку автозагрузки для объявления, импортированного из XLSX.

    option_category может быть пустой и не влияет на исходную CSV-категорию.
    """

    row = {
        "Id": listing.row_id,
        "AvitoId": listing.avito_id,
        "Title": listing.title,
        "Description": listing.description,
        "ImageUrls": IMAGE_URLS_SEPARATOR.join(listing.image_urls or []),
        "Address": listing.address,
        "AvitoStatus": listing.status,
    }

    row.update(listing.base_data or {})
    row.update(listing.option_data or {})

    # Сохраняем исходную категорию импортированного объявления.
    row["Category"] = normalize_export_value(
        (listing.base_data or {}).get("Category")
    )

    return row


def get_export_fieldnames(imported_listing_rows):
    """
    Формирует разрешённые колонки CSV.

    Для публикаций сервиса используется строгий backend whitelist.
    Дополнительные колонки разрешаются только для импортированных
    XLSX-объявлений, чтобы не потерять данные исходной выгрузки Avito.
    """
    fieldnames = get_backend_approved_csv_columns()

    imported_row_keys = []
    for row in imported_listing_rows:
        imported_row_keys.extend(row.keys())

    return merge_fieldnames(fieldnames, imported_row_keys)


def export_avito_account_publications_to_csv(*,
                                             workspace,
                                             avito_account,
                                             output_dir=None
                                             ):
    if avito_account.workspace_id != workspace.id:
        raise ValueError("Аккаунт Avito принадлежит другому workspace")
    output_dir = Path(output_dir or settings.STATIC_ROOT)
    output_dir.mkdir(parents=True, exist_ok=True)

    mark_avito_account_exporting(avito_account)

    publications = get_publications_for_export(
        workspace=workspace,
        avito_account=avito_account,
    )
    managed_imported_listings = get_managed_imported_listings_for_export(
        workspace=workspace,
        avito_account=avito_account,
    )

    publication_rows = [
        build_publication_export_row(publication)
        for publication in publications
    ]
    imported_listing_rows = [
        build_listing_export_row(listing)
        for listing in managed_imported_listings
    ]

    raw_rows = publication_rows + imported_listing_rows
    fieldnames = get_export_fieldnames(imported_listing_rows)

    rows = [
        filter_row_to_approved_columns(row, fieldnames)
        for row in raw_rows
    ]

    file_path = output_dir / build_export_file_name(avito_account)
    try:
        write_csv_atomic(file_path=file_path, fieldnames=fieldnames, rows=rows)
    except Exception as exc:
        mark_avito_account_export_error(avito_account=avito_account, error=exc)
        raise

    mark_avito_account_export_clean(avito_account=avito_account, file_path=file_path)

    return file_path


def get_publications_for_export(*, workspace, avito_account):
    return (
        AdPublication.objects
        .select_related("creative", "avito_account", "avito_listing")
        .filter(
            workspace=workspace,
            avito_account=avito_account,
            status=AdPublication.Status.ACTIVE
        )
        .order_by("created_at", "id")
    )


def get_managed_imported_listings_for_export(*, workspace, avito_account):
    return (
        AvitoListing.objects
        .filter(
            workspace=workspace,
            avito_account=avito_account,
            source=AvitoListing.Source.AVITO_EXCEL,
            management_status=AvitoListing.ManagementStatus.MANAGED,
            desired_status=AvitoListing.DesiredStatus.PUBLISH,
            publication__isnull=True,
        )
        .order_by("created_at", "id")
    )


def merge_fieldnames(current_fieldnames, new_fieldnames):
    result = list(current_fieldnames)

    for fieldname in new_fieldnames:
        if fieldname not in result:
            result.append(fieldname)

    return result


def build_export_file_name(avito_account):
    avito_slug = slugify(avito_account.name) or f"avito-account-{avito_account.id}"
    return f"{avito_slug}_avito_autoload.csv"


def write_csv_atomic(*, file_path, fieldnames, rows):
    fd, temp_path = tempfile.mkstemp(
        dir=str(file_path.parent),
        prefix=f".{file_path.name}.",
        suffix=".tmp"
    )

    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(
                csv_file,
                fieldnames=fieldnames,
                delimiter=CSV_DELIMITER,
                extrasaction="ignore"
            )
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temp_path, file_path)

    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


def ensure_publication_relations(publication):
    if isinstance(publication, AdPublication) and hasattr(publication, "_state"):
        if "creative" in publication._state.fields_cache:
            return publication

    return (
        AdPublication.objects
        .select_related("creative", "avito_account")
        .get(id=publication.id)
    )
