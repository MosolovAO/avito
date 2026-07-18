from django.db import models


class AvitoListingDailyStats(models.Model):
    """Дневная статистика объявления Avito."""

    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="avito_listing_daily_stats",
    )
    listing = models.ForeignKey(
        "avitotask.AvitoListing",
        on_delete=models.CASCADE,
        related_name="analytics_daily_stats",
    )

    date = models.DateField()

    views = models.PositiveIntegerField(default=0)
    contacts = models.PositiveIntegerField(default=0)
    favorites = models.PositiveIntegerField(default=0)

    calls = models.PositiveIntegerField(default=0)
    messages = models.PositiveIntegerField(default=0)

    total_spend = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Расходы по объявлению за день в рублях.",
    )

    raw_metrics = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Дневная статистика Avito"
        verbose_name_plural = "Дневная статистика Avito"
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["listing", "date"], name="idx_an_avstats_listing_date"),
            models.Index(fields=["workspace", "-date"], name="idx_an_avstats_ws_date"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["listing", "date"],
                name="uniq_an_avstats_listing_date",
            )
        ]

    def __str__(self):
        return f"{self.listing.avito_id} / {self.date}"