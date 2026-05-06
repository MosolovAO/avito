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


@dataclass(frozen=True)
class AvitoListingsImportResult:
    total_received: int
    created_listings: int
    updated_listings: int
    created_publications: int
    batch: AdBatch | None


@transaction.atomic
def import_avito_listings_for_account(avito_account, session=None):
    token = get_account_token(avito_account)
    client = AvitoApiClient(session=session)

    payload = client.get_items(token)
    resources = payload.get('resources') or []

    batch = None
    if resources:
        batch = AdBatch.objects.create(
            workspace=avito_account.workspace,
            source=AdBatch.Source.IMPORT,
            status=AdBatch.Status.COMPLETED,
            total_creatives=0,
            total_publications=0,
            completed_at=timezone.now()
        )

    created_listings = 0
    updated_listings = 0
    created_publications = 0

    for item in resources:
        listing, was_created = upsert_avito_listing(avito_account, item)
        if was_created:
            created_listings += 1
        else:
            updated_listings += 1

        if listing.publication_id is None:
            create_import_publication_for_listing(listing, item, batch)
            created_publications += 1

    if batch is not None:
        batch.total_creatives = created_publications
        batch.total_publications = created_publications
        batch.save(update_fields=["total_creatives", "total_publications"])

    return AvitoListingsImportResult(
        total_received=len(resources),
        created_listings=created_listings,
        updated_listings=updated_listings,
        created_publications=created_publications,
        batch=batch
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

    defaults = {
        "status": item.get('status') or "",
        "title": item.get('title') or "",
        "url": item.get('url') or "",
        "imported_payload": item,
        "last_seen_at": timezone.now()
    }
    return AvitoListing.objects.update_or_create(
        workspace=avito_account.workspace,
        avito_account=avito_account,
        avito_id=str(avito_id),
        defaults=defaults,
    )


def create_import_publication_for_listing(listing, item, batch):
    creative = AdCreative.objects.create(
        workspace=listing.workspace,
        batch=batch,
        source=AdCreative.Source.IMPORT,
        title=item.get("title") or f"Avito #{listing.avito_id}",
        description=item.get("description") or "",
        image_urls=[],
        base_data=build_import_base_data(item),
        option_data={},
        identity_hash=None,
    )

    publication = AdPublication.objects.create(
        workspace=listing.workspace,
        avito_account=listing.avito_account,
        creative=creative,
        batch=batch,
        source=AdPublication.Source.IMPORT,
        status=AdPublication.Status.DRAFT,
        row_id=None,
        address=item.get("address") or "",
        address_data={},
        overrides={},
    )

    listing.publication = publication
    listing.save(update_fields=["publication", "updated_at"])

    return publication


def build_import_base_data(item):
    base_data = {}

    if item.get("price") is not None:
        base_data["Price"] = item["price"]

    category = item.get("category") or {}
    if category.get("name"):
        base_data["Category"] = category["name"]

    if item.get("url"):
        base_data["AvitoUrl"] = item["url"]

    return base_data
