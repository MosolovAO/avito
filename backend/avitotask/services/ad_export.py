import csv
import os
import tempfile
from pathlib import Path

from django.conf import settings
from django.utils.text import slugify

from avitotask.models import AdPublication

from avitotask.services.ad_export_state import (
    mark_avito_account_export_clean,
    mark_avito_account_export_error,
    mark_avito_account_exporting,
)

IMAGE_URLS_SEPARATOR = " | "
CSV_DELIMITER = ";"


def build_publication_export_row(publication):
    """
    Собирает итоговые данные одной публикации для будущего CSV.

    Приоритет:
    системные поля + creative.base_data + creative.option_data + publication.overrides.
    """

    publication = ensure_publication_relations(publication)
    creative = publication.creative

    row = {
        "Id": publication.row_id,
        "Title": creative.title,
        "Description": creative.description,
        "ImageUrls": IMAGE_URLS_SEPARATOR.join(creative.image_urls or []),
        "Address": publication.address
    }

    row.update(creative.base_data or {})
    row.update(creative.option_data or {})
    row.update(publication.overrides or {})

    return row


def export_avito_account_publications_to_csv(*,
                                             workspace,
                                             avito_account,
                                             output_dir=None
                                             ):
    if avito_account.workspace_id != workspace.id:
        raise ValueError("Аккаунт Avito принадлежит другому workspace")
    output_dir = Path(output_dir or settings.STATIC_ROOT)
    output_dir.mkdir(parents=True, exist_ok=True)

    mark_avito_account_exporting(avito_account)

    publications = get_publications_for_export(
        workspace=workspace,
        avito_account=avito_account,
    )

    rows = []
    fieldnames = []

    for publication in publications:
        row = build_publication_export_row(publication)
        rows.append(row)
        fieldnames = merge_fieldnames(fieldnames, row.keys())

    file_path = output_dir / build_export_file_name(avito_account)
    try:
        write_csv_atomic(file_path=file_path, fieldnames=fieldnames, rows=rows)
    except Exception as exc:
        mark_avito_account_export_error(avito_account=avito_account, error=exc)
        raise

    mark_avito_account_export_clean(avito_account=avito_account, file_path=file_path)

    return file_path


def get_publications_for_export(*, workspace, avito_account):
    return (
        AdPublication.objects
        .select_related("creative", "avito_account")
        .filter(
            workspace=workspace,
            avito_account=avito_account,
            status=AdPublication.Status.ACTIVE
        )
        .order_by("created_at", "id")
    )


def merge_fieldnames(current_fieldnames, new_fieldnames):
    result = list(current_fieldnames)

    for fieldname in new_fieldnames:
        if fieldname not in result:
            result.append(fieldname)

    return result


def build_export_file_name(avito_account):
    avito_slug = slugify(avito_account.name) or f"avito-account-{avito_account.id}"
    return f"{avito_slug}_avito_autoload.csv"


def write_csv_atomic(*, file_path, fieldnames, rows):
    fd, temp_path = tempfile.mkstemp(
        dir=str(file_path.parent),
        prefix=f".{file_path.name}.",
        suffix=".tmp"
    )

    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(
                csv_file,
                fieldnames=fieldnames,
                delimiter=CSV_DELIMITER,
                extrasaction="ignore"
            )
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temp_path, file_path)

    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


def ensure_publication_relations(publication):
    if isinstance(publication, AdPublication) and hasattr(publication, "_state"):
        if "creative" in publication._state.fields_cache:
            return publication

    return (
        AdPublication.objects
        .select_related("creative", "avito_account")
        .get(id=publication.id)
    )
