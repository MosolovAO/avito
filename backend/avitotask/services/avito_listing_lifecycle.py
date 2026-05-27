from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from avitotask.models import AvitoListing


@dataclass(frozen=True)
class AvitoListingLifecycleItem:
    listing_id: int
    avito_id: str
    row_id: str
    title: str
    status: str
    desired_status: str
    date_end: str
    days_left: int | None
    action: str


@dataclass(frozen=True)
class AvitoListingLifecycleReport:
    total_checked: int
    expired: int
    expires_soon: int
    active_ok: int
    items: list[AvitoListingLifecycleItem]


def build_avito_listing_lifecycle_report(
    *,
    workspace,
    avito_account,
    soon_days=3,
) -> AvitoListingLifecycleReport:
    now = timezone.now()

    listings = (
        AvitoListing.objects
        .filter(
            workspace=workspace,
            avito_account=avito_account,
            source=AvitoListing.Source.AVITO_EXCEL,
            management_status=AvitoListing.ManagementStatus.MANAGED,
            desired_status=AvitoListing.DesiredStatus.PUBLISH,
        )
        .order_by("id")
    )

    items = []
    expired = 0
    expires_soon = 0
    active_ok = 0

    for listing in listings.iterator():
        date_end_raw = get_listing_date_end(listing)
        date_end = parse_avito_date_end(date_end_raw)

        if date_end is None:
            action = "unknown_date_end"
            days_left = None
        else:
            delta = date_end - now
            days_left = delta.days

            if delta.total_seconds() < 0:
                action = "expired"
                expired += 1
            elif delta <= timedelta(days=soon_days):
                action = "expires_soon"
                expires_soon += 1
            else:
                action = "active_ok"
                active_ok += 1

        items.append(
            AvitoListingLifecycleItem(
                listing_id=listing.id,
                avito_id=listing.avito_id,
                row_id=listing.row_id or "",
                title=listing.title or "",
                status=listing.status or "",
                desired_status=listing.desired_status,
                date_end=date_end_raw,
                days_left=days_left,
                action=action,
            )
        )

    return AvitoListingLifecycleReport(
        total_checked=len(items),
        expired=expired,
        expires_soon=expires_soon,
        active_ok=active_ok,
        items=items,
    )


def get_listing_date_end(listing):
    return (
        (listing.base_data or {}).get("DateEnd")
        or (listing.raw_data or {}).get("AvitoDateEnd")
        or ""
    )


def parse_avito_date_end(value):
    if not value:
        return None

    try:
        return timezone.datetime.fromisoformat(str(value))
    except ValueError:
        return None