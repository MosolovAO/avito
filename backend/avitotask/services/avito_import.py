from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from avitotask.models import (
    AdBatch,
    AdCreative,
    AdPublication,
    AvitoAccount,
    AvitoListing,
    AvitoOAuthToken,
)
from avitotask.services.avito_api import AvitoApiClient, AvitoApiError

AVITO_ITEMS_PER_PAGE = 100
AVITO_ITEMS_MAX_PAGES = 100


@dataclass(frozen=True)
class AvitoListingsImportResult:
    total_received: int
    created_listings: int
    updated_listings: int
    out_of_sync_listings: int
    seen_avito_ids: list[str]
    batch: AdBatch | None


@transaction.atomic
def import_avito_listings_for_account(avito_account, session=None):
    token = get_account_token(avito_account)
    client = AvitoApiClient(session=session)

    payload = client.get_items(token)
    resources = payload.get('resources') or []

    batch = AdBatch.objects.create(
        workspace=avito_account.workspace,
        source=AdBatch.Source.IMPORT,
        status=AdBatch.Status.DRAFT,
        total_creatives=0,
        total_publications=0,
    )

    created_listings = 0
    updated_listings = 0
    total_received = 0

    seen_avito_ids = set()

    for payload, resources in client.iter_items(
            token,
            per_page=AVITO_ITEMS_PER_PAGE,
            max_pages=AVITO_ITEMS_MAX_PAGES,
    ):
        total_received += len(resources)

        for item in resources:
            avito_id = item.get("id")
            if avito_id:
                seen_avito_ids.add(str(avito_id))

            listing, was_created = upsert_avito_listing(avito_account, item)
            if was_created:
                created_listings += 1
            else:
                updated_listings += 1

    if total_received == 0:
        batch.delete()
        batch = None
    else:
        batch.status = AdBatch.Status.COMPLETED
        batch.total_creatives = 0
        batch.total_publications = 0
        batch.completed_at = timezone.now()
        batch.save(
            update_fields=[
                "status",
                "total_creatives",
                "total_publications",
                "completed_at",
            ]
        )

    out_of_sync_listings = mark_managed_excel_listings_out_of_sync(
        avito_account,
        seen_avito_ids,
    )

    return AvitoListingsImportResult(
        total_received=total_received,
        created_listings=created_listings,
        updated_listings=updated_listings,
        out_of_sync_listings=out_of_sync_listings,
        seen_avito_ids=sorted(seen_avito_ids),
        batch=batch,
    )


def get_account_token(avito_account):
    try:
        return avito_account.oauth_tokens
    except AvitoOAuthToken.DoesNotExist as exc:
        raise AvitoApiError("У AvitoAccount нет подключенного OAuth-токена.") from exc


def upsert_avito_listing(avito_account, item):
    avito_id = item.get('id')

    if not avito_id:
        raise AvitoApiError("Avito API вернул объявление без id.", payload=item)

    listing = AvitoListing.objects.filter(
        workspace=avito_account.workspace,
        avito_account=avito_account,
        avito_id=str(avito_id),
    ).first()

    if listing and listing.source == AvitoListing.Source.AVITO_EXCEL:
        return update_managed_excel_listing_from_api(listing, item), False

    defaults = {
        "source": AvitoListing.Source.API,
        "management_status": AvitoListing.ManagementStatus.OBSERVED,
        "status": item.get('status') or "",
        "title": item.get('title') or "",
        "url": item.get('url') or "",
        "imported_payload": item,
        "last_seen_at": timezone.now(),
    }

    return AvitoListing.objects.update_or_create(
        workspace=avito_account.workspace,
        avito_account=avito_account,
        avito_id=str(avito_id),
        defaults=defaults,
    )


def update_managed_excel_listing_from_api(listing, item):
    """
    API /core/v1/items возвращает неполную карточку.

    Для source=avito_excel не перетираем title/description/base_data/option_data,
    потому что источник истины - данные, импортированные из XLSX и измененные в сервисе.
    Обновляем только наблюдаемые поля: статус, URL, last_seen_at и сырой API payload.
    """

    update_fields = []

    api_status = item.get("status")
    if api_status is not None:
        listing.status = api_status or ""
        update_fields.append("status")

    api_url = item.get("url")
    if api_url is not None:
        listing.url = api_url or ""
        update_fields.append("url")

    listing.imported_payload = merge_imported_payload(
        listing.imported_payload,
        source="api",
        payload=item,
    )
    listing.last_seen_at = timezone.now()
    update_fields.extend(["imported_payload", "last_seen_at", "updated_at"])

    listing.save(update_fields=update_fields)

    return listing


def merge_imported_payload(current_payload, *, source, payload):
    result = dict(current_payload or {})
    result[source] = payload
    return result


def mark_managed_excel_listings_out_of_sync(avito_account, seen_avito_ids):
    queryset = AvitoListing.objects.filter(
        workspace=avito_account.workspace,
        avito_account=avito_account,
        source=AvitoListing.Source.AVITO_EXCEL,
        management_status=AvitoListing.ManagementStatus.MANAGED,
    )

    if seen_avito_ids:
        queryset = queryset.exclude(avito_id__in=seen_avito_ids)

    return queryset.update(
        management_status=AvitoListing.ManagementStatus.OUT_OF_SYNC,
        last_seen_at=timezone.now(),
    )
