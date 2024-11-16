from datetime import timedelta

from django.db import models


class Product(models.Model):
    name = models.CharField(max_length=255)
    url = models.URLField()
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    update_interval = models.IntegerField(
        default=24,  # Интервал в часах
        help_text="Интервал обновления цены в часах"
    )
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    def next_update_time(self):
        """Вычисляет время следующего обновления."""
        return self.last_updated + timedelta(seconds=self.update_interval)