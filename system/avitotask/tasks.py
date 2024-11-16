from celery import shared_task
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
    products = Product.objects.all()
    current_time = datetime.now()  # Naive время
    for product in products:
        next_update = product.last_updated.replace(tzinfo=None) + timedelta(seconds=product.update_interval)
        if current_time >= next_update:
            update_product_price.delay(product.id)


@shared_task
def print_hello():
    print("Hello World!")