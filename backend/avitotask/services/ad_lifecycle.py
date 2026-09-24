from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from avitotask.models import AdPublication, AvitoListing
from avitotask.services.ad_editing import AdEditingError
from avitotask.services.ad_export_state import mark_avito_accounts_export_dirty
from avitotask.services.ad_publication_dates import (
    PUBLICATION_EXTENSION_DAYS,
    extend_date_end,
    get_publication_effective_date_end,
    set_legacy_date_end,
    sync_linked_listings_published_end,
)

ENTITY_TYPE_AVITO_LISTING = "avito_listing"
ENTITY_TYPE_AD_PUBLICATION = "ad_publication"

ACTION_PUBLISH = "publish"
ACTION_PAUSE = "pause"
ACTION_DELETE = "delete"
ACTION_EXTEND = "extend"

PUBLICATION_STATUS_BY_ACTION = {
    ACTION_PUBLISH: AdPublication.Status.ACTIVE,
    ACTION_PAUSE: AdPublication.Status.PAUSED,
    ACTION_DELETE: AdPublication.Status.ARCHIVED,
}

LISTING_DESIRED_STATUS_BY_ACTION = {
    ACTION_PUBLISH: AvitoListing.DesiredStatus.PUBLISH,
    ACTION_PAUSE: AvitoListing.DesiredStatus.PAUSE,
    ACTION_DELETE: AvitoListing.DesiredStatus.ARCHIVE,
}

ACTIONS_STOPPING_ACTIVITY = {
    ACTION_PAUSE,
    ACTION_DELETE,
}


def bulk_update_ads_lifecycle(*, workspace, avito_account, items, action):
    """
    Единая операция управления трансляцией объявлений.

    Для публикаций меняет AdPublication.status.
    Для импортированных XLSX Avito-объявлений меняет AvitoListing.desired_status.
    Для service AvitoListing со связанной публикацией управляет именно публикацией,
    потому что CSV-экспорт service-объявлений идет через AdPublication.
    """

    if avito_account.workspace_id != workspace.id:
        raise AdEditingError("Аккаунт Avito принадлежит другому workspace.")

    if action not in {*PUBLICATION_STATUS_BY_ACTION, ACTION_EXTEND}:
        raise AdEditingError("Некорректное действие.")

    publication_ids = {
        item["id"]
        for item in items
        if item["entity_type"] == ENTITY_TYPE_AD_PUBLICATION
    }
    listing_ids = {
        item["id"]
        for item in items
        if item["entity_type"] == ENTITY_TYPE_AVITO_LISTING
    }

    with transaction.atomic():
        listing_split = split_listing_lifecycle_targets(
            workspace=workspace,
            avito_account=avito_account,
            listing_ids=listing_ids,
        )

        publication_ids.update(listing_split["publication_ids"])

        if action == ACTION_EXTEND:
            publication_result = extend_publications_date_end(
                workspace=workspace,
                avito_account=avito_account,
                publication_ids=publication_ids,
            )
            listing_result = extend_imported_listings_date_end(
                workspace=workspace,
                avito_account=avito_account,
                listing_ids=listing_split["imported_listing_ids"],
            )
        else:
            publication_result = update_publications_lifecycle(
                workspace=workspace,
                avito_account=avito_account,
                publication_ids=publication_ids,
                action=action,
            )
            listing_result = update_imported_listings_lifecycle(
                workspace=workspace,
                avito_account=avito_account,
                listing_ids=listing_split["imported_listing_ids"],
                action=action,
            )

        updated = (
                publication_result["updated"]
                + listing_result["updated"]
        )
        required_export_revision = None

        if updated:
            revisions = mark_avito_accounts_export_dirty(
                [avito_account.id],
            )
            required_export_revision = revisions.get(
                avito_account.id,
            )

    return {
        "action": action,
        "requested": len(items),
        "updated": updated,
        "required_export_revision": required_export_revision,
        "publications": publication_result,
        "listings": {
            **listing_result,
            "requested": len(listing_ids),
            "matched": listing_split["matched"],
            "missing": listing_split["missing"],
            "unsupported": (
                    listing_split["unsupported"]
                    + listing_result["unsupported"]
            ),
            "redirected_to_publications": listing_split["redirected_to_publications"],
        },
    }


def split_listing_lifecycle_targets(*, workspace, avito_account, listing_ids):
    if not listing_ids:
        return {
            "imported_listing_ids": set(),
            "publication_ids": set(),
            "matched": 0,
            "missing": 0,
            "unsupported": 0,
            "redirected_to_publications": 0,
        }

    listings = list(
        AvitoListing.objects
        .select_related("publication")
        .filter(
            workspace=workspace,
            avito_account=avito_account,
            id__in=listing_ids,
        )
    )

    imported_listing_ids = set()
    publication_ids = set()
    unsupported = 0
    redirected_to_publications = 0

    for listing in listings:
        if listing.source == AvitoListing.Source.AVITO_EXCEL:
            imported_listing_ids.add(listing.id)
            continue

        if listing.source == AvitoListing.Source.SERVICE and listing.publication_id:
            publication_ids.add(listing.publication_id)
            redirected_to_publications += 1
            continue

        unsupported += 1

    return {
        "imported_listing_ids": imported_listing_ids,
        "publication_ids": publication_ids,
        "matched": len(listings),
        "missing": len(listing_ids) - len(listings),
        "unsupported": unsupported,
        "redirected_to_publications": redirected_to_publications,
    }


def update_publications_lifecycle(
        *,
        workspace,
        avito_account,
        publication_ids,
        action,
):
    if not publication_ids:
        return {
            "requested": 0,
            "matched": 0,
            "updated": 0,
            "missing": 0,
        }

    status = PUBLICATION_STATUS_BY_ACTION[action]
    now = timezone.now()

    stops_activity = action in ACTIONS_STOPPING_ACTIVITY

    linked_listings = []

    if stops_activity:
        linked_listings = list(
            AvitoListing.objects
            .select_for_update(of=("self",))
            .filter(
                workspace=workspace,
                avito_account=avito_account,
                publication_id__in=publication_ids,
                publication__workspace=workspace,
                publication__avito_account=avito_account,
                source=AvitoListing.Source.SERVICE,
            )
            .order_by("id")
        )

    publications = list(
        AdPublication.objects
        .select_for_update()
        .select_related("creative")
        .filter(
            workspace=workspace,
            avito_account=avito_account,
            id__in=publication_ids,
        )
        .order_by("id")
    )
    matched = len(publications)

    for publication in publications:
        publication.status = status
        publication.updated_at = now

        if action == ACTION_PUBLISH:
            ensure_publication_has_active_date_end(publication)

    if publications:
        AdPublication.objects.bulk_update(
            publications,
            [
                "status",
                "published_end",
                "published_end_source",
                "overrides",
                "updated_at",
            ],
        )

        if stops_activity and linked_listings:
            matched_publication_ids = {
                publication.id
                for publication in publications
            }
            stopped_listings = [
                listing
                for listing in linked_listings
                if listing.publication_id in matched_publication_ids
            ]

            for listing in stopped_listings:
                listing.active_since = None
                listing.updated_at = now

            if stopped_listings:
                AvitoListing.objects.bulk_update(
                    stopped_listings,
                    [
                        "active_since",
                        "updated_at",
                    ],
                )

        if action == ACTION_PUBLISH:
            sync_linked_listings_published_end(publications)

    return {
        "requested": len(publication_ids),
        "matched": matched,
        "updated": matched,
        "missing": len(publication_ids) - matched,
    }


def update_imported_listings_lifecycle(
        *,
        workspace,
        avito_account,
        listing_ids,
        action,
):
    if not listing_ids:
        return {
            "matched": 0,
            "updated": 0,
            "unsupported": 0,
        }

    desired_status = LISTING_DESIRED_STATUS_BY_ACTION[action]
    now = timezone.now()

    stops_activity = action in ACTIONS_STOPPING_ACTIVITY

    listings = list(
        AvitoListing.objects
        .select_for_update()
        .filter(
            workspace=workspace,
            avito_account=avito_account,
            id__in=listing_ids,
            source=AvitoListing.Source.AVITO_EXCEL,
        )
        .order_by("id")
    )

    for listing in listings:
        listing.desired_status = desired_status

        if stops_activity:
            listing.active_since = None

        listing.updated_at = now

        if action == ACTION_PUBLISH:
            listing.management_status = (
                AvitoListing.ManagementStatus.MANAGED
            )
            ensure_listing_has_active_date_end(listing)

    update_fields = [
        "desired_status",
        "published_end",
        "base_data",
        "updated_at",
    ]

    if stops_activity:
        update_fields.append("active_since")

    if action == ACTION_PUBLISH:
        update_fields.append("management_status")

    if listings:
        AvitoListing.objects.bulk_update(
            listings,
            update_fields,
        )

    return {
        "matched": len(listings),
        "updated": len(listings),
        "unsupported": 0,
    }


def extend_publications_date_end(
        *,
        workspace,
        avito_account,
        publication_ids,
):
    if not publication_ids:
        return {
            "requested": 0,
            "matched": 0,
            "updated": 0,
            "missing": 0,
        }

    publications = list(
        AdPublication.objects
        .select_for_update()
        .select_related("creative")
        .filter(
            workspace=workspace,
            avito_account=avito_account,
            id__in=publication_ids,
        )
    )
    now = timezone.now()

    for publication in publications:
        next_published_end = extend_date_end(
            get_publication_effective_date_end(publication),
        )

        publication.published_end = next_published_end
        publication.published_end_source = (
            AdPublication.PublishedEndSource.PUBLICATION
        )
        publication.overrides = set_legacy_date_end(
            publication.overrides,
            next_published_end,
        )
        publication.updated_at = now

    if publications:
        AdPublication.objects.bulk_update(
            publications,
            [
                "published_end",
                "published_end_source",
                "overrides",
                "updated_at",
            ],
        )
        sync_linked_listings_published_end(publications)

    return {
        "requested": len(publication_ids),
        "matched": len(publications),
        "updated": len(publications),
        "missing": len(publication_ids) - len(publications),
    }


def extend_imported_listings_date_end(
        *,
        workspace,
        avito_account,
        listing_ids,
):
    if not listing_ids:
        return {
            "matched": 0,
            "updated": 0,
            "unsupported": 0,
        }

    listings = list(
        AvitoListing.objects
        .select_for_update()
        .filter(
            workspace=workspace,
            avito_account=avito_account,
            id__in=listing_ids,
            source=AvitoListing.Source.AVITO_EXCEL,
        )
    )
    extendable_listings = [
        listing
        for listing in listings
        if listing.management_status in {
            AvitoListing.ManagementStatus.MANAGED,
            AvitoListing.ManagementStatus.OUT_OF_SYNC,
        }
    ]
    now = timezone.now()

    for listing in extendable_listings:
        next_published_end = extend_date_end(
            listing.published_end,
        )

        listing.published_end = next_published_end
        listing.base_data = set_legacy_date_end(
            listing.base_data,
            next_published_end,
        )

    if extendable_listings:
        AvitoListing.objects.bulk_update(
            extendable_listings,
            [
                "published_end",
                "base_data",
                "desired_status",
                "updated_at",
            ],
        )

    return {
        "matched": len(listings),
        "updated": len(extendable_listings),
        "unsupported": len(listings) - len(extendable_listings),
    }


def ensure_publication_has_active_date_end(publication):
    current_published_end = get_publication_effective_date_end(
        publication,
    )

    if (
            current_published_end
            and current_published_end >= timezone.localdate()
    ):
        return

    next_published_end = build_next_active_date_end()

    publication.published_end = next_published_end
    publication.published_end_source = (
        AdPublication.PublishedEndSource.PUBLICATION
    )
    publication.overrides = set_legacy_date_end(
        publication.overrides,
        next_published_end,
    )


def ensure_listing_has_active_date_end(listing):
    current_published_end = listing.published_end

    if (
            current_published_end is None
            or current_published_end < timezone.localdate()
    ):
        current_published_end = build_next_active_date_end()

    listing.published_end = current_published_end
    listing.base_data = set_legacy_date_end(
        listing.base_data,
        current_published_end,
    )


def build_next_active_date_end():
    return (
            timezone.localdate()
            + timedelta(days=PUBLICATION_EXTENSION_DAYS)
    )
