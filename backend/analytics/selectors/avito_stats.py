from datetime import date, datetime
from decimal import Decimal

from django.db.models import Max, Sum
from django.utils import timezone

from analytics.models import (
    AvitoListingDailyStats,
    AvitoListingStatsCoverage,
    AvitoStatsSyncState,
)


def build_avito_listing_stats_report(
        *,
        workspace,
        avito_account,
        date_from,
        date_to,
        listing_ids=None,
        page=1,
        page_size=50,
):
    listings_queryset = (
        avito_account.avito_listings
        .filter(workspace=workspace)
        .only(
            "id",
            "avito_id",
            "title",
            "status",
        )
        .order_by("id")
    )

    if listing_ids:
        listings_queryset = listings_queryset.filter(
            id__in=listing_ids,
        )

    listings_count = listings_queryset.count()
    offset = (page - 1) * page_size

    listings = list(
        listings_queryset[offset:offset + page_size]
    )
    page_listing_ids = [
        listing.id
        for listing in listings
    ]

    total_pages = (
        (listings_count + page_size - 1) // page_size
        if listings_count
        else 0
    )

    coverage_queryset = (
        AvitoListingStatsCoverage.objects
        .filter(
            workspace=workspace,
            listing__avito_account=avito_account,
        )
    )

    if listing_ids:
        coverage_queryset = coverage_queryset.filter(
            listing_id__in=listing_ids,
        )

    base_complete_count = coverage_queryset.filter(
        coverage_from__lte=date_from,
        finalized_through__gte=date_to,
    ).count()

    spending_complete_count = coverage_queryset.filter(
        spending_coverage_from__lte=date_from,
        spending_finalized_through__gte=date_to,
    ).count()

    report_stats_complete = (
            base_complete_count == listings_count
    )
    report_spend_complete = (
            report_stats_complete
            and spending_complete_count == listings_count
    )

    all_stats_queryset = (
        AvitoListingDailyStats.objects
        .filter(
            workspace=workspace,
            listing__avito_account=avito_account,
            date__gte=date_from,
            date__lte=date_to,
        )
    )

    if listing_ids:
        all_stats_queryset = all_stats_queryset.filter(
            listing_id__in=listing_ids,
        )

    aggregated_totals = all_stats_queryset.aggregate(
        views=Sum("views"),
        contacts=Sum("contacts"),
        favorites=Sum("favorites"),
        total_spend=Sum("total_spend"),
    )

    if report_stats_complete:
        report_views = int(
            aggregated_totals["views"] or 0
        )
        report_contacts = int(
            aggregated_totals["contacts"] or 0
        )
        report_favorites = int(
            aggregated_totals["favorites"] or 0
        )
    else:
        report_views = None
        report_contacts = None
        report_favorites = None

    if report_spend_complete:
        report_total_spend = (
            aggregated_totals["total_spend"]
            if aggregated_totals["total_spend"] is not None
            else Decimal("0.00")
        )
    else:
        report_total_spend = None

    page_coverages_by_listing_id = {
        coverage.listing_id: coverage
        for coverage in (
            AvitoListingStatsCoverage.objects
            .filter(
                workspace=workspace,
                listing__avito_account=avito_account,
                listing_id__in=page_listing_ids,
            )
        )
    }

    page_stats_queryset = (
        AvitoListingDailyStats.objects
        .filter(
            workspace=workspace,
            listing__avito_account=avito_account,
            listing_id__in=page_listing_ids,
            date__gte=date_from,
            date__lte=date_to,
        )
        .order_by("listing_id", "date")
    )

    listings_by_id = {}

    for listing in listings:
        coverage = page_coverages_by_listing_id.get(
            listing.id
        )

        stats_complete = is_requested_range_covered(
            coverage=coverage,
            date_from=date_from,
            date_to=date_to,
        )
        spend_complete = (
                stats_complete
                and is_requested_spending_range_covered(
            coverage=coverage,
            date_from=date_from,
            date_to=date_to,
        )
        )

        listings_by_id[listing.id] = {
            "listing_id": listing.id,
            "avito_id": listing.avito_id,
            "title": listing.title,
            "status": listing.status,
            "stats_complete": stats_complete,
            "spend_complete": spend_complete,
            "totals": {
                "views": 0 if stats_complete else None,
                "contacts": 0 if stats_complete else None,
                "favorites": 0 if stats_complete else None,
                "total_spend": (
                    Decimal("0.00")
                    if spend_complete
                    else None
                ),
                "cost_per_contact": None,
                "views_to_contacts_conversion": None,
            },
            "daily": [],
        }

    for stat in page_stats_queryset:
        listing_item = listings_by_id[stat.listing_id]
        coverage = page_coverages_by_listing_id.get(
            stat.listing_id
        )

        daily_spend_complete = (
            is_requested_spending_range_covered(
                coverage=coverage,
                date_from=stat.date,
                date_to=stat.date,
            )
        )

        if daily_spend_complete:
            daily_total_spend = (
                stat.total_spend
                if stat.total_spend is not None
                else Decimal("0.00")
            )
        else:
            daily_total_spend = None

        listing_item["daily"].append({
            "date": stat.date.isoformat(),
            "views": stat.views,
            "contacts": stat.contacts,
            "favorites": stat.favorites,
            "total_spend": format_money(
                daily_total_spend
            ),
            "cost_per_contact": format_money(
                calculate_cost_per_contact(
                    daily_total_spend,
                    stat.contacts,
                )
            ),
            "views_to_contacts_conversion": format_percentage(
                calculate_views_to_contacts_conversion(
                    stat.views,
                    stat.contacts,
                )
            ),
        })

        if listing_item["stats_complete"]:
            listing_item["totals"]["views"] += stat.views
            listing_item["totals"]["contacts"] += stat.contacts
            listing_item["totals"]["favorites"] += stat.favorites

        if listing_item["spend_complete"]:
            listing_item["totals"]["total_spend"] += (
                stat.total_spend
                if stat.total_spend is not None
                else Decimal("0.00")
            )

    listing_items = list(listings_by_id.values())

    for listing_item in listing_items:
        listing_totals = listing_item["totals"]

        if listing_item["stats_complete"]:
            listing_totals[
                "views_to_contacts_conversion"
            ] = format_percentage(
                calculate_views_to_contacts_conversion(
                    listing_totals["views"],
                    listing_totals["contacts"],
                )
            )

        if listing_item["spend_complete"]:
            listing_totals["cost_per_contact"] = format_money(
                calculate_cost_per_contact(
                    listing_totals["total_spend"],
                    listing_totals["contacts"],
                )
            )

        listing_totals["total_spend"] = format_money(
            listing_totals["total_spend"]
        )

    return {
        "avito_account_id": avito_account.id,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "stats_complete": report_stats_complete,
        "spend_complete": report_spend_complete,
        "count": listings_count,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "totals": {
            "views": report_views,
            "contacts": report_contacts,
            "favorites": report_favorites,
            "total_spend": format_money(
                report_total_spend
            ),
            "cost_per_contact": format_money(
                calculate_cost_per_contact(
                    report_total_spend,
                    report_contacts,
                )
                if report_spend_complete
                else None
            ),
            "views_to_contacts_conversion": format_percentage(
                calculate_views_to_contacts_conversion(
                    report_views,
                    report_contacts,
                )
                if report_stats_complete
                else None
            ),
        },
        "listings": listing_items,
    }


def add_nullable_money(current, value):
    if value is None:
        return current

    if current is None:
        return value

    return current + value


def calculate_cost_per_contact(total_spend, contacts):
    if total_spend is None:
        return None

    if contacts == 0:
        return None

    return (total_spend / Decimal(contacts)).quantize(Decimal("0.01"))


def format_percentage(value):
    if value is None:
        return None

    return f"{value:.2f}"


def calculate_views_to_contacts_conversion(views, contacts):
    if views == 0:
        return None

    return (
            Decimal(contacts)
            / Decimal(views)
            * Decimal("100")
    ).quantize(Decimal("0.01"))


def format_money(value):
    if value is None:
        return None

    return f"{value:.2f}"


def build_avito_ads_stats_payload(
        *,
        workspace,
        avito_account,
        items,
        date_from=None,
        date_to=None,
):
    """
    Обогащает только текущую страницу объявлений.

    date_from/date_to пока не передаются frontend-ом, но selector уже
    готов для будущего фильтра периода.
    """

    listing_ids = {
        item["avito_listing_id"]
        for item in items
        if item.get("avito_listing_id")
    }

    stats_queryset = AvitoListingDailyStats.objects.filter(
        workspace=workspace,
        listing__avito_account=avito_account,
        listing_id__in=listing_ids,
    )

    if date_from is not None:
        stats_queryset = stats_queryset.filter(date__gte=date_from)

    if date_to is not None:
        stats_queryset = stats_queryset.filter(date__lte=date_to)

    totals_by_listing_id = {
        row["listing_id"]: row
        for row in (
            stats_queryset
            .values("listing_id")
            .annotate(
                views=Sum("views"),
                contacts=Sum("contacts"),
                favorites=Sum("favorites"),
                total_spend=Sum("total_spend"),
                updated_at=Max("updated_at"),
            )
        )
    }

    coverages_by_listing_id = {
        coverage.listing_id: coverage
        for coverage in (
            AvitoListingStatsCoverage.objects
            .filter(
                workspace=workspace,
                listing__avito_account=avito_account,
                listing_id__in=listing_ids,
            )
        )
    }

    sync_state = (
        AvitoStatsSyncState.objects
        .filter(
            workspace=workspace,
            avito_account=avito_account,
        )
        .first()
    )

    enriched_items = [
        {
            **item,
            "stats": build_ad_stats_item(
                item=item,
                totals=totals_by_listing_id.get(
                    item.get("avito_listing_id")
                ),
                coverage=coverages_by_listing_id.get(
                    item.get("avito_listing_id")
                ),
                sync_state=sync_state,
                date_from=date_from,
                date_to=date_to,
            ),
        }
        for item in items
    ]

    return {
        "stats_sync": serialize_stats_sync_state(sync_state),
        "results": enriched_items,
    }


def get_item_published_date(item):
    published_at = item.get("published_at")

    if published_at is None:
        return None

    if isinstance(published_at, datetime):
        if timezone.is_aware(published_at):
            return timezone.localdate(published_at)

        return published_at.date()

    if isinstance(published_at, date):
        return published_at

    return None


def build_ad_stats_item(
        *,
        item,
        totals,
        coverage,
        sync_state,
        date_from=None,
        date_to=None,
):
    if not item.get("avito_listing_id") or not item.get("avito_id"):
        return {
            "status": "unavailable",
            "views": None,
            "contacts": None,
            "favorites": None,
            "total_spend": None,
            "spend_complete": False,
            "views_to_contacts_conversion": None,
            "updated_at": None,
        }

    published_date = get_item_published_date(item)

    if not is_requested_range_covered(
            coverage=coverage,
            date_from=date_from,
            date_to=date_to,
            available_from=published_date,
    ):
        status = (
            "error"
            if (
                    sync_state
                    and sync_state.status == AvitoStatsSyncState.Status.ERROR
            )
            else "processing"
        )

        return {
            "status": status,
            "views": None,
            "contacts": None,
            "favorites": None,
            "total_spend": None,
            "spend_complete": False,
            "views_to_contacts_conversion": None,
            "updated_at": None,
        }

    views = int(totals["views"]) if totals else 0
    contacts = int(totals["contacts"]) if totals else 0

    spend_complete = is_requested_spending_range_covered(
        coverage=coverage,
        date_from=date_from,
        date_to=date_to,
        available_from=published_date,
    )

    if spend_complete:
        total_spend = (
            totals["total_spend"]
            if totals and totals["total_spend"] is not None
            else Decimal("0.00")
        )
    else:
        total_spend = None

    return {
        "status": "ready",
        "views": views,
        "contacts": contacts,
        "favorites": int(totals["favorites"]) if totals else 0,
        "total_spend": format_money(total_spend),
        "spend_complete": spend_complete,
        "views_to_contacts_conversion": format_percentage(
            calculate_views_to_contacts_conversion(
                views,
                contacts,
            )
        ),
        "updated_at": serialize_datetime(
            totals["updated_at"]
            if totals
            else (
                coverage.last_successful_at
                if coverage
                else None
            )
        ),
    }


def is_requested_range_covered(
        *,
        coverage,
        date_from=None,
        date_to=None,
        available_from=None,
):
    if (
            date_from is not None
            and date_to is not None
            and available_from is not None
    ):
        # До появления объявления показатели гарантированно равны нулю.
        if date_to < available_from:
            return True

        date_from = max(
            date_from,
            available_from,
        )

    if coverage is None:
        return False

    if (
            coverage.coverage_from is None
            or coverage.finalized_through is None
    ):
        return False

    if date_from is None and date_to is None:
        return True

    if date_from is None or date_to is None:
        return False

    return (
            coverage.coverage_from <= date_from
            and coverage.finalized_through >= date_to
    )


def is_requested_spending_range_covered(
        *,
        coverage,
        date_from=None,
        date_to=None,
        available_from=None,
):
    if (
            date_from is not None
            and date_to is not None
            and available_from is not None
    ):
        # До публикации расходы также гарантированно равны нулю.
        if date_to < available_from:
            return True

        date_from = max(
            date_from,
            available_from,
        )

    if coverage is None:
        return False

    if (
            coverage.spending_coverage_from is None
            or coverage.spending_finalized_through is None
    ):
        return False

    if date_from is None and date_to is None:
        if (
                coverage.coverage_from is None
                or coverage.finalized_through is None
        ):
            return False

        return (
                coverage.spending_coverage_from
                <= coverage.coverage_from
                and coverage.spending_finalized_through
                >= coverage.finalized_through
        )

    if date_from is None or date_to is None:
        return False

    return (
            coverage.spending_coverage_from <= date_from
            and coverage.spending_finalized_through >= date_to
    )


def serialize_stats_sync_state(sync_state):
    if sync_state is None:
        return {
            "status": AvitoStatsSyncState.Status.NOT_STARTED,
            "coverage_from": None,
            "coverage_to": None,
            "requested_at": None,
            "started_at": None,
            "finished_at": None,
            "last_successful_at": None,
            "error": "",
        }

    return {
        "status": sync_state.status,
        "coverage_from": serialize_date(sync_state.coverage_from),
        "coverage_to": serialize_date(sync_state.coverage_to),
        "requested_at": serialize_datetime(sync_state.requested_at),
        "started_at": serialize_datetime(sync_state.started_at),
        "finished_at": serialize_datetime(sync_state.finished_at),
        "last_successful_at": serialize_datetime(
            sync_state.last_successful_at
        ),
        "error": sync_state.error,
    }


def serialize_date(value):
    return value.isoformat() if value else None


def serialize_datetime(value):
    return value.isoformat() if value else None
