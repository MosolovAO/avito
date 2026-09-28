import logging

from celery import shared_task

from avitotask.models import AvitoAccount
from avitotask.services.avito_api import AvitoApiError
from calls.models import CallSyncState
from calls.services import sync_calls_for_account

logger = logging.getLogger(__name__)


@shared_task
def sync_calls_for_account_task(account_id):
    try:
        backfill_remaining = sync_calls_for_account(account_id)
    except AvitoApiError as exc:
        CallSyncState.objects.filter(avito_account_id=account_id).update(
            last_error=f"Ошибка Avito API (HTTP {exc.status_code or 'неизвестен'})."
        )
        raise
    except Exception:
        CallSyncState.objects.filter(avito_account_id=account_id).update(
            last_error="Внутренняя ошибка синхронизации звонков."
        )
        raise

    if backfill_remaining:
        sync_calls_for_account_task.apply_async(
            args=(account_id,), countdown=60,
        )
    return {"backfill_remaining": backfill_remaining}


@shared_task
def enqueue_calls_sync_task():
    queued = 0
    failed = 0
    account_ids = AvitoAccount.objects.filter(
        is_active=True,
        oauth_tokens__isnull=False,
    ).order_by("id").values_list("id", flat=True)

    for account_id in account_ids.iterator():
        try:
            sync_calls_for_account_task.delay(account_id)
        except Exception:
            failed += 1
            logger.exception(
                "Не удалось поставить синхронизацию звонков в очередь: account_id=%s",
                account_id,
            )
        else:
            queued += 1

    return {"queued": queued, "failed": failed}
