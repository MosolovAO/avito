from django.db import transaction

from avitotask.models import AvitoAccount
from avitotask.services.ad_export_state import mark_avito_accounts_export_queued


def queue_avito_account_csv_exports(avito_account_ids):
    account_ids = list(
        AvitoAccount.objects
        .filter(id__in=list(avito_account_ids), is_active=True)
        .order_by("id")
        .values_list("id", flat=True)
    )

    if not account_ids:
        return "none"

    def enqueue_exports():
        from avitotask.tasks import export_avito_account_csv_task

        mark_avito_accounts_export_queued(account_ids)

        for account_id in account_ids:
            export_avito_account_csv_task.delay(account_id)

    transaction.on_commit(enqueue_exports)

    return "queued"

