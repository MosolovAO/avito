from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from analytics.selectors.avito_stats import (
    build_avito_ads_stats_payload,
)
from django.db.models import F, Q
from django.db.models.functions import Coalesce

from avitotask.models import AdPublication, AvitoAccount, AvitoListing

from avitotask.services.ad_publication_dates import (
    format_avito_date,
    get_publication_date_end_source,
    get_publication_effective_date_end,
)

ENTITY_TYPE_AVITO_LISTING = "avito_listing"
ENTITY_TYPE_AD_PUBLICATION = "ad_publication"


def get_listing_date_end_value(listing: AvitoListing) -> str:
    if listing.published_end is not None:
        return format_avito_date(listing.published_end)

    return (
            (listing.base_data or {}).get("DateEnd")
            or (listing.option_data or {}).get("DateEnd")
            or (listing.raw_data or {}).get("AvitoDateEnd")
            or ""
    )


def get_linked_ad_date_end_payload(listing: AvitoListing) -> dict[str, str]:
    listing_date_end = get_listing_date_end_value(listing)

    if listing_date_end:
        return {
            "date_end": str(listing_date_end),
            "date_end_source": "avito",
        }

    publication = listing.publication

    return {
        "date_end": format_avito_date(get_publication_effective_date_end(publication)),
        "date_end_source": get_publication_date_end_source(publication),
    }


def get_listing_date_end_payload(listing: AvitoListing) -> dict[str, str]:
    listing_date_end = get_listing_date_end_value(listing)

    return {
        "date_end": str(listing_date_end) if listing_date_end else "",
        "date_end_source": "avito" if listing_date_end else "none",
    }


def get_publication_date_end_payload(publication: AdPublication) -> dict[str, str]:
    return {
        "date_end": format_avito_date(get_publication_effective_date_end(publication)),
        "date_end_source": get_publication_date_end_source(publication),
    }


def order_queryset_by_published_end(queryset, *, is_desc):
    published_end_order = (
        F("published_end").desc(nulls_last=True)
        if is_desc
        else F("published_end").asc(nulls_last=True)
    )

    return queryset.order_by(
        published_end_order,
        "id",
    )


def get_date_end_candidate_sort_key(
        candidate: tuple[date | None, str, Any],
        *,
        is_desc: bool,
):
    published_end, entity_type, item = candidate

    if published_end is None:
        date_order = 0
    else:
        ordinal = published_end.toordinal()
        date_order = -ordinal if is_desc else ordinal

    entity_order = (
        0
        if entity_type == ENTITY_TYPE_AD_PUBLICATION
        else 1
    )

    return (
        published_end is None,
        date_order,
        item.id,
        entity_order,
    )


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
    address: str = ""
    ordering: str = "-date_end"


@dataclass(frozen=True)
class AvitoAdListResult:
    count: int
    page: int
    page_size: int
    results: list[dict[str, Any]]
    stats_sync: dict[str, Any]


def list_avito_account_ads(
        *,
        workspace,
        avito_account: AvitoAccount,
        filters: AvitoAdListFilters | None = None,
        page: int = 1,
        page_size: int = 50,
) -> AvitoAdListResult:
    if avito_account.workspace_id != workspace.id:
        raise ValueError(
            "AvitoAccount принадлежит другому workspace."
        )

    filters = filters or AvitoAdListFilters()
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)

    start = (page - 1) * page_size
    end = start + page_size
    ordering = filters.ordering or "-date_end"
    sort_by_date_end = ordering in {
        "date_end",
        "-date_end",
    }
    is_date_desc = ordering == "-date_end"

    items = []
    date_end_candidates = []
    total_count = 0

    include_listings = filters.entity_type in (
        "",
        ENTITY_TYPE_AVITO_LISTING,
        ENTITY_TYPE_AD_PUBLICATION,
    )

    if include_listings:
        listings_queryset = get_filtered_listings(
            workspace=workspace,
            avito_account=avito_account,
            filters=filters,
        )

        if filters.entity_type == ENTITY_TYPE_AVITO_LISTING:
            listings_queryset = listings_queryset.exclude(
                source=AvitoListing.Source.SERVICE,
                publication__isnull=False,
            )

        if filters.entity_type == ENTITY_TYPE_AD_PUBLICATION:
            listings_queryset = listings_queryset.filter(
                source=AvitoListing.Source.SERVICE,
                publication__isnull=False,
            )

        total_count += listings_queryset.count()

        if sort_by_date_end:
            limited_listings = list(
                order_queryset_by_published_end(
                    listings_queryset,
                    is_desc=is_date_desc,
                )[:end]
            )

            date_end_candidates.extend(
                (
                    listing.published_end,
                    ENTITY_TYPE_AVITO_LISTING,
                    listing,
                )
                for listing in limited_listings
            )
        else:
            items.extend(
                serialize_listing_for_ads_page(listing)
                for listing in listings_queryset[:end]
            )

    if filters.entity_type in (
            "",
            ENTITY_TYPE_AD_PUBLICATION,
    ):
        publications_queryset = (
            get_filtered_unlinked_publications(
                workspace=workspace,
                avito_account=avito_account,
                filters=filters,
            )
        )

        total_count += publications_queryset.count()

        if sort_by_date_end:
            limited_publications = list(
                order_queryset_by_published_end(
                    publications_queryset,
                    is_desc=is_date_desc,
                )[:end]
            )

            date_end_candidates.extend(
                (
                    publication.published_end,
                    ENTITY_TYPE_AD_PUBLICATION,
                    publication,
                )
                for publication in limited_publications
            )
        else:
            publications_queryset = (
                publications_queryset
                .annotate(
                    sort_value=Coalesce(
                        "updated_at",
                        "created_at",
                    ),
                )
                .order_by("-sort_value")
            )
            items.extend(
                serialize_publication_for_ads_page(publication)
                for publication in publications_queryset[:end]
            )

    if sort_by_date_end:
        date_end_candidates.sort(
            key=lambda candidate: get_date_end_candidate_sort_key(
                candidate,
                is_desc=is_date_desc,
            ),
        )

        page_candidates = date_end_candidates[start:end]

        items = [
            (
                serialize_listing_for_ads_page(item)
                if entity_type == ENTITY_TYPE_AVITO_LISTING
                else serialize_publication_for_ads_page(item)
            )
            for _, entity_type, item in page_candidates
        ]
    else:
        items.sort(
            key=lambda item: item["sort_at"] or datetime.min,
            reverse=True,
        )
        items = items[start:end]

    serialized_results = [
        strip_internal_fields(item)
        for item in items
    ]

    stats_payload = build_avito_ads_stats_payload(
        workspace=workspace,
        avito_account=avito_account,
        items=serialized_results,
    )

    return AvitoAdListResult(
        count=total_count,
        page=page,
        page_size=page_size,
        results=stats_payload["results"],
        stats_sync=stats_payload["stats_sync"],
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
        .select_related(
            "avito_account",
            "option_category",
            "publication",
            "publication__creative",
            "publication__creative__option_category",
        )
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

    if filters.address:
        queryset = queryset.filter(address__icontains=filters.address)

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
        .select_related(
            "avito_account",
            "creative",
            "creative__option_category",
            "task",
            "batch",
        )
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

    if filters.address:
        queryset = queryset.filter(address__icontains=filters.address)

    return queryset


def serialize_linked_publication_listing_for_ads_page(listing: AvitoListing) -> dict[str, Any]:
    publication = listing.publication
    option_category = publication.creative.option_category
    autoload_error = extract_listing_autoload_error(listing)
    date_end_payload = get_linked_ad_date_end_payload(listing)

    return {
        "entity_type": ENTITY_TYPE_AD_PUBLICATION,
        "id": publication.id,
        "avito_account": listing.avito_account_id,
        "avito_account_name": listing.avito_account.name,
        "publication": publication.id,
        "option_category_id": (
            option_category.id
            if option_category
            else None
        ),
        "option_category": (
            option_category.category
            if option_category
            else None
        ),
        "publication_row_id": publication.row_id,
        "source": publication.source,
        "status": publication.status,
        "desired_status": listing.desired_status,
        "management_status": listing.management_status,
        "row_id": publication.row_id,
        "avito_id": listing.avito_id,
        "title": listing.title,
        "description": listing.description,
        "address": listing.address,
        "url": listing.url,
        "image_urls": listing.image_urls,
        "base_data": listing.base_data,
        "option_data": listing.option_data,
        "unmapped_data": listing.unmapped_data,
        "has_publication": True,
        "has_avito_id": bool(listing.avito_id),
        "has_errors": bool(autoload_error),
        "autoload_error": autoload_error,
        "published_at": listing.published_at or publication.published_at,
        "last_seen_at": listing.last_seen_at,
        "created_at": publication.created_at,
        "updated_at": max(publication.updated_at, listing.updated_at),
        "sort_at": (
                listing.last_seen_at
                or listing.updated_at
                or publication.updated_at
        ),
        "published_end": format_avito_date(
            publication.published_end
            or get_publication_effective_date_end(publication)
        ),
        "date_end": date_end_payload["date_end"],
        "date_end_source": date_end_payload["date_end_source"],
        "avito_listing_id": listing.id,
    }


def serialize_listing_for_ads_page(listing: AvitoListing) -> dict[str, Any]:
    if listing.publication_id and listing.source == AvitoListing.Source.SERVICE:
        return serialize_linked_publication_listing_for_ads_page(listing)

    option_category = listing.option_category
    autoload_error = extract_listing_autoload_error(listing)
    date_end_payload = get_listing_date_end_payload(listing)

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
        "sort_at": (
                listing.last_seen_at
                or listing.updated_at
                or listing.created_at
        ),
        "published_end": format_avito_date(
            listing.published_end,
        ),
        "date_end": date_end_payload["date_end"],
        "date_end_source": date_end_payload["date_end_source"],
        "option_category_id": (
            option_category.id
            if option_category
            else None
        ),
        "option_category": (
            option_category.category
            if option_category
            else None
        ),
        "avito_listing_id": listing.id,
    }


def serialize_publication_for_ads_page(publication: AdPublication) -> dict[str, Any]:
    option_category = publication.creative.option_category
    autoload_error = extract_publication_autoload_error(publication)
    date_end_payload = get_publication_date_end_payload(publication)

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
        "sort_at": (
                publication.updated_at
                or publication.created_at
        ),
        "published_end": format_avito_date(
            publication.published_end
            or get_publication_effective_date_end(publication)
        ),
        "date_end": date_end_payload["date_end"],
        "date_end_source": date_end_payload["date_end_source"],
        "option_category_id": (
            option_category.id
            if option_category
            else None
        ),
        "option_category": (
            option_category.category
            if option_category
            else None
        ),
        "avito_listing_id": None,
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
