from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from avitotask.models import AdPublication, AvitoAccount, AvitoListing, AvitoOAuthToken
from avitotask.services.avito_api import AvitoApiClient, AvitoApiError


@dataclass(frozen=True)
class AvitoAutoloadLinkResult:
    total_requested: int
    linked: int
    missing: int
    conflicts: int
    created_listings: int
    updated_listings: int


@transaction.atomic
def link_publications_to_avito_ids_for_account(avito_account, row_ids=None, session=None):
    token = get_account_token(avito_account)
    publications = get_publications_for_avito_id_linking(avito_account, row_ids=row_ids)

    row_id_to_publication = {
        publication.row_id: publication
        for publication in publications
        if publication.row_id
    }

    if not row_id_to_publication:
        return AvitoAutoloadLinkResult(
            total_requested=0,
            linked=0,
            missing=0,
            conflicts=0,
            created_listings=0,
            updated_listings=0,
        )
    client = AvitoApiClient(session=session)
    payload = client.get_avito_ids_by_ad_ids(token, list(row_id_to_publication.keys()))

    linked = 0
    missing = 0
    conflicts = 0
    created_listings = 0
    updated_listings = 0

    for item in payload.get("items") or []:
        row_id = item.get("ad_id")
        avito_id = item.get("avito_id")
        publication = row_id_to_publication.get(row_id)

        if publication is None:
            continue

        if not avito_id:
            missing += 1
            continue

        listing, was_created = upsert_listing_for_publication(
            publication=publication,
            avito_id=avito_id,
            payload=item
        )

        if listing.publication_id and listing.publication_id != publication.id:
            conflicts += 1
            continue

        if listing.publication_id is None:
            listing.publication = publication
            listing.save(update_fields=["publication", "updated_at"])

        linked += 1

        if was_created:
            created_listings += 1
        else:
            updated_listings += 1

    return AvitoAutoloadLinkResult(
        total_requested=len(row_id_to_publication),
        linked=linked,
        missing=missing,
        conflicts=conflicts,
        created_listings=created_listings,
        updated_listings=updated_listings,
    )


def get_account_token(avito_account):
    try:
        return avito_account.oauth_tokens
    except AvitoOAuthToken.DoesNotExist as exc:
        raise AvitoApiError("У AvitoAccount нет подключенного OAuth-токена.") from exc


def get_publications_for_avito_id_linking(avito_account, row_ids=None):
    queryset = (
        AdPublication.objects
        .select_related("creative", "avito_account")
        .filter(
            workspace=avito_account.workspace,
            avito_account=avito_account,
            row_id__isnull=False
        )
        .exclude(row_id="")
        .exclude(status=AdPublication.Status.ARCHIVED)
        .order_by("id")
    )

    if row_ids is not None:
        queryset = queryset.filter(row_id__in=row_ids)

    return list(queryset)


def upsert_listing_for_publication(publication, avito_id, payload):
    return AvitoListing.objects.update_or_create(
        workspace=publication.workspace,
        avito_account=publication.avito_account,
        avito_id=str(avito_id),
        defaults={
            "status": "published",
            "title": publication.creative.title,
            "imported_payload": payload,
            "last_seen_at": timezone.now()
        }
    )
