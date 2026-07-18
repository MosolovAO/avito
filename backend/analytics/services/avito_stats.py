from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction

from analytics.models import AvitoListingDailyStats
from avitotask.models import AvitoListing, AvitoOAuthToken
from avitotask.services.avito_api import AvitoApiClient, AvitoApiError


@dataclass(frozen=True)
class AvitoStatsImportResult:
    total_listings: int
    total_days: int
    created_stats: int
    updated_stats: int


@transaction.atomic
def import_avito_listing_daily_stats_for_account(
        avito_account,
        date_from,
        date_to,
        listing_ids=None,
        session=None,
):
    if not avito_account.external_account_id:
        raise AvitoApiError("У AvitoAccount не заполнен external_account_id.")

    token = get_account_token(avito_account)
    listings = get_listings_for_stats(avito_account, listing_ids=listing_ids)

    if not listings:
        return AvitoStatsImportResult(
            total_listings=0,
            total_days=0,
            created_stats=0,
            updated_stats=0,
        )

    client = AvitoApiClient(session=session)
    listing_by_avito_id = {
        str(listing.avito_id): listing
        for listing in listings
    }

    total_days = 0
    created_stats = 0
    updated_stats = 0

    date_from = normalize_date(date_from)
    date_to = normalize_date(date_to)

    for listings_chunk in chunked(listings, 100):
        item_ids = [int(listing.avito_id) for listing in listings_chunk]

        stats_payload = client.get_item_stats(
            token=token,
            user_id=avito_account.external_account_id,
            item_ids=item_ids,
            date_from=date_from,
            date_to=date_to,
        )
        spend_payload = get_item_spending_payload(
            client=client,
            token=token,
            user_id=avito_account.external_account_id,
            item_ids=item_ids,
            date_from=date_from,
            date_to=date_to,
        )

        spending_by_item_and_date = build_spending_by_item_and_date(spend_payload)

        for item in stats_payload.get("result", {}).get("items", []):
            listing = listing_by_avito_id.get(str(item.get("itemId")))
            if listing is None:
                continue

            for stat in item.get("stats") or []:
                stat_date = date.fromisoformat(stat["date"])
                spending = spending_by_item_and_date.get((str(item.get("itemId")), stat_date))

                _, was_created = upsert_daily_stat(
                    listing=listing,
                    stat=stat,
                    total_spend=spending,
                )
                total_days += 1

                if was_created:
                    created_stats += 1
                else:
                    updated_stats += 1

    return AvitoStatsImportResult(
        total_listings=len(listings),
        total_days=total_days,
        created_stats=created_stats,
        updated_stats=updated_stats,
    )


def get_account_token(avito_account):
    try:
        return avito_account.oauth_tokens
    except AvitoOAuthToken.DoesNotExist as exc:
        raise AvitoApiError("У AvitoAccount нет подключенного OAuth-токена.") from exc


def get_listings_for_stats(avito_account, listing_ids=None):
    queryset = (
        AvitoListing.objects
        .filter(
            workspace=avito_account.workspace,
            avito_account=avito_account,
        )
        .exclude(avito_id="")
        .order_by("id")
    )

    if listing_ids is not None:
        queryset = queryset.filter(id__in=listing_ids)

    return list(queryset)


def get_item_spending_payload(client, token, user_id, item_ids, date_from, date_to):
    if not hasattr(client, "get_item_analytics"):
        return {}

    return client.get_item_analytics(
        token=token,
        user_id=user_id,
        item_ids=item_ids,
        date_from=date_from,
        date_to=date_to,
        metrics=["spending"],
    )


def build_spending_by_item_and_date(payload):
    result = {}

    for item in payload.get("result", {}).get("items", []):
        item_id = str(item.get("itemId"))

        for stat in item.get("stats") or []:
            stat_date = date.fromisoformat(stat["date"])
            spending = stat.get("spending")

            if spending is None:
                continue

            result[(item_id, stat_date)] = money_from_kopecks(spending)

    return result


def money_from_kopecks(value):
    return (Decimal(str(value)) / Decimal("100")).quantize(Decimal("0.01"))


def upsert_daily_stat(listing, stat, total_spend=None):
    stat_date = date.fromisoformat(stat["date"])
    raw_metrics = dict(stat)

    if total_spend is not None:
        raw_metrics["spending"] = int(total_spend * Decimal("100"))

    return AvitoListingDailyStats.objects.update_or_create(
        listing=listing,
        date=stat_date,
        defaults={
            "workspace": listing.workspace,
            "views": int(stat.get("uniqViews") or 0),
            "contacts": int(stat.get("uniqContacts") or 0),
            "favorites": int(stat.get("uniqFavorites") or 0),
            "calls": int(stat.get("calls") or 0),
            "messages": int(stat.get("messages") or 0),
            "total_spend": total_spend,
            "raw_metrics": raw_metrics,
        },
    )


def normalize_date(value):
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def chunked(items, size):
    for index in range(0, len(items), size):
        yield items[index:index + size]
