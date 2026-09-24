from django.conf import settings
from django.db import models
from django.db.models import F, Q


class Automation(models.Model):
    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        ENABLED = "enabled", "Enabled"
        DISABLED = "disabled", "Disabled"
        ARCHIVED = "archived", "Archived"

    class ExecutionMode(models.TextChoices):
        MANUAL = "manual", "Manual"

    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="automations",
    )

    module_type = models.CharField(max_length=64)
    name = models.CharField(max_length=255)

    state = models.CharField(
        max_length=20,
        choices=State.choices,
        default=State.DRAFT,
    )
    execution_mode = models.CharField(
        max_length=20,
        choices=ExecutionMode.choices,
        default=ExecutionMode.MANUAL,
    )

    version = models.PositiveIntegerField(default=1)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_automations",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_automations",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["workspace", "state"],
                name="idx_auto_workspace_state",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(version__gte=1),
                name="chk_auto_version_positive",
            ),
        ]

    def __str__(self):
        return self.name


class AutomationRun(models.Model):
    """
    Устойчивое состояние одного вычисления автоматизации.

    Предметные снимки и счётчики хранятся в типизированных моделях
    результата, а не в этой общей таблице.
    """

    class RunKind(models.TextChoices):
        PREVIEW = "preview", "Preview"
        EXECUTE = "execute", "Execute"

    class Trigger(models.TextChoices):
        MANUAL = "manual", "Manual"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        WAITING_FOR_DATA = "waiting_for_data", "Waiting for data"
        EVALUATING = "evaluating", "Evaluating"
        WAITING_APPROVAL = "waiting_approval", "Waiting approval"
        EFFECT_PENDING = "effect_pending", "Effect pending"
        COMPLETED = "completed", "Completed"
        PARTIAL = "partial", "Partial"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    automation = models.ForeignKey(
        Automation,
        on_delete=models.CASCADE,
        related_name="runs",
    )
    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="automation_runs",
    )

    run_kind = models.CharField(
        max_length=16,
        choices=RunKind.choices,
    )
    trigger = models.CharField(
        max_length=16,
        choices=Trigger.choices,
        default=Trigger.MANUAL,
    )

    execution_mode_snapshot = models.CharField(
        max_length=20,
        choices=Automation.ExecutionMode.choices,
    )
    automation_version = models.PositiveIntegerField()
    automation_name_snapshot = models.CharField(max_length=255)
    module_type_snapshot = models.CharField(max_length=64)

    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.QUEUED,
    )

    idempotency_key = models.CharField(
        max_length=128,
        null=True,
        blank=True,
    )

    retry_count = models.PositiveSmallIntegerField(default=0)
    data_wait_attempt_count = models.PositiveSmallIntegerField(default=0)

    next_attempt_at = models.DateTimeField(null=True, blank=True)
    wait_started_at = models.DateTimeField(null=True, blank=True)

    run_token = models.UUIDField(
        null=True,
        blank=True,
        editable=False,
    )
    heartbeat_at = models.DateTimeField(null=True, blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    error_code = models.CharField(
        max_length=64,
        blank=True,
        default="",
    )
    error_message = models.TextField(
        blank=True,
        default="",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_automation_runs",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["status", "next_attempt_at", "id"],
                name="idx_autorun_status_next_id",
            ),
            models.Index(
                fields=["automation", "created_at"],
                name="idx_autorun_automation_created",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(automation_version__gte=1),
                name="chk_autorun_version_positive",
            ),
            models.UniqueConstraint(
                fields=[
                    "automation",
                    "run_kind",
                    "idempotency_key",
                ],
                condition=(
                        Q(idempotency_key__isnull=False)
                        & ~Q(idempotency_key="")
                ),
                name="uniq_autorun_client_key",
            ),
            models.UniqueConstraint(
                fields=["automation", "run_kind"],
                condition=Q(
                    status__in=[
                        "queued",
                        "waiting_for_data",
                        "evaluating",
                        "waiting_approval",
                        "effect_pending",
                    ]
                ),
                name="uniq_autorun_open_kind",
            ),
        ]


class AvitoListingAutomationConfig(models.Model):
    """
    Типизированная конфигурация модуля автоматизации объявлений Avito.

    Дерево условий и действие проверяются валидатором модуля. Модель
    обеспечивает целостность связей и ограничения на уровне базы данных.
    """

    automation = models.OneToOneField(
        Automation,
        on_delete=models.CASCADE,
        related_name="avito_listing_config",
    )
    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="avito_listing_automation_configs",
    )
    avito_account = models.ForeignKey(
        "avitotask.AvitoAccount",
        on_delete=models.RESTRICT,
        related_name="avito_listing_automation_configs",
    )

    condition_tree = models.JSONField()

    action_type = models.CharField(max_length=64)
    action_config = models.JSONField(
        default=dict,
        blank=True,
    )

    max_actions_per_run = models.PositiveSmallIntegerField(default=10)
    approval_ttl_minutes = models.PositiveSmallIntegerField(default=1440)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                        Q(max_actions_per_run__gte=1)
                        & Q(max_actions_per_run__lte=100)
                ),
                name="chk_avcfg_actions_range",
            ),
            models.CheckConstraint(
                condition=(
                        Q(approval_ttl_minutes__gte=60)
                        & Q(approval_ttl_minutes__lte=10080)
                ),
                name="chk_avcfg_ttl_range",
            ),
        ]


class AvitoListingRunResult(models.Model):
    """
    Типизированный результат вычисления объявлений Avito.

    `examples_snapshot` — UX-гипотеза MVP для объяснения результата
    асинхронного preview. После реальных пользовательских тестов поле нужно
    сохранить, только если оно используется интерфейсом. В противном случае
    его необходимо удалить отдельной миграцией схемы.

    Вычислитель должен сохранять не более 20 безопасных примеров.
    """

    run = models.OneToOneField(
        AutomationRun,
        on_delete=models.CASCADE,
        related_name="avito_listing_result",
    )
    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="avito_listing_run_results",
    )
    avito_account = models.ForeignKey(
        "avitotask.AvitoAccount",
        on_delete=models.RESTRICT,
        related_name="automation_run_results",
    )

    as_of_date = models.DateField()
    max_actions_per_run_snapshot = models.PositiveSmallIntegerField(
        default=10,
    )
    approval_ttl_minutes_snapshot = models.PositiveSmallIntegerField(
        default=1440,
    )
    target_max_id_snapshot = models.PositiveBigIntegerField(default=0)

    condition_snapshot = models.JSONField()
    action_snapshot = models.JSONField()

    examples_snapshot = models.JSONField(
        default=list,
        blank=True,
    )

    checked = models.PositiveIntegerField(default=0)
    ineligible = models.PositiveIntegerField(default=0)
    insufficient_coverage = models.PositiveIntegerField(default=0)
    not_matched = models.PositiveIntegerField(default=0)
    matched = models.PositiveIntegerField(default=0)
    deferred_by_run_limit = models.PositiveIntegerField(default=0)

    pending_approval = models.PositiveIntegerField(default=0)
    completed_actions = models.PositiveIntegerField(default=0)
    failed_actions = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["avito_account", "as_of_date"],
                name="idx_avres_account_asof",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                        Q(max_actions_per_run_snapshot__gte=1)
                        & Q(max_actions_per_run_snapshot__lte=100)
                ),
                name="chk_avres_actions_range",
            ),
            models.CheckConstraint(
                condition=(
                        Q(approval_ttl_minutes_snapshot__gte=60)
                        & Q(approval_ttl_minutes_snapshot__lte=10080)
                ),
                name="chk_avres_ttl_range",
            ),
        ]


class AvitoListingDecision(models.Model):
    """
    Устойчивое решение о выполнении действия над одним объявлением Avito.

    Снимки должны содержать только безопасные атрибуты для журнала. Полные
    описания, изображения, OAuth-данные и исходные импортированные данные
    сохранять запрещено. Переходы статусов выполняются доменными сервисами,
    а не методом model.save().
    """

    class Status(models.TextChoices):
        PENDING_APPROVAL = "pending_approval", "Pending approval"
        APPLYING = "applying", "Applying"
        EFFECT_PENDING = "effect_pending", "Effect pending"
        COMPLETED = "completed", "Completed"
        REJECTED = "rejected", "Rejected"
        EXPIRED = "expired", "Expired"
        STALE = "stale", "Stale"
        SUPERSEDED = "superseded", "Superseded"
        FAILED = "failed", "Failed"

    run = models.ForeignKey(
        AutomationRun,
        on_delete=models.CASCADE,
        related_name="avito_listing_decisions",
    )
    automation = models.ForeignKey(
        Automation,
        on_delete=models.CASCADE,
        related_name="avito_listing_decisions",
    )
    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="avito_listing_decisions",
    )
    avito_account = models.ForeignKey(
        "avitotask.AvitoAccount",
        on_delete=models.RESTRICT,
        related_name="automation_decisions",
    )

    listing = models.ForeignKey(
        "avitotask.AvitoListing",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="automation_decisions",
    )
    listing_id_snapshot = models.PositiveBigIntegerField()
    listing_snapshot = models.JSONField()

    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING_APPROVAL,
    )

    automation_version = models.PositiveIntegerField()
    active_since_snapshot = models.DateTimeField()

    condition_snapshot = models.JSONField()
    metrics_snapshot = models.JSONField()
    action_snapshot = models.JSONField()

    expires_at = models.DateTimeField()

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_avito_listing_decisions",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rejected_avito_listing_decisions",
    )
    rejected_at = models.DateTimeField(null=True, blank=True)

    action_applied_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    terminal_at = models.DateTimeField(null=True, blank=True)

    required_export_revision = models.PositiveBigIntegerField(
        null=True,
        blank=True,
    )
    effect_attempts = models.PositiveSmallIntegerField(default=0)
    next_effect_retry_at = models.DateTimeField(null=True, blank=True)

    error_code = models.CharField(
        max_length=64,
        blank=True,
        default="",
    )
    error_message = models.TextField(
        blank=True,
        default="",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["run", "status"],
                name="idx_avdec_run_status",
            ),
            models.Index(
                fields=["listing", "status"],
                name="idx_avdec_listing_status",
            ),
            models.Index(
                fields=["status", "expires_at"],
                name="idx_avdec_status_expires",
            ),
            models.Index(
                fields=["terminal_at", "id"],
                name="idx_avdec_terminal_id",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(listing_id_snapshot__gte=1),
                name="chk_avdec_listing_id_positive",
            ),
            models.CheckConstraint(
                condition=Q(automation_version__gte=1),
                name="chk_avdec_version_positive",
            ),
            models.CheckConstraint(
                condition=(
                        Q(required_export_revision__isnull=True)
                        | Q(required_export_revision__gte=1)
                ),
                name="chk_avdec_export_rev_positive",
            ),
            models.UniqueConstraint(
                fields=["run", "listing_id_snapshot"],
                name="uniq_avdec_run_listing",
            ),
        ]


class AvitoAutomationAccountState(models.Model):
    """
    Состояние координации запусков автоматизаций одного Avito-аккаунта.

    Модель не заменяет AvitoAccount.sync_status: тот статус относится
    к синхронизации данных Avito, а этот — только к вычислению правил
    и выполнению действий.
    """

    class Status(models.TextChoices):
        IDLE = "idle", "Свободно"
        RUNNING = "running", "Выполняется"

    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="avito_automation_account_states",
    )
    avito_account = models.OneToOneField(
        "avitotask.AvitoAccount",
        on_delete=models.CASCADE,
        related_name="automation_state",
    )

    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.IDLE,
    )

    run_token = models.UUIDField(
        null=True,
        blank=True,
        editable=False,
    )
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["status", "lease_expires_at", "id"],
                name="idx_avstate_status_lease",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                        Q(
                            status="idle",
                            run_token__isnull=True,
                            heartbeat_at__isnull=True,
                            lease_expires_at__isnull=True,
                        )
                        | Q(
                    status="running",
                    run_token__isnull=False,
                    heartbeat_at__isnull=False,
                    lease_expires_at__isnull=False,
                    lease_expires_at__gt=F("heartbeat_at"),
                )
                ),
                name="chk_avstate_lease_consistent",
            ),
        ]
