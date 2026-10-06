import logging

from django.db.models import Q
from django.utils import timezone

import requests
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings

from avitotask.models import AvitoAccount
from avitotask.services.avito_api import AvitoApiError
from calls.models import CallSyncState
from calls.services import sync_calls_for_account

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    soft_time_limit=settings.AVITO_CALLS_SYNC_SOFT_TIME_LIMIT_SECONDS,
    time_limit=settings.AVITO_CALLS_SYNC_TIME_LIMIT_SECONDS,
)
def sync_calls_for_account_task(self, account_id):
    try:
        backfill_remaining = sync_calls_for_account(account_id)
    except SoftTimeLimitExceeded:
        CallSyncState.objects.filter(avito_account_id=account_id).update(
            last_error="Превышено максимальное время синхронизации звонков."
        )
        raise
    except AvitoApiError as exc:
        CallSyncState.objects.filter(avito_account_id=account_id).update(
            last_error=f"Ошибка Avito API (HTTP {exc.status_code or 'неизвестен'})."
        )

        retryable = (
                            isinstance(exc.status_code, int)
                            and 500 <= exc.status_code <= 599
                    ) or isinstance(
            exc.__cause__,
            (requests.Timeout, requests.ConnectionError),
        )

        if retryable:
            raise self.retry(
                exc=exc,
                countdown=self.default_retry_delay * (2 ** self.request.retries),
            )

        raise
    except Exception:
        CallSyncState.objects.filter(avito_account_id=account_id).update(
            last_error="Внутренняя ошибка синхронизации звонков."
        )
        raise

    if backfill_remaining:
        self.apply_async(args=(account_id,), countdown=60)

    return {"backfill_remaining": backfill_remaining}


@shared_task
def enqueue_calls_sync_task():
    queued = 0
    failed = 0
    account_ids = AvitoAccount.objects.filter(
        is_active=True,
        oauth_tokens__isnull=False,
    ).filter(
        Q(calls_sync_state__access_retry_at__isnull=True)
        | Q(calls_sync_state__access_retry_at__lte=timezone.now())
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
