from django.utils import timezone
from avitotask.models import AdPublication, AvitoAccount
from django.db.models import Case, F, Value, When
from django.db import transaction


def mark_avito_accounts_export_dirty(
        avito_accounts,
) -> dict[int, int]:
    """
    Помечает аккаунты dirty и возвращает созданные export revisions.

    UPDATE блокирует изменяемые строки до завершения транзакции. Поэтому
    следующий SELECT видит именно созданные этим переходом revisions, а
    конкурентное изменение сможет продолжиться только после commit.
    """
    accounts_ids = set(normalize_account_ids(avito_accounts))

    if not accounts_ids:
        return {}

    with transaction.atomic():
        AvitoAccount.objects.filter(id__in=accounts_ids).update(
            export_status=AvitoAccount.ExportStatus.DIRTY,
            export_revision=F("export_revision") + 1,
            export_requested_at=timezone.now(),
            export_error="",
        )

        return dict(
            AvitoAccount.objects
            .filter(id__in=accounts_ids)
            .values_list("id", "export_revision")
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
        exporting_revision=F("export_revision"),
        export_started_at=timezone.now(),
        export_error="",
    )


def mark_avito_account_export_clean(*, avito_account, file_path):
    AvitoAccount.objects.filter(
        id=avito_account.id,
        exporting_revision__isnull=False,
    ).update(
        export_status=Case(
            When(
                export_revision=F("exporting_revision"),
                then=Value(AvitoAccount.ExportStatus.CLEAN),
            ),
            default=F("export_status"),
        ),
        export_file_path=str(file_path),
        last_exported_at=timezone.now(),
        last_exported_revision=F("exporting_revision"),
        exporting_revision=None,
        export_error="",
    )


def mark_avito_account_export_error(*, avito_account, error):
    AvitoAccount.objects.filter(
        id=avito_account.id,
        exporting_revision__isnull=False,
    ).update(
        export_status=AvitoAccount.ExportStatus.ERROR,
        exporting_revision=None,
        export_error=str(error),
    )


def normalize_account_ids(avito_accounts):
    accounts_ids = []

    for account in avito_accounts:
        if isinstance(account, int):
            accounts_ids.append(account)
        else:
            accounts_ids.append(account.id)

    return accounts_ids
