from dataclasses import dataclass, field
from typing import Any

from django.db import transaction
from django.utils import timezone

from avitotask.models import AdPublication, AvitoAccount, AvitoListing

REJECTED_STATUSES = {
    "error",
    "failed",
    "rejected",
    "declined",
    "blocked",
}

ACCEPTED_STATUSES = {
    "ok",
    "success",
    "accepted",
    "published",
    "active",
}


@dataclass(frozen=True)
class NormalizedAutoloadReportRow:
    row_id: str
    avito_id: str
    status: str
    error_message: str
    raw_data: dict[str, Any]


@dataclass(frozen=True)
class AvitoAutoloadReportSyncResult:
    total_rows: int = 0
    accepted_rows: int = 0
    rejected_rows: int = 0
    linked_publications: int = 0
    updated_listings: int = 0
    created_listings: int = 0
    missing_row_id: int = 0
    missing_publications: int = 0
    conflicts: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)


@transaction.atomic
def sync_avito_autoload_report(
        *,
        workspace,
        avito_account: AvitoAccount,
        report_rows: list[dict[str, Any]],
) -> AvitoAutoloadReportSyncResult:
    """
    Синхронизирует результат автозагрузки Avito с нашими моделями.

    Главный ключ связи:
    - Id в CSV == AdPublication.row_id
    - Id в отчете Avito == row_id
    - AvitoId в отчете == AvitoListing.avito_id

    Функция намеренно принимает уже разобранные report_rows.
    Получение отчета из Avito API подключим отдельным слоем.
    """

    if avito_account.workspace_id != workspace.id:
        raise ValueError("AvitoAccount принадлежит другому workspace.")

    normalized_rows = [
        normalize_autoload_report_row(row)
        for row in report_rows
    ]

    row_ids = [
        row.row_id
        for row in normalized_rows
        if row.row_id
    ]

    publications_by_row_id = {
        publication.row_id: publication
        for publication in (
            AdPublication.objects
            .select_related("creative")
            .filter(
                workspace=workspace,
                avito_account=avito_account,
                row_id__in=row_ids,
            )
        )
    }

    total_rows = 0
    accepted_rows = 0
    rejected_rows = 0
    linked_publications = 0
    updated_listings = 0
    created_listings = 0
    missing_row_id = 0
    missing_publications = 0
    conflicts = 0
    errors = []

    for row in normalized_rows:
        total_rows += 1

        if not row.row_id:
            missing_row_id += 1
            errors.append(
                {
                    "reason": "missing_row_id",
                    "row": row.raw_data,
                }
            )
            continue

        publication = publications_by_row_id.get(row.row_id)

        if is_rejected_report_row(row):
            rejected_rows += 1

            if publication:
                mark_publication_autoload_error(
                    publication=publication,
                    row=row,
                )
            else:
                update_imported_listing_report_state(
                    workspace=workspace,
                    avito_account=avito_account,
                    row=row,
                )

            continue

        if not row.avito_id:
            errors.append(
                {
                    "reason": "missing_avito_id",
                    "row_id": row.row_id,
                    "row": row.raw_data,
                }
            )
            continue

        accepted_rows += 1

        if publication:
            listing, was_created = upsert_service_listing_from_publication(
                workspace=workspace,
                avito_account=avito_account,
                publication=publication,
                row=row,
            )

            if was_created:
                created_listings += 1
            else:
                updated_listings += 1

            linked_publications += 1
            clear_publication_autoload_error(publication)
            mark_publication_published(publication)
            continue

        listing_was_updated = update_imported_listing_report_state(
            workspace=workspace,
            avito_account=avito_account,
            row=row,
        )

        if listing_was_updated:
            updated_listings += 1
        else:
            missing_publications += 1
            errors.append(
                {
                    "reason": "missing_publication",
                    "row_id": row.row_id,
                    "avito_id": row.avito_id,
                    "row": row.raw_data,
                }
            )

    return AvitoAutoloadReportSyncResult(
        total_rows=total_rows,
        accepted_rows=accepted_rows,
        rejected_rows=rejected_rows,
        linked_publications=linked_publications,
        updated_listings=updated_listings,
        created_listings=created_listings,
        missing_row_id=missing_row_id,
        missing_publications=missing_publications,
        conflicts=conflicts,
        errors=errors,
    )


def normalize_autoload_report_row(row: dict[str, Any]) -> NormalizedAutoloadReportRow:
    row_id = pick_first_value(
        row,
        [
            "Id",
            "id",
            "ad_id",
            "adId",
            "row_id",
            "autoload_id",
        ],
    )

    avito_id = pick_first_value(
        row,
        [
            "AvitoId",
            "avito_id",
            "avitoId",
            "item_id",
            "itemId",
        ],
    )

    status = pick_first_value(
        row,
        [
            "status",
            "Status",
            "result",
            "state",
        ],
    )

    error_message = pick_first_value(
        row,
        [
            "error",
            "errors",
            "error_message",
            "message",
            "reason",
        ],
    )

    return NormalizedAutoloadReportRow(
        row_id=str(row_id or "").strip(),
        avito_id=str(avito_id or "").strip(),
        status=str(status or "").strip(),
        error_message=str(error_message or "").strip(),
        raw_data=row,
    )


def pick_first_value(row: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value

    return ""


def is_rejected_report_row(row: NormalizedAutoloadReportRow) -> bool:
    normalized_status = row.status.strip().lower()

    if normalized_status in REJECTED_STATUSES:
        return True

    return bool(row.error_message) and not row.avito_id


def upsert_service_listing_from_publication(
    *,
    workspace,
    avito_account: AvitoAccount,
    publication: AdPublication,
    row: NormalizedAutoloadReportRow,
):
    existing_listing = AvitoListing.objects.filter(
        workspace=workspace,
        avito_account=avito_account,
        publication=publication,
    ).first()

    if existing_listing is None:
        existing_listing = AvitoListing.objects.filter(
            workspace=workspace,
            avito_account=avito_account,
            avito_id=row.avito_id,
        ).first()

    defaults = build_listing_defaults_from_publication(
        publication=publication,
        row=row,
    )

    if existing_listing:
        existing_listing.publication = publication
        existing_listing.avito_id = row.avito_id
        existing_listing.source = AvitoListing.Source.SERVICE
        existing_listing.management_status = AvitoListing.ManagementStatus.MANAGED
        existing_listing.row_id = row.row_id
        existing_listing.status = defaults["status"]
        existing_listing.title = defaults["title"]
        existing_listing.description = defaults["description"]
        existing_listing.address = defaults["address"]
        existing_listing.image_urls = defaults["image_urls"]
        existing_listing.base_data = defaults["base_data"]
        existing_listing.option_data = defaults["option_data"]
        existing_listing.option_category = defaults["option_category"]
        existing_listing.imported_payload = defaults["imported_payload"]
        existing_listing.last_seen_at = defaults["last_seen_at"]
        existing_listing.save(
            update_fields=[
                "publication",
                "avito_id",
                "source",
                "option_category",
                "management_status",
                "row_id",
                "status",
                "title",
                "description",
                "address",
                "image_urls",
                "base_data",
                "option_data",
                "imported_payload",
                "last_seen_at",
                "updated_at",
            ]
        )
        return existing_listing, False

    listing = AvitoListing.objects.create(
        workspace=workspace,
        avito_account=avito_account,
        avito_id=row.avito_id,
        **defaults,
    )

    return listing, True


def build_listing_defaults_from_publication(
        *,
        publication: AdPublication,
        row: NormalizedAutoloadReportRow,
) -> dict[str, Any]:
    creative = publication.creative

    return {
        "publication": publication,
        "source": AvitoListing.Source.SERVICE,
        "management_status": AvitoListing.ManagementStatus.MANAGED,
        "desired_status": AvitoListing.DesiredStatus.PUBLISH,
        "row_id": row.row_id,
        "status": row.status or AdPublication.Status.ACTIVE,
        "title": creative.title,
        "option_category": creative.option_category,
        "description": creative.description,
        "address": publication.address,
        "image_urls": creative.image_urls or [],
        "base_data": creative.base_data or {},
        "option_data": creative.option_data or {},
        "imported_payload": {
            "autoload_report": row.raw_data,
        },
        "published_at": publication.published_at or timezone.now(),
        "last_seen_at": timezone.now(),
    }


def update_imported_listing_report_state(
        *,
        workspace,
        avito_account: AvitoAccount,
        row: NormalizedAutoloadReportRow,
) -> bool:
    queryset = AvitoListing.objects.filter(
        workspace=workspace,
        avito_account=avito_account,
        row_id=row.row_id,
    )

    if row.avito_id:
        queryset = queryset.filter(avito_id=row.avito_id)

    listing = queryset.first()

    if not listing:
        return False

    imported_payload = dict(listing.imported_payload or {})
    imported_payload["autoload_report"] = row.raw_data

    listing.status = row.status or listing.status
    listing.imported_payload = imported_payload
    listing.last_seen_at = timezone.now()
    listing.save(
        update_fields=[
            "status",
            "imported_payload",
            "last_seen_at",
            "updated_at",
        ]
    )

    return True


def mark_publication_autoload_error(
        *,
        publication: AdPublication,
        row: NormalizedAutoloadReportRow,
) -> None:
    address_data = dict(publication.address_data or {})
    address_data["autoload_error"] = {
        "status": row.status,
        "message": row.error_message,
        "raw": row.raw_data,
    }

    publication.status = AdPublication.Status.ERROR
    publication.address_data = address_data
    publication.save(
        update_fields=[
            "status",
            "address_data",
            "updated_at",
        ]
    )


def clear_publication_autoload_error(publication: AdPublication) -> None:
    address_data = dict(publication.address_data or {})

    if "autoload_error" not in address_data:
        return

    address_data.pop("autoload_error", None)
    publication.address_data = address_data
    publication.save(
        update_fields=[
            "address_data",
            "updated_at",
        ]
    )


def mark_publication_published(publication: AdPublication) -> None:
    update_fields = []

    if publication.status != AdPublication.Status.ACTIVE:
        publication.status = AdPublication.Status.ACTIVE
        update_fields.append("status")

    if publication.published_at is None:
        publication.published_at = timezone.now()
        update_fields.append("published_at")

    if update_fields:
        update_fields.append("updated_at")
        publication.save(update_fields=update_fields)
