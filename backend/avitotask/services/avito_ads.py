from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db.models import Q

from avitotask.models import AdPublication, AvitoAccount, AvitoListing

from django.db.models.functions import Coalesce

ENTITY_TYPE_AVITO_LISTING = "avito_listing"
ENTITY_TYPE_AD_PUBLICATION = "ad_publication"


@dataclass(frozen=True)
class AvitoAdListFilters:
    entity_type: str = ""
    source: str = ""
    status: str = ""
    desired_status: str = ""
    management_status: str = ""
    has_avito_id: str = ""
    has_errors: str = ""
    search: str = ""


@dataclass(frozen=True)
class AvitoAdListResult:
    count: int
    page: int
    page_size: int
    results: list[dict[str, Any]]


def list_avito_account_ads(
        *,
        workspace,
        avito_account: AvitoAccount,
        filters: AvitoAdListFilters | None = None,
        page: int = 1,
        page_size: int = 50,
) -> AvitoAdListResult:
    """
    Единый список объявлений для общей страницы.

    Оптимизация:
    - count считаем в БД;
    - сериализуем не все записи, а только кандидатов для нужной страницы;
    - итоговую сортировку двух источников оставляем в Python.
    """

    if avito_account.workspace_id != workspace.id:
        raise ValueError("AvitoAccount принадлежит другому workspace.")

    filters = filters or AvitoAdListFilters()
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)

    start = (page - 1) * page_size
    end = start + page_size

    items = []
    total_count = 0

    if filters.entity_type in ("", ENTITY_TYPE_AVITO_LISTING):
        listings_queryset = (
            get_filtered_listings(
                workspace=workspace,
                avito_account=avito_account,
                filters=filters,
            )
            .annotate(sort_value=Coalesce("last_seen_at", "updated_at", "created_at"))
            .order_by("-sort_value")
        )

        total_count += listings_queryset.count()

        items.extend(
            serialize_listing_for_ads_page(listing)
            for listing in listings_queryset[:end]
        )

    if filters.entity_type in ("", ENTITY_TYPE_AD_PUBLICATION):
        publications_queryset = (
            get_filtered_unlinked_publications(
                workspace=workspace,
                avito_account=avito_account,
                filters=filters,
            )
            .annotate(sort_value=Coalesce("updated_at", "created_at"))
            .order_by("-sort_value")
        )

        total_count += publications_queryset.count()

        items.extend(
            serialize_publication_for_ads_page(publication)
            for publication in publications_queryset[:end]
        )

    items.sort(
        key=lambda item: item["sort_at"] or datetime.min,
        reverse=True,
    )

    return AvitoAdListResult(
        count=total_count,
        page=page,
        page_size=page_size,
        results=[
            strip_internal_fields(item)
            for item in items[start:end]
        ],
    )


def get_filtered_listings(
        *,
        workspace,
        avito_account: AvitoAccount,
        filters: AvitoAdListFilters,
):
    queryset = (
        AvitoListing.objects
        .filter(
            workspace=workspace,
            avito_account=avito_account,
        )
        .select_related("avito_account", "publication")
        .order_by("-last_seen_at", "-created_at")
    )

    if filters.source:
        queryset = queryset.filter(source=filters.source)

    if filters.status:
        queryset = queryset.filter(status=filters.status)

    if filters.desired_status:
        queryset = queryset.filter(desired_status=filters.desired_status)

    if filters.management_status:
        queryset = queryset.filter(management_status=filters.management_status)

    if filters.has_avito_id in ("1", "true", "True"):
        queryset = queryset.exclude(avito_id="")

    if filters.has_avito_id in ("0", "false", "False"):
        queryset = queryset.filter(avito_id="")

    if filters.has_errors in ("1", "true", "True"):
        queryset = queryset.filter(
            Q(imported_payload__autoload_report__error__isnull=False) |
            Q(imported_payload__autoload_report__errors__isnull=False) |
            Q(imported_payload__autoload_report__error_message__isnull=False)
        )

    if filters.search:
        queryset = queryset.filter(
            Q(title__icontains=filters.search) |
            Q(address__icontains=filters.search) |
            Q(row_id__icontains=filters.search) |
            Q(avito_id__icontains=filters.search)
        )

    return queryset


def get_filtered_unlinked_publications(
        *,
        workspace,
        avito_account: AvitoAccount,
        filters: AvitoAdListFilters,
):
    queryset = (
        AdPublication.objects
        .filter(
            workspace=workspace,
            avito_account=avito_account,
            avito_listing__isnull=True,
        )
        .select_related("avito_account", "creative", "task", "batch")
        .order_by("-created_at")
    )

    if filters.source:
        queryset = queryset.filter(source=filters.source)

    if filters.status:
        queryset = queryset.filter(status=filters.status)

    if filters.desired_status or filters.management_status:
        return queryset.none()

    if filters.has_avito_id in ("1", "true", "True"):
        return queryset.none()

    if filters.has_errors in ("1", "true", "True"):
        queryset = queryset.filter(status=AdPublication.Status.ERROR)

    if filters.search:
        queryset = queryset.filter(
            Q(creative__title__icontains=filters.search) |
            Q(address__icontains=filters.search) |
            Q(row_id__icontains=filters.search)
        )

    return queryset


def serialize_listing_for_ads_page(listing: AvitoListing) -> dict[str, Any]:
    autoload_error = extract_listing_autoload_error(listing)

    return {
        "entity_type": ENTITY_TYPE_AVITO_LISTING,
        "id": listing.id,
        "avito_account": listing.avito_account_id,
        "avito_account_name": listing.avito_account.name,
        "publication": listing.publication_id,
        "publication_row_id": listing.publication.row_id if listing.publication else None,
        "source": listing.source,
        "status": listing.status,
        "desired_status": listing.desired_status,
        "management_status": listing.management_status,
        "row_id": listing.row_id,
        "avito_id": listing.avito_id,
        "title": listing.title,
        "description": listing.description,
        "address": listing.address,
        "url": listing.url,
        "image_urls": listing.image_urls,
        "base_data": listing.base_data,
        "option_data": listing.option_data,
        "unmapped_data": listing.unmapped_data,
        "has_publication": listing.publication_id is not None,
        "has_avito_id": bool(listing.avito_id),
        "has_errors": bool(autoload_error),
        "autoload_error": autoload_error,
        "published_at": listing.published_at,
        "last_seen_at": listing.last_seen_at,
        "created_at": listing.created_at,
        "updated_at": listing.updated_at,
        "sort_at": listing.last_seen_at or listing.updated_at or listing.created_at,
    }


def serialize_publication_for_ads_page(publication: AdPublication) -> dict[str, Any]:
    autoload_error = extract_publication_autoload_error(publication)

    return {
        "entity_type": ENTITY_TYPE_AD_PUBLICATION,
        "id": publication.id,
        "avito_account": publication.avito_account_id,
        "avito_account_name": publication.avito_account.name,
        "publication": publication.id,
        "publication_row_id": publication.row_id,
        "source": publication.source,
        "status": publication.status,
        "desired_status": None,
        "management_status": None,
        "row_id": publication.row_id,
        "avito_id": None,
        "title": publication.creative.title,
        "description": publication.creative.description,
        "address": publication.address,
        "url": None,
        "image_urls": publication.creative.image_urls,
        "base_data": publication.creative.base_data,
        "option_data": publication.creative.option_data,
        "unmapped_data": {},
        "has_publication": True,
        "has_avito_id": False,
        "has_errors": bool(autoload_error),
        "autoload_error": autoload_error,
        "published_at": publication.published_at,
        "last_seen_at": None,
        "created_at": publication.created_at,
        "updated_at": publication.updated_at,
        "sort_at": publication.updated_at or publication.created_at,
    }


def extract_listing_autoload_error(listing: AvitoListing) -> dict[str, Any] | None:
    payload = listing.imported_payload or {}
    report = payload.get("autoload_report") or {}

    error = (
            report.get("error")
            or report.get("errors")
            or report.get("error_message")
            or report.get("message")
            or report.get("reason")
    )

    if not error:
        return None

    return {
        "message": error,
        "raw": report,
    }


def extract_publication_autoload_error(publication: AdPublication) -> dict[str, Any] | None:
    address_data = publication.address_data or {}
    return address_data.get("autoload_error") or None


def strip_internal_fields(item: dict[str, Any]) -> dict[str, Any]:
    result = dict(item)
    result.pop("sort_at", None)
    return result
