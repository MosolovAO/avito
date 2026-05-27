from dataclasses import dataclass, field
from typing import Any

from django.db import transaction

from avitotask.models import AvitoListing
from avitotask.services.avito_excel_import import (
    AvitoExcelColumn,
    CORE_COLUMN_MAP,
    build_row_preview,
    get_product_option_map,
    split_mapped_data,
)


@dataclass(frozen=True)
class AvitoListingRemapResult:
    total_checked: int = 0
    updated: int = 0
    skipped_without_raw_data: int = 0
    still_with_unmapped: int = 0
    resolved_columns: list[str] = field(default_factory=list)


def build_columns_from_listing(listing: AvitoListing) -> list[AvitoExcelColumn]:
    option_map = get_product_option_map()
    payload = listing.imported_payload or {}
    column_data = payload.get("column_data")

    if isinstance(column_data, list) and column_data:
        return [
            AvitoExcelColumn(
                ru_title=str(item.get("ru_title") or ""),
                technical_title=(
                        CORE_COLUMN_MAP.get(str(item.get("ru_title") or ""))
                        or option_map.get(str(item.get("ru_title") or ""))
                ),
                required=str(item.get("required") or ""),
                value_format=str(item.get("value_format") or ""),
            )
            for item in column_data
            if item.get("ru_title")
        ]

    return [
        AvitoExcelColumn(
            ru_title=ru_title,
            technical_title=CORE_COLUMN_MAP.get(ru_title) or option_map.get(ru_title),
            required="",
            value_format="",
        )
        for ru_title in listing.raw_data.keys()
    ]


def merge_without_overwriting_existing(
        current_data: dict[str, Any],
        remapped_data: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    next_data = dict(current_data or {})
    was_changed = False

    for key, value in remapped_data.items():
        if key in next_data:
            continue

        next_data[key] = value
        was_changed = True

    return next_data, was_changed


@transaction.atomic
def remap_imported_avito_listings(*, workspace, avito_account) -> AvitoListingRemapResult:
    if avito_account.workspace_id != workspace.id:
        raise ValueError("Avito-аккаунт не принадлежит текущему workspace.")

    queryset = (
        AvitoListing.objects
        .select_for_update()
        .filter(
            workspace=workspace,
            avito_account=avito_account,
            source=AvitoListing.Source.AVITO_EXCEL,
        )
        .only(
            "id",
            "sheet_name",
            "category_path",
            "raw_data",
            "base_data",
            "option_data",
            "unmapped_data",
            "imported_payload",
        )
    )

    total_checked = 0
    updated = 0
    skipped_without_raw_data = 0
    still_with_unmapped = 0
    resolved_columns = set()

    for listing in queryset.iterator(chunk_size=500):
        total_checked += 1

        raw_data = listing.raw_data
        if not isinstance(raw_data, dict) or not raw_data:
            skipped_without_raw_data += 1
            continue

        previous_unmapped_columns = set((listing.unmapped_data or {}).keys())

        row_preview = build_row_preview(
            sheet_name=listing.sheet_name,
            category_path=listing.category_path,
            row_number=0,
            raw_data=raw_data,
            columns=build_columns_from_listing(listing),
        )

        _, remapped_base_data, remapped_option_data = split_mapped_data(
            row_preview.mapped_data,
        )

        next_base_data, base_changed = merge_without_overwriting_existing(
            listing.base_data,
            remapped_base_data,
        )
        next_option_data, option_changed = merge_without_overwriting_existing(
            listing.option_data,
            remapped_option_data,
        )

        next_unmapped_data = row_preview.unmapped_data
        unmapped_changed = next_unmapped_data != (listing.unmapped_data or {})

        if next_unmapped_data:
            still_with_unmapped += 1

        resolved_columns.update(previous_unmapped_columns - set(next_unmapped_data.keys()))

        if not base_changed and not option_changed and not unmapped_changed:
            continue

        imported_payload = dict(listing.imported_payload or {})
        imported_payload["remapped_data"] = {
            "mapped_data": row_preview.mapped_data,
            "unmapped_data": row_preview.unmapped_data,
        }

        listing.base_data = next_base_data
        listing.option_data = next_option_data
        listing.unmapped_data = next_unmapped_data
        listing.imported_payload = imported_payload
        listing.save(
            update_fields=[
                "base_data",
                "option_data",
                "unmapped_data",
                "imported_payload",
                "updated_at",
            ],
        )
        updated += 1

    return AvitoListingRemapResult(
        total_checked=total_checked,
        updated=updated,
        skipped_without_raw_data=skipped_without_raw_data,
        still_with_unmapped=still_with_unmapped,
        resolved_columns=sorted(resolved_columns),
    )
