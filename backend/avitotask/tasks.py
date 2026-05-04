from celery import shared_task
from django.utils.timezone import now

import logging

from .models import Product
from datetime import datetime, timedelta
from .services.ad_schedule import run_due_ad_generation_tasks as run_due_ad_generation_tasks_service
from .views import product_random

from .models import AvitoAccount
from .services.ad_export import export_avito_account_publications_to_csv

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
    products = Product.objects.filter(next_update_time__lte=now())  # Проверяем, какие продукты пора обновить
    for product in products:
        print(product.id)
        product_random(product.id)  # Вызываем как обычную функцию
        print(f"Updated product ID: {product.id}")

    print("DONE!")


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
def run_due_ad_generation_tasks(limit=50):
    return run_due_ad_generation_tasks_service(limit=limit)
