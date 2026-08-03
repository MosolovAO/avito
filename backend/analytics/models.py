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


class AvitoStatsSyncState(models.Model):
    """Постоянное состояние синхронизации статистики Avito-аккаунта."""

    class Status(models.TextChoices):
        NOT_STARTED = "not_started", "Не запускалась"
        QUEUED = "queued", "В очереди"
        RUNNING = "running", "Выполняется"
        SUCCESS = "success", "Успешно"
        ERROR = "error", "Ошибка"

    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="avito_stats_sync_states",
    )
    avito_account = models.OneToOneField(
        "avitotask.AvitoAccount",
        on_delete=models.CASCADE,
        related_name="analytics_stats_sync",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NOT_STARTED,
    )

    run_id = models.UUIDField(
        null=True,
        blank=True,
        editable=False,
    )
    heartbeat_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    requested_date_from = models.DateField(null=True, blank=True)
    requested_date_to = models.DateField(null=True, blank=True)

    coverage_from = models.DateField(null=True, blank=True)
    coverage_to = models.DateField(null=True, blank=True)

    requested_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    last_successful_at = models.DateTimeField(null=True, blank=True)

    error = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Состояние синхронизации статистики Avito"
        verbose_name_plural = "Состояния синхронизации статистики Avito"
        indexes = [
            models.Index(
                fields=["workspace", "status"],
                name="idx_an_avsync_ws_status",
            ),
        ]

    def __str__(self):
        return f"{self.avito_account_id}: {self.status}"


class AvitoListingStatsCoverage(models.Model):
    """
    Подтверждённый диапазон финальной дневной статистики объявления.

    Отсутствие AvitoListingDailyStats внутри этого диапазона означает
    подтверждённые нулевые значения.
    """

    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="avito_listing_stats_coverages",
    )
    listing = models.OneToOneField(
        "avitotask.AvitoListing",
        on_delete=models.CASCADE,
        related_name="analytics_stats_coverage",
    )

    coverage_from = models.DateField(null=True, blank=True)
    finalized_through = models.DateField(null=True, blank=True)

    spending_coverage_from = models.DateField(
        null=True,
        blank=True,
    )
    spending_finalized_through = models.DateField(
        null=True,
        blank=True,
    )

    last_attempted_at = models.DateTimeField(null=True, blank=True)
    last_successful_at = models.DateTimeField(null=True, blank=True)

    error = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Покрытие статистики объявления Avito"
        verbose_name_plural = "Покрытия статистики объявлений Avito"
        indexes = [
            models.Index(
                fields=["workspace", "finalized_through"],
                name="idx_an_avcov_ws_final",
            ),
        ]

    def __str__(self):
        return (
            f"{self.listing_id}: "
            f"{self.coverage_from} — {self.finalized_through}"
        )
