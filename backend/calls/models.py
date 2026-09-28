from django.db import models


class Call(models.Model):
    class Type(models.TextChoices):
        NEW = "new", "Новый"
        REPEAT = "repeat", "Повторный"

    workspace = models.ForeignKey(
        "accounts.Workspace", on_delete=models.CASCADE, related_name="calls",
    )
    avito_account = models.ForeignKey(
        "avitotask.AvitoAccount", on_delete=models.CASCADE, related_name="calls",
    )
    listing = models.ForeignKey(
        "avitotask.AvitoListing", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="calls",
    )
    external_id = models.CharField(max_length=100)
    occurred_at = models.DateTimeField()
    buyer_phone = models.CharField(max_length=64, blank=True)
    normalized_phone = models.CharField(max_length=20, blank=True)
    talk_duration = models.PositiveIntegerField(default=0)
    waiting_duration = models.PositiveIntegerField(default=0)
    is_missed = models.BooleanField(null=True, default=None)
    call_type = models.CharField(
        max_length=10, choices=Type.choices, null=True, blank=True,
    )
    avito_item_id = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["avito_account", "external_id"],
                name="uniq_call_account_external_id",
            ),
        ]
        indexes = [
            models.Index(
                fields=["workspace", "avito_account", "-occurred_at", "-id"],
                name="idx_calls_workspace_time",
            ),
            models.Index(
                fields=["avito_account", "normalized_phone", "occurred_at", "external_id"],
                name="idx_calls_account_phone_time",
            ),
        ]


class CallSyncState(models.Model):
    class Phase(models.TextChoices):
        SYNCING = "syncing", "Синхронизация"
        CLASSIFYING = "classifying", "Классификация"

    avito_account = models.OneToOneField(
        "avitotask.AvitoAccount",
        on_delete=models.CASCADE,
        related_name="calls_sync_state",
    )
    phase = models.CharField(
        max_length=16, choices=Phase.choices, null=True, blank=True,
    )
    last_synced_at = models.DateTimeField(null=True, blank=True)
    backfill_before = models.DateTimeField(null=True, blank=True)
    backfill_complete = models.BooleanField(default=False)
    classification_complete = models.BooleanField(default=False)
    lease_until = models.DateTimeField(null=True, blank=True)
    lease_token = models.CharField(max_length=32, blank=True)
    last_error = models.TextField(blank=True)
