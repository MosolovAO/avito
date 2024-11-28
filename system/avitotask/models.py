from datetime import timedelta

from django.db import models


class Product(models.Model):
    name = models.CharField(max_length=255)
    url = models.URLField()
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    next_update_time = models.DateTimeField(
        null=True, blank=True,
        help_text="Точное время следующего обновления цены"
    )
    last_updated = models.DateTimeField(auto_now=True)
    titles = models.JSONField(default=list, blank=True, help_text="Список заголовков для продукта")

    def __str__(self):
        return self.name


