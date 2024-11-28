from celery import shared_task
from django.utils.timezone import now

from .models import Product
from datetime import datetime, timedelta


@shared_task
def update_product_price(product_id):
    try:
        product = Product.objects.get(id=product_id)
        print(f"Готово!{product.name}")
        print(f"{product.last_updated}")
        product.save()
    except Exception as e:
        print(f"Ошибка обновления цены для продукта {product_id}: {e}")


@shared_task
def schedule_price_updates():
    products = Product.objects.filter(next_update_time__lte=now())  # Проверяем, какие продукты пора обновить
    for product in products:
        update_product_price.delay(product.id)
        # Установим новое время обновления, если это требуется
        product.next_update_time = None  # Или обновить на следующее запланированное время
        product.save()


@shared_task
def print_hello():
    print("Hello World!")
