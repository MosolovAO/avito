from celery import shared_task

import logging

from django.db import transaction
from django.utils import timezone

from .services.avito_import import import_avito_listings_for_account
from .models import Product

from .models import AvitoAccount
from .services.ad_export import export_avito_account_publications_to_csv
from .services.avito_autoload import link_publications_to_avito_ids_for_account
from .services.ad_schedule import run_due_ad_generation_tasks as run_due_ad_generation_tasks_service
from .services.avito_stats import import_avito_listing_daily_stats_for_account
from .services.ad_cleanup import archive_stale_publications

logger = logging.getLogger(__name__)


@shared_task
def update_product_price(product_id):
    try:
        product = Product.objects.get(id=product_id)
        print(f"Готово!{product.name}, {product.last_updated}")
        product.save()
    except Exception as e:
        print(f"Ошибка обновления цены для продукта {product_id}: {e}")


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
    avito_account = (
        AvitoAccount.objects
        .select_related("workspace")
        .get(id=avito_account_id)
    )

    file_path = export_avito_account_publications_to_csv(
        workspace=avito_account.workspace,
        avito_account=avito_account
    )

    logger.info(
        "Exported Avito CSV for account_id=%s to %s",
        avito_account.id,
        file_path
    )

    return str(file_path)


@shared_task
def export_dirty_avito_accounts_csv_task(limit=20):
    dirty_accounts = (
        AvitoAccount.objects
        .select_related("workspace")
        .filter(
            is_active=True,
            export_status=AvitoAccount.ExportStatus.DIRTY
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
            .get(id=avito_account_id)
        )
        if avito_account.sync_status == AvitoAccount.SyncStatus.SYNCING:
            return {
                "status": "synced",
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
            session=session
        )
    except Exception as exc:
        AvitoAccount.objects.filter(id=avito_account_id).update(
            export_status=AvitoAccount.ExportStatus.ERROR,
            export_error=str(exc),
            updated_at=timezone.now()
        )
        raise

    AvitoAccount.objects.filter(id=avito_account_id).update(
        export_status=AvitoAccount.ExportStatus.DIRTY,
        export_error=None,
        last_sync_at=timezone.now(),
        updated_at=timezone.now()
    )

    logger.info(
        "Imported Avito listings for account_id=%s: total=%s created=%s updated=%s publications=%s",
        avito_account.id,
        result.total_received,
        result.created_listings,
        result.updated_listings,
        result.created_publications,
    )

    return {
        "status": "completed",
        "total_received": result.total_received,
        "created_listings": result.created_listings,
        "updated_listings": result.updated_listings,
        "created_publications": result.created_publications,
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
