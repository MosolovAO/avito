from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from avitotask.models import AvitoAccount


def get_avito_sync_stale_timeout_minutes() -> int:
    return int(
        getattr(settings, "AVITO_SYNC_STALE_TIMEOUT_MINUTES", 30)
        or 30
    )


def is_avito_account_sync_stale(avito_account: AvitoAccount) -> bool:
    if avito_account.sync_status != AvitoAccount.SyncStatus.SYNCING:
        return False

    if not avito_account.sync_started_at:
        return True

    stale_after = timedelta(minutes=get_avito_sync_stale_timeout_minutes())

    return timezone.now() - avito_account.sync_started_at > stale_after
