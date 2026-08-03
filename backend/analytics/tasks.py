import logging
import uuid
from datetime import timedelta
import requests
from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from analytics.models import AvitoStatsSyncState
from analytics.services.avito_stats import (
    build_avito_stats_backfill_plan,
    import_avito_listing_daily_stats_for_account,
    import_avito_profile_daily_stats_for_account,
    normalize_date,
    resolve_stats_sync_range,
)
from avitotask.models import AvitoAccount
from avitotask.services.avito_api import (
    AvitoApiError,
    AvitoConfigurationError,
)

AVITO_STATS_TASK_MAX_RETRIES = 3
AVITO_STATS_TASK_RETRY_BASE_SECONDS = 60
AVITO_STATS_TASK_RETRY_MAX_SECONDS = 15 * 60

logger = logging.getLogger(__name__)


def enqueue_avito_stats_sync(
        *,
        avito_account,
        date_from=None,
        date_to=None,
        listing_ids=None,
):
    now = timezone.now()
    today = timezone.localdate()

    with transaction.atomic():
        AvitoStatsSyncState.objects.get_or_create(
            workspace=avito_account.workspace,
            avito_account=avito_account,
        )

        sync_state = (
            AvitoStatsSyncState.objects
            .select_for_update()
            .get(avito_account=avito_account)
        )

        resolved_from, resolved_to = resolve_stats_sync_range(
            sync_state=sync_state,
            today=today,
            date_from=date_from,
            date_to=date_to,
        )

        if is_active_sync(sync_state, now=now):
            return {
                "sync_state": sync_state,
                "task_id": None,
                "queued": False,
                "date_from": resolved_from,
                "date_to": resolved_to,
            }

        run_id = uuid.uuid4()

        sync_state.status = AvitoStatsSyncState.Status.QUEUED
        sync_state.run_id = run_id
        sync_state.heartbeat_at = None
        sync_state.requested_date_from = resolved_from
        sync_state.requested_date_to = resolved_to
        sync_state.requested_at = now
        sync_state.started_at = None
        sync_state.finished_at = None
        sync_state.error = ""
        sync_state.save(
            update_fields=[
                "status",
                "run_id",
                "heartbeat_at",
                "requested_date_from",
                "requested_date_to",
                "requested_at",
                "started_at",
                "finished_at",
                "error",
                "updated_at",
            ]
        )

    try:
        async_result = import_avito_account_daily_stats_task.delay(
            avito_account.id,
            resolved_from.isoformat(),
            resolved_to.isoformat(),
            listing_ids,
            str(run_id),
        )
    except Exception as exc:
        mark_sync_error(
            avito_account_id=avito_account.id,
            error=str(exc),
            run_id=run_id,
        )
        raise

    return {
        "sync_state": sync_state,
        "task_id": async_result.id,
        "queued": True,
        "date_from": resolved_from,
        "date_to": resolved_to,
    }


def enqueue_avito_profile_daily_sync(
        *,
        avito_account,
        stat_date,
):
    now = timezone.now()
    stat_date = normalize_date(stat_date)

    with transaction.atomic():
        AvitoStatsSyncState.objects.get_or_create(
            workspace=avito_account.workspace,
            avito_account=avito_account,
        )

        sync_state = (
            AvitoStatsSyncState.objects
            .select_for_update()
            .get(avito_account=avito_account)
        )

        if is_active_sync(sync_state, now=now):
            return {
                "sync_state": sync_state,
                "task_id": None,
                "queued": False,
                "date_from": stat_date,
                "date_to": stat_date,
            }

        run_id = uuid.uuid4()

        sync_state.status = AvitoStatsSyncState.Status.QUEUED
        sync_state.run_id = run_id
        sync_state.heartbeat_at = None
        sync_state.requested_date_from = stat_date
        sync_state.requested_date_to = stat_date
        sync_state.requested_at = now
        sync_state.started_at = None
        sync_state.finished_at = None
        sync_state.error = ""
        sync_state.save(
            update_fields=[
                "status",
                "run_id",
                "heartbeat_at",
                "requested_date_from",
                "requested_date_to",
                "requested_at",
                "started_at",
                "finished_at",
                "error",
                "updated_at",
            ]
        )

    try:
        async_result = (
            import_avito_account_profile_daily_stats_task.delay(
                avito_account.id,
                stat_date.isoformat(),
                str(run_id),
            )
        )

    except Exception as exc:
        mark_sync_error(
            avito_account_id=avito_account.id,
            error=str(exc),
            run_id=run_id,
        )

        raise

    return {
        "sync_state": sync_state,
        "task_id": async_result.id,
        "queued": True,
        "date_from": stat_date,
        "date_to": stat_date,
    }


def enqueue_avito_stats_backfill(
        *,
        avito_account,
        target_date,
):
    """
    Ставит исторический stats/v1 backfill в отдельную очередь.

    target_date — уже загруженный через stats/v2 завершённый день.
    Исторический план будет строиться до target_date - 1.
    """

    now = timezone.now()
    target_date = normalize_date(target_date)

    with transaction.atomic():
        AvitoStatsSyncState.objects.get_or_create(
            workspace=avito_account.workspace,
            avito_account=avito_account,
        )

        sync_state = (
            AvitoStatsSyncState.objects
            .select_for_update()
            .get(avito_account=avito_account)
        )

        if is_active_sync(sync_state, now=now):
            return {
                "sync_state": sync_state,
                "task_id": None,
                "queued": False,
                "date_from": target_date,
                "date_to": target_date,
            }

        run_id = uuid.uuid4()

        sync_state.status = AvitoStatsSyncState.Status.QUEUED
        sync_state.run_id = run_id
        sync_state.heartbeat_at = None
        sync_state.requested_date_from = target_date
        sync_state.requested_date_to = target_date
        sync_state.requested_at = now
        sync_state.started_at = None
        sync_state.finished_at = None
        sync_state.error = ""
        sync_state.save(
            update_fields=[
                "status",
                "run_id",
                "heartbeat_at",
                "requested_date_from",
                "requested_date_to",
                "requested_at",
                "started_at",
                "finished_at",
                "error",
                "updated_at",
            ]
        )

    try:
        async_result = (
            backfill_missing_avito_listing_stats_task.delay(
                avito_account.id,
                target_date.isoformat(),
                str(run_id),
            )
        )
    except Exception as exc:
        mark_sync_error(
            avito_account_id=avito_account.id,
            error=str(exc),
            run_id=run_id,
        )
        raise

    return {
        "sync_state": sync_state,
        "task_id": async_result.id,
        "queued": True,
        "date_from": target_date,
        "date_to": target_date,
    }


@shared_task(
    bind=True,
    max_retries=AVITO_STATS_TASK_MAX_RETRIES,
)
def import_avito_account_daily_stats_task(
        self,
        avito_account_id,
        date_from,
        date_to,
        listing_ids=None,
        run_id=None,
):
    avito_account = (
        AvitoAccount.objects
        .select_related("workspace")
        .get(id=avito_account_id)
    )

    if not claim_sync(
            avito_account,
            run_id=run_id,
    ):
        return {
            "status": "skipped",
            "reason": "already_running",
            "avito_account_id": avito_account.id,
        }

    try:
        date_from = normalize_date(date_from)
        date_to = normalize_date(date_to)

        result = import_avito_listing_daily_stats_for_account(
            avito_account=avito_account,
            date_from=date_from,
            date_to=date_to,
            listing_ids=listing_ids,
            progress_callback=lambda: touch_sync_heartbeat(
                avito_account_id=avito_account.id,
                run_id=run_id,
            ),
        )
    except AvitoApiError as exc:
        retry_pending = (
                is_transient_avito_error(exc)
                and self.request.retries < self.max_retries
                and mark_sync_retry_pending(avito_account_id=avito_account.id, error=str(exc), run_id=run_id, )
        )

        if retry_pending:
            countdown = get_sync_retry_countdown(self)

            logger.warning(
                (
                    "Retrying Avito stats import "
                    "for account_id=%s run_id=%s "
                    "attempt=%s countdown=%s"
                ),
                avito_account.id,
                run_id,
                self.request.retries + 1,
                countdown,
            )

            raise self.retry(
                exc=exc,
                countdown=countdown,
            )

        mark_sync_error(
            avito_account_id=avito_account.id,
            error=str(exc),
            run_id=run_id,
        )
        logger.exception(
            "Avito stats import failed for account_id=%s",
            avito_account.id,
        )
        raise

    except Exception as exc:
        mark_sync_error(
            avito_account_id=avito_account.id,
            error=str(exc),
            run_id=run_id,
        )
        logger.exception(
            "Avito stats import failed for account_id=%s",
            avito_account.id,
        )
        raise

    success_marked = mark_sync_success(
        avito_account_id=avito_account.id,
        date_from=date_from,
        date_to=date_to,
        run_id=run_id,
    )

    if not success_marked:
        logger.info(
            (
                "Skipped completion of superseded Avito stats "
                "run for account_id=%s run_id=%s"
            ),
            avito_account.id,
            run_id,
        )
        return {
            "status": "superseded",
            "avito_account_id": avito_account.id,
        }
    logger.info(
        (
            "Imported Avito daily stats for account_id=%s: "
            "listings=%s days=%s created=%s updated=%s "
            "unchanged=%s"
        ),
        avito_account.id,
        result.total_listings,
        result.total_days,
        result.created_stats,
        result.updated_stats,
        result.unchanged_stats,
    )

    return {
        "status": "success",
        "total_listings": result.total_listings,
        "total_days": result.total_days,
        "created_stats": result.created_stats,
        "updated_stats": result.updated_stats,
        "unchanged_stats": result.unchanged_stats,
    }


@shared_task(
    bind=True,
    max_retries=AVITO_STATS_TASK_MAX_RETRIES,
)
def import_avito_account_profile_daily_stats_task(
        self,
        avito_account_id,
        stat_date,
        run_id=None,
):
    avito_account = (
        AvitoAccount.objects
        .select_related("workspace")
        .get(id=avito_account_id)
    )

    if not claim_sync(
            avito_account,
            run_id=run_id,
    ):
        return {
            "status": "skipped",
            "reason": "already_running",
            "avito_account_id": avito_account.id,
        }

    current_date = stat_date

    try:
        stat_date = normalize_date(stat_date)
        current_date = stat_date

        sync_state = (
            AvitoStatsSyncState.objects
            .only("coverage_to")
            .get(avito_account=avito_account)
        )

        if (
                sync_state.coverage_to is None
                or sync_state.coverage_to >= stat_date
        ):
            dates_to_import = [stat_date]
        else:
            missing_days = (
                    stat_date - sync_state.coverage_to
            ).days

            dates_to_import = [
                sync_state.coverage_to + timedelta(days=offset)
                for offset in range(1, missing_days + 1)
            ]

        total_received = 0
        matched_listings = 0
        created_stats = 0
        updated_stats = 0
        deleted_zero_stats = 0
        confirmed_listings = 0

        for current_date in dates_to_import:
            heartbeat_updated = touch_sync_heartbeat(
                avito_account_id=avito_account.id,
                run_id=run_id,
            )

            if not heartbeat_updated:
                logger.info(
                    (
                        "Stopped superseded Avito profile stats "
                        "run before date=%s account_id=%s run_id=%s"
                    ),
                    current_date,
                    avito_account.id,
                    run_id,
                )
                return {
                    "status": "superseded",
                    "avito_account_id": avito_account.id,
                }

            result = import_avito_profile_daily_stats_for_account(
                avito_account=avito_account,
                stat_date=current_date,
            )

            total_received += result.total_received
            matched_listings += result.matched_listings
            created_stats += result.created_stats
            updated_stats += result.updated_stats
            deleted_zero_stats += result.deleted_zero_stats
            confirmed_listings += result.confirmed_listings

    except AvitoApiError as exc:
        retry_pending = (
                is_transient_avito_error(exc)
                and self.request.retries < self.max_retries
                and mark_sync_retry_pending(avito_account_id=avito_account.id, error=str(exc), run_id=run_id, )

        )
        if retry_pending:
            countdown = get_sync_retry_countdown(self)
            logger.warning(
                (
                    "Retrying Avito profile daily stats "
                    "for account_id=%s date=%s run_id=%s "
                    "attempt=%s countdown=%s"
                ),
                avito_account.id,
                current_date,
                run_id,
                self.request.retries + 1,
                countdown,
            )
            raise self.retry(
                exc=exc,
                countdown=countdown,
            )
        mark_sync_error(
            avito_account_id=avito_account.id,
            error=str(exc),
            run_id=run_id,
        )
        logger.exception(
            (
                "Avito profile daily stats import failed "
                "for account_id=%s date=%s"
            ),
            avito_account.id,
            current_date,
        )
        raise
    except Exception as exc:
        mark_sync_error(
            avito_account_id=avito_account.id,
            error=str(exc),
            run_id=run_id,

        )
        logger.exception(
            (
                "Avito profile daily stats import failed "
                "for account_id=%s date=%s"
            ),
            avito_account.id,
            current_date,
        )
        raise

    success_marked = mark_sync_success(
        avito_account_id=avito_account.id,
        date_from=dates_to_import[0],
        date_to=stat_date,
        run_id=run_id,
    )

    if not success_marked:
        logger.info(
            (
                "Skipped completion of superseded Avito profile "
                "stats run for account_id=%s run_id=%s"
            ),
            avito_account.id,
            run_id,
        )
        return {
            "status": "superseded",
            "avito_account_id": avito_account.id,
        }

    logger.info(
        (
            "Imported Avito profile daily stats "
            "for account_id=%s range=%s..%s: "
            "dates=%s received=%s matched=%s created=%s "
            "updated=%s deleted_zero=%s confirmed=%s"
        ),
        avito_account.id,
        dates_to_import[0],
        stat_date,
        len(dates_to_import),
        total_received,
        matched_listings,
        created_stats,
        updated_stats,
        deleted_zero_stats,
        confirmed_listings,
    )

    backfill_result = enqueue_avito_stats_backfill(
        avito_account=avito_account,
        target_date=stat_date,
    )

    return {
        "status": "success",
        "date": stat_date.isoformat(),
        "dates_processed": len(dates_to_import),
        "total_received": total_received,
        "matched_listings": matched_listings,
        "created_stats": created_stats,
        "updated_stats": updated_stats,
        "deleted_zero_stats": deleted_zero_stats,
        "confirmed_listings": confirmed_listings,
        "backfill_queued": backfill_result["queued"],
    }


@shared_task(
    bind=True,
    max_retries=AVITO_STATS_TASK_MAX_RETRIES,
)
def backfill_missing_avito_listing_stats_task(
        self,
        avito_account_id,
        target_date,
        run_id=None,
):
    """
    Заполняет недостающую историю через stats/v1.

    План строится отдельно для каждого объявления, но одинаковые
    диапазоны объединяются, чтобы Avito API получал объявления пакетами.
    """

    avito_account = (
        AvitoAccount.objects
        .select_related("workspace")
        .get(id=avito_account_id)
    )

    if not claim_sync(
            avito_account,
            run_id=run_id,
    ):
        return {
            "status": "skipped",
            "reason": "already_running",
            "avito_account_id": avito_account.id,
        }

    try:
        target_date = normalize_date(target_date)

        plan = build_avito_stats_backfill_plan(
            avito_account=avito_account,
            target_date=target_date,
        )

        total_listings = 0
        total_days = 0
        created_stats = 0
        updated_stats = 0
        unchanged_stats = 0

        for request in plan:
            heartbeat_updated = touch_sync_heartbeat(
                avito_account_id=avito_account.id,
                run_id=run_id,
            )

            if not heartbeat_updated:
                logger.info(
                    (
                        "Stopped superseded Avito stats backfill "
                        "before range=%s..%s account_id=%s run_id=%s"
                    ),
                    request.date_from,
                    request.date_to,
                    avito_account.id,
                    run_id,
                )
                return {
                    "status": "superseded",
                    "avito_account_id": avito_account.id,
                }

            result = import_avito_listing_daily_stats_for_account(
                avito_account=avito_account,
                date_from=request.date_from,
                date_to=request.date_to,
                listing_ids=list(request.listing_ids),
                progress_callback=lambda: touch_sync_heartbeat(
                    avito_account_id=avito_account.id,
                    run_id=run_id,
                ),
            )

            total_listings += result.total_listings
            total_days += result.total_days
            created_stats += result.created_stats
            updated_stats += result.updated_stats
            unchanged_stats += result.unchanged_stats

    except AvitoApiError as exc:
        retry_pending = (
                is_transient_avito_error(exc)
                and self.request.retries < self.max_retries
                and mark_sync_retry_pending(avito_account_id=avito_account.id, error=str(exc), run_id=run_id, )

        )

        if retry_pending:
            countdown = get_sync_retry_countdown(self)

            logger.warning(

                (
                    "Retrying Avito stats backfill "
                    "for account_id=%s target_date=%s run_id=%s "
                    "attempt=%s countdown=%s"
                ),

                avito_account.id,
                target_date,
                run_id,
                self.request.retries + 1,
                countdown,
            )

            raise self.retry(
                exc=exc,
                countdown=countdown,
            )

        mark_sync_error(
            avito_account_id=avito_account.id,
            error=str(exc),
            run_id=run_id,
        )

        logger.exception(
            (
                "Avito stats backfill failed "
                "for account_id=%s target_date=%s"
            ),
            avito_account.id,
            target_date,
        )
        raise

    except Exception as exc:
        mark_sync_error(
            avito_account_id=avito_account.id,
            error=str(exc),
            run_id=run_id,
        )

        logger.exception(
            (
                "Avito stats backfill failed "
                "for account_id=%s target_date=%s"
            ),
            avito_account.id,
            target_date,
        )
        raise

    coverage_from = min(
        (
            request.date_from
            for request in plan
        ),
        default=target_date,
    )

    success_marked = mark_sync_success(
        avito_account_id=avito_account.id,
        date_from=coverage_from,
        date_to=target_date,
        run_id=run_id,
    )

    if not success_marked:
        logger.info(
            (
                "Skipped completion of superseded Avito stats "
                "backfill for account_id=%s run_id=%s"
            ),
            avito_account.id,
            run_id,
        )
        return {
            "status": "superseded",
            "avito_account_id": avito_account.id,
        }

    logger.info(
        (
            "Finished Avito stats backfill "
            "for account_id=%s target_date=%s: "
            "requests=%s listing_batches=%s "
            "days=%s created=%s updated=%s unchanged=%s"
        ),
        avito_account.id,
        target_date,
        len(plan),
        total_listings,
        total_days,
        created_stats,
        updated_stats,
        unchanged_stats,
    )

    return {
        "status": "success",
        "target_date": target_date.isoformat(),
        "requests_processed": len(plan),
        "total_listings": total_listings,
        "total_days": total_days,
        "created_stats": created_stats,
        "updated_stats": updated_stats,
        "unchanged_stats": unchanged_stats,
    }


@shared_task
def enqueue_daily_avito_stats_syncs_task():
    target_date = (
            timezone.localdate() - timedelta(days=1)
    )

    accounts = (
        AvitoAccount.objects
        .filter(
            is_active=True,
            external_account_id__isnull=False,
            oauth_tokens__isnull=False,
        )
        .exclude(external_account_id="")
        .select_related("workspace")
        .distinct()
    )

    queued = 0
    skipped = 0

    for avito_account in accounts.iterator(chunk_size=100):
        result = enqueue_avito_profile_daily_sync(
            avito_account=avito_account,
            stat_date=target_date,
        )

        if result["queued"]:
            queued += 1
        else:
            skipped += 1

    return {
        "queued": queued,
        "skipped": skipped,
    }


def is_transient_avito_error(exc):
    if isinstance(exc, AvitoConfigurationError):
        return False

    status_code = exc.status_code

    if status_code == 429:
        return True

    if (
            isinstance(status_code, int)
            and status_code >= 500
    ):
        return True

    return isinstance(
        exc.__cause__,
        requests.RequestException,
    )


def get_sync_retry_countdown(task):
    countdown = (
            AVITO_STATS_TASK_RETRY_BASE_SECONDS
            * (2 ** task.request.retries)
    )

    return min(
        countdown,
        AVITO_STATS_TASK_RETRY_MAX_SECONDS,
    )


def mark_sync_retry_pending(
        *,
        avito_account_id,
        error,
        run_id=None,
):
    try:
        requested_run_id = (
            uuid.UUID(str(run_id))
            if run_id is not None
            else None
        )
    except (AttributeError, TypeError, ValueError):
        return False

    now = timezone.now()

    updated_count = AvitoStatsSyncState.objects.filter(
        avito_account_id=avito_account_id,
        run_id=requested_run_id,
        status=AvitoStatsSyncState.Status.RUNNING,
    ).update(
        status=AvitoStatsSyncState.Status.QUEUED,
        requested_at=now,
        started_at=None,
        heartbeat_at=None,
        finished_at=None,
        error=error,
        updated_at=now,
    )

    return updated_count == 1


def claim_sync(avito_account, run_id=None):
    now = timezone.now()

    try:
        requested_run_id = (
            uuid.UUID(str(run_id))
            if run_id is not None
            else None
        )
    except (AttributeError, TypeError, ValueError):
        return False

    with transaction.atomic():
        AvitoStatsSyncState.objects.get_or_create(
            workspace=avito_account.workspace,
            avito_account=avito_account,
        )

        sync_state = (
            AvitoStatsSyncState.objects
            .select_for_update()
            .get(avito_account=avito_account)
        )

        if sync_state.run_id != requested_run_id:
            return False

        if sync_state.status != AvitoStatsSyncState.Status.QUEUED:
            return False

        sync_state.status = AvitoStatsSyncState.Status.RUNNING
        sync_state.started_at = now
        sync_state.heartbeat_at = now
        sync_state.finished_at = None
        sync_state.error = ""
        sync_state.save(
            update_fields=[
                "status",
                "started_at",
                "heartbeat_at",
                "finished_at",
                "error",
                "updated_at",
            ]
        )

    return True


def touch_sync_heartbeat(
        *,
        avito_account_id,
        run_id,
):
    try:
        requested_run_id = (
            uuid.UUID(str(run_id))
            if run_id is not None
            else None
        )
    except (AttributeError, TypeError, ValueError):
        return False

    now = timezone.now()

    updated_count = AvitoStatsSyncState.objects.filter(
        avito_account_id=avito_account_id,
        run_id=requested_run_id,
        status=AvitoStatsSyncState.Status.RUNNING,
    ).update(
        heartbeat_at=now,
        updated_at=now,
    )

    return updated_count == 1


def mark_sync_success(
        *,
        avito_account_id,
        date_from,
        date_to,
        run_id=None,
):
    now = timezone.now()

    try:
        requested_run_id = (
            uuid.UUID(str(run_id))
            if run_id is not None
            else None
        )
    except (AttributeError, TypeError, ValueError):
        return False

    with transaction.atomic():
        sync_state = (
            AvitoStatsSyncState.objects
            .select_for_update()
            .get(avito_account_id=avito_account_id)
        )

        if sync_state.run_id != requested_run_id:
            return False

        sync_state.status = AvitoStatsSyncState.Status.SUCCESS
        sync_state.coverage_from = min_not_none(
            sync_state.coverage_from,
            date_from,
        )
        sync_state.coverage_to = max_not_none(
            sync_state.coverage_to,
            date_to,
        )
        sync_state.finished_at = now
        sync_state.last_successful_at = now
        sync_state.error = ""
        sync_state.save(
            update_fields=[
                "status",
                "coverage_from",
                "coverage_to",
                "finished_at",
                "last_successful_at",
                "error",
                "updated_at",
            ]
        )

    return True


def mark_sync_error(
        *,
        avito_account_id,
        error,
        run_id=None,
):
    try:
        requested_run_id = (
            uuid.UUID(str(run_id))
            if run_id is not None
            else None
        )
    except (AttributeError, TypeError, ValueError):
        return False

    now = timezone.now()

    updated_count = AvitoStatsSyncState.objects.filter(
        avito_account_id=avito_account_id,
        run_id=requested_run_id,
    ).update(
        status=AvitoStatsSyncState.Status.ERROR,
        finished_at=now,
        error=error,
        updated_at=now,
    )

    return updated_count == 1


def is_active_sync(sync_state, *, now):
    if sync_state.status not in {
        AvitoStatsSyncState.Status.QUEUED,
        AvitoStatsSyncState.Status.RUNNING,
    }:
        return False

    if sync_state.status == AvitoStatsSyncState.Status.RUNNING:
        anchor = (
                sync_state.heartbeat_at
                or sync_state.started_at
        )
    else:
        anchor = sync_state.requested_at

    if anchor is None:
        return False

    stale_timeout = timedelta(
        minutes=settings.AVITO_STATS_STALE_TIMEOUT_MINUTES
    )

    return anchor > now - stale_timeout


def min_not_none(current, incoming):
    if current is None:
        return incoming
    return min(current, incoming)


def max_not_none(current, incoming):
    if current is None:
        return incoming
    return max(current, incoming)
