from celery import shared_task

import logging

from django.db import transaction
from django.utils import timezone

from .services.avito_import import import_avito_listings_for_account

from .models import AvitoAccount
from .services.ad_export import export_avito_account_publications_to_csv
from .services.avito_autoload import link_publications_to_avito_ids_for_account
from .services.ad_schedule import run_due_ad_generation_tasks as run_due_ad_generation_tasks_service
from .services.avito_stats import import_avito_listing_daily_stats_for_account
from .services.ad_cleanup import archive_stale_publications
from .services.ad_export_state import mark_avito_account_exporting
from .services.avito_autoload_report_fetch import sync_last_completed_autoload_report_for_account
from .services.avito_sync_state import is_avito_account_sync_stale

logger = logging.getLogger(__name__)


@shared_task
def update_product_price(product_id):
    logger.warning(
        "Legacy update_product_price task is disabled. Product is no longer an active task model."
    )
    return {
        "status": "disabled",
        "replacement": "AdGenerationTask",
    }


@shared_task
def schedule_price_updates():
    logger.warning(
        "Legacy schedule_price_updates task is disabled. Use run_due_ad_generation_tasks instead."
    )
    return {
        "status": "disabled",
        "replacement": "avitotask.tasks.run_due_ad_generation_tasks",
    }


@shared_task
def print_hello():
    print("Hello World!")


@shared_task
def export_avito_account_csv_task(avito_account_id):
    with transaction.atomic():
        avito_account = (
            AvitoAccount.objects
            .select_related("workspace")
            .select_for_update(of=("self",))
            .get(id=avito_account_id)
        )

        if avito_account.export_status == AvitoAccount.ExportStatus.EXPORTING:
            return {
                "status": "skipped",
                "reason": "already_exporting",
            }

        if avito_account.export_status == AvitoAccount.ExportStatus.CLEAN:
            return {
                "status": "skipped",
                "reason": "already_clean",
                "file_path": avito_account.export_file_path,
            }

        mark_avito_account_exporting(avito_account)

    avito_account.refresh_from_db()

    try:
        file_path = export_avito_account_publications_to_csv(
            workspace=avito_account.workspace,
            avito_account=avito_account,
        )
    except Exception as exc:
        AvitoAccount.objects.filter(id=avito_account_id).update(
            export_status=AvitoAccount.ExportStatus.ERROR,
            export_error=str(exc),
        )
        raise

    logger.info(
        "Exported Avito CSV for account_id=%s to %s",
        avito_account.id,
        file_path,
    )

    return str(file_path)


@shared_task
def export_dirty_avito_accounts_csv_task(limit=20):
    dirty_accounts = (
        AvitoAccount.objects
        .select_related("workspace")
        .filter(
            is_active=True,
            export_status__in=[
                AvitoAccount.ExportStatus.DIRTY,
                AvitoAccount.ExportStatus.QUEUED,
            ]
        )
        .order_by("export_requested_at", "id")[:limit]
    )

    exported_count = 0

    for avito_account in dirty_accounts:
        export_avito_account_csv_task(avito_account.id)
        exported_count += 1

    return exported_count


@shared_task
def import_avito_account_listings_task(avito_account_id, session=None):
    with transaction.atomic():
        avito_account = (
            AvitoAccount.objects
            .select_related("workspace")
            .select_for_update()
            .get(id=avito_account_id)
        )
        if avito_account.sync_status == AvitoAccount.SyncStatus.SYNCING:
            return {
                "status": "skipped",
                "reason": "Import is already running for this account"
            }

        avito_account.sync_status = AvitoAccount.SyncStatus.SYNCING
        avito_account.sync_started_at = timezone.now()
        avito_account.sync_error = None
        avito_account.save(
            update_fields=[
                "sync_status",
                "sync_started_at",
                "sync_error",
                "updated_at",
            ]
        )

    try:
        result = import_avito_listings_for_account(
            avito_account,
            session=session,
        )
    except Exception as exc:
        AvitoAccount.objects.filter(id=avito_account_id).update(
            sync_status=AvitoAccount.SyncStatus.ERROR,
            sync_error=str(exc),
            updated_at=timezone.now(),
        )
        raise

    AvitoAccount.objects.filter(id=avito_account_id).update(
        sync_status=AvitoAccount.SyncStatus.IDLE,
        sync_error=None,
        last_synced_at=timezone.now(),
        last_sync_total_received=result.total_received,
        last_sync_created_listings=result.created_listings,
        last_sync_updated_listings=result.updated_listings,
        updated_at=timezone.now(),
    )

    logger.info(
        "Imported Avito listings for account_id=%s: total=%s created=%s updated=%s publications=%s",
        avito_account.id,
        result.total_received,
        result.created_listings,
        result.updated_listings,
    )

    return {
        "status": "completed",
        "total_received": result.total_received,
        "created_listings": result.created_listings,
        "updated_listings": result.updated_listings,
        "out_of_sync_listings": result.out_of_sync_listings,
        "batch_id": result.batch.id if result.batch else None,
    }


@shared_task
def link_avito_account_publications_task(avito_account_id, row_ids=None, session=None):
    avito_account = (
        AvitoAccount.objects
        .select_related("workspace")
        .get(id=avito_account_id)
    )

    result = link_publications_to_avito_ids_for_account(
        avito_account,
        row_ids=row_ids,
        session=session
    )

    logger.info(
        "Linked Avito publications for account_id=%s: requested=%s linked=%s missing=%s conflicts=%s",
        avito_account.id,
        result.total_requested,
        result.linked,
        result.missing,
        result.conflicts,
    )

    return {
        "total_requested": result.total_requested,
        "linked": result.linked,
        "missing": result.missing,
        "conflicts": result.conflicts,
        "created_listings": result.created_listings,
        "updated_listings": result.updated_listings,
    }


@shared_task
def import_avito_account_daily_stats_task(
        avito_account_id,
        date_from,
        date_to,
        listing_ids=None,
        session=None,
):
    avito_account = (
        AvitoAccount.objects
        .select_related("workspace")
        .get(id=avito_account_id)
    )

    result = import_avito_listing_daily_stats_for_account(
        avito_account=avito_account,
        date_from=date_from,
        date_to=date_to,
        listing_ids=listing_ids,
        session=session
    )

    logger.info(
        "Imported Avito daily stats for account_id=%s: listings=%s days=%s created=%s updated=%s",
        avito_account.id,
        result.total_listings,
        result.total_days,
        result.created_stats,
        result.updated_stats,
    )

    return {
        "total_listings": result.total_listings,
        "total_days": result.total_days,
        "created_stats": result.created_stats,
        "updated_stats": result.updated_stats,
    }


@shared_task
def archive_stale_publications_task(older_than_days=60, limit=1000):
    result = archive_stale_publications(
        older_than_days=older_than_days,
        limit=limit
    )

    logger.info(
        "Archived stale publications: archived=%s older_than_days=%s limit=%s",
        result.archived_publications,
        older_than_days,
        limit,
    )

    return {
        "archived_publications": result.archived_publications,
    }


@shared_task
def run_due_ad_generation_tasks(limit=50):
    return run_due_ad_generation_tasks_service(limit=limit)


@shared_task
def sync_last_completed_avito_autoload_report_task(avito_account_id, session=None):
    with transaction.atomic():
        avito_account = (
            AvitoAccount.objects
            .select_related("workspace")
            .select_for_update(of=("self",))
            .get(id=avito_account_id)
        )

        if (
                avito_account.sync_status == AvitoAccount.SyncStatus.SYNCING
                and not is_avito_account_sync_stale(avito_account)
        ):
            return {
                "status": "skipped",
                "reason": "already_syncing",
            }

        avito_account.sync_status = AvitoAccount.SyncStatus.SYNCING
        avito_account.sync_started_at = timezone.now()
        avito_account.sync_error = None
        avito_account.save(
            update_fields=[
                "sync_status",
                "sync_started_at",
                "sync_error",
                "updated_at",
            ]
        )

    avito_account.refresh_from_db()

    try:
        result = sync_last_completed_autoload_report_for_account(
            avito_account=avito_account,
            session=session,
        )
    except Exception as exc:
        AvitoAccount.objects.filter(id=avito_account_id).update(
            sync_status=AvitoAccount.SyncStatus.ERROR,
            sync_error=str(exc),
            updated_at=timezone.now(),
        )
        raise

    sync_result = result.sync_result

    AvitoAccount.objects.filter(id=avito_account_id).update(
        sync_status=AvitoAccount.SyncStatus.IDLE,
        sync_error=None,
        last_synced_at=timezone.now(),
        last_sync_total_received=sync_result.total_rows,
        last_sync_created_listings=sync_result.created_listings,
        last_sync_updated_listings=sync_result.updated_listings,
        updated_at=timezone.now(),
    )

    logger.info(
        "Synced last completed Avito autoload report for account_id=%s report_id=%s rows=%s linked=%s created=%s updated=%s",
        avito_account_id,
        result.report_id,
        sync_result.total_rows,
        sync_result.linked_publications,
        sync_result.created_listings,
        sync_result.updated_listings,
    )

    return {
        "status": "completed",
        "report_id": result.report_id,
        "report_status": result.report_status,
        "total_items_received": result.total_items_received,
        "total_rows": sync_result.total_rows,
        "accepted_rows": sync_result.accepted_rows,
        "rejected_rows": sync_result.rejected_rows,
        "linked_publications": sync_result.linked_publications,
        "created_listings": sync_result.created_listings,
        "updated_listings": sync_result.updated_listings,
        "missing_row_id": sync_result.missing_row_id,
        "missing_publications": sync_result.missing_publications,
        "conflicts": sync_result.conflicts,
        "errors": sync_result.errors,
    }


@shared_task
def sync_last_completed_avito_autoload_reports_task(limit=20):
    avito_accounts = (
        AvitoAccount.objects
        .filter(is_active=True)
        .exclude(sync_status=AvitoAccount.SyncStatus.SYNCING)
        .order_by("last_synced_at", "id")[:limit]
    )

    queued = 0

    for avito_account in avito_accounts:
        sync_last_completed_avito_autoload_report_task.delay(avito_account.id)
        queued += 1

    return {
        "queued": queued,
    }
