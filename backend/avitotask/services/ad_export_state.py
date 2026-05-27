from django.utils import timezone
from avitotask.models import AdPublication, AvitoAccount


def mark_avito_accounts_export_dirty(avito_accounts):
    accounts_ids = normalize_account_ids(avito_accounts)

    if not accounts_ids:
        return

    AvitoAccount.objects.filter(id__in=accounts_ids).update(
        export_status=AvitoAccount.ExportStatus.DIRTY,
        export_requested_at=timezone.now(),
        export_error="",
    )


def mark_avito_accounts_export_queued(avito_accounts):
    accounts_ids = normalize_account_ids(avito_accounts)

    if not accounts_ids:
        return

    AvitoAccount.objects.filter(id__in=accounts_ids).update(
        export_status=AvitoAccount.ExportStatus.QUEUED,
        export_requested_at=timezone.now(),
        export_error="",
    )


def mark_publication_export_dirty(publication):
    mark_avito_accounts_export_dirty([publication.avito_account_id])


def mark_creative_publications_export_dirty(*, creative):
    accounts_ids = (
        AdPublication.objects
        .filter(workspace=creative.workspace, creative=creative)
        .values_list("avito_account_id", flat=True)
        .distinct()
    )

    mark_avito_accounts_export_dirty(accounts_ids)


def mark_avito_account_exporting(avito_account):
    AvitoAccount.objects.filter(id=avito_account.id).update(
        export_status=AvitoAccount.ExportStatus.EXPORTING,
        export_started_at=timezone.now(),
        export_error="",
    )


def mark_avito_account_export_clean(*, avito_account, file_path):
    AvitoAccount.objects.filter(id=avito_account.id).update(
        export_status=AvitoAccount.ExportStatus.CLEAN,
        export_file_path=str(file_path),
        last_exported_at=timezone.now(),
        export_error="",
    )


def mark_avito_account_export_error(*, avito_account, error):
    AvitoAccount.objects.filter(id=avito_account.id).update(
        export_status=AvitoAccount.ExportStatus.ERROR,
        export_error=str(error)
    )


def normalize_account_ids(avito_accounts):
    accounts_ids = []

    for account in avito_accounts:
        if isinstance(account, int):
            accounts_ids.append(account)
        else:
            accounts_ids.append(account.id)

    return accounts_ids
