from decimal import Decimal

from analytics.models import AvitoListingDailyStats


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