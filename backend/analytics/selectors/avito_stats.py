from decimal import Decimal

from django.db.models import Max, Sum

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
):
    stats_queryset = (
        AvitoListingDailyStats.objects
        .filter(
            workspace=workspace,
            listing__avito_account=avito_account,
            date__gte=date_from,
            date__lte=date_to,
        )
        .select_related("listing")
        .order_by("listing_id", "date")
    )

    if listing_ids:
        stats_queryset = stats_queryset.filter(listing_id__in=listing_ids)

    listings_by_id = {}
    totals = {
        "views": 0,
        "contacts": 0,
        "favorites": 0,
        "total_spend": None,
    }

    for stat in stats_queryset:
        listing = stat.listing

        if listing.id not in listings_by_id:
            listings_by_id[listing.id] = {
                "listing_id": listing.id,
                "avito_id": listing.avito_id,
                "title": listing.title,
                "status": listing.status,
                "totals": {
                    "views": 0,
                    "contacts": 0,
                    "favorites": 0,
                    "total_spend": None,
                    "cost_per_contact": None,
                },
                "daily": [],
            }

        listing_item = listings_by_id[listing.id]
        daily_total_spend = format_money(stat.total_spend)
        daily_cost_per_contact = calculate_cost_per_contact(stat.total_spend, stat.contacts)

        listing_item["daily"].append({
            "date": stat.date.isoformat(),
            "views": stat.views,
            "contacts": stat.contacts,
            "favorites": stat.favorites,
            "total_spend": daily_total_spend,
            "cost_per_contact": format_money(daily_cost_per_contact),
        })

        listing_item["totals"]["views"] += stat.views
        listing_item["totals"]["contacts"] += stat.contacts
        listing_item["totals"]["favorites"] += stat.favorites
        listing_item["totals"]["total_spend"] = add_nullable_money(
            listing_item["totals"]["total_spend"],
            stat.total_spend,
        )

        totals["views"] += stat.views
        totals["contacts"] += stat.contacts
        totals["favorites"] += stat.favorites
        totals["total_spend"] = add_nullable_money(totals["total_spend"], stat.total_spend)

    for listing_item in listings_by_id.values():
        listing_item["totals"]["cost_per_contact"] = format_money(
            calculate_cost_per_contact(
                listing_item["totals"]["total_spend"],
                listing_item["totals"]["contacts"],
            )
        )
        listing_item["totals"]["total_spend"] = format_money(
            listing_item["totals"]["total_spend"]
        )

    report = {
        "avito_account_id": avito_account.id,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "totals": {
            "views": totals["views"],
            "contacts": totals["contacts"],
            "favorites": totals["favorites"],
            "total_spend": format_money(totals["total_spend"]),
            "cost_per_contact": format_money(
                calculate_cost_per_contact(totals["total_spend"], totals["contacts"])
            ),
        },
        "listings": list(listings_by_id.values()),
    }

    return report


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
            "updated_at": None,
        }

    if not is_requested_range_covered(
            coverage=coverage,
            date_from=date_from,
            date_to=date_to,
    ):
        status = (
            "error"
            if (
                    sync_state
                    and sync_state.status
                    == AvitoStatsSyncState.Status.ERROR
            )
            else "processing"
        )

        return {
            "status": status,
            "views": None,
            "contacts": None,
            "updated_at": None,
        }

    return {
        "status": "ready",
        "views": int(totals["views"]) if totals else 0,
        "contacts": int(totals["contacts"]) if totals else 0,
        "updated_at": serialize_datetime(
            totals["updated_at"]
            if totals
            else coverage.last_successful_at
        ),
    }


def is_requested_range_covered(
        *,
        coverage,
        date_from=None,
        date_to=None,
):
    if coverage is None:
        return False

    if (
            coverage.coverage_from is None
            or coverage.finalized_through is None
    ):
        return False

    # Таблица без фильтра показывает накопительные значения
    # за весь подтверждённый диапазон объявления.
    if date_from is None and date_to is None:
        return True

    # Selector должен получать либо обе границы, либо ни одной.
    if date_from is None or date_to is None:
        return False

    return (
            coverage.coverage_from <= date_from
            and coverage.finalized_through >= date_to
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
