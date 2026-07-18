import calendar
import os
from uuid import uuid4

import secrets

from datetime import timedelta, datetime
from django.db import models

from django.utils import timezone as django_timezone

from django.db.models import JSONField, Q
from django.core.serializers.json import DjangoJSONEncoder

from django.core.exceptions import ValidationError
from django.db.models.functions import Lower, Trim


def ad_image_asset_upload_to(instance, filename):
    extension = os.path.splitext(filename)[1].lower()
    return f"ad-images/workspace-{instance.workspace_id}/{uuid4().hex}{extension}"


def generate_avito_account_feed_token():
    return secrets.token_urlsafe(32)


class MyJSONEncoder(DjangoJSONEncoder):
    """
    JSONField с кастомным encoder-ом для человекочитаемой кириллицы.
    Используется там, где важно сохранять русские значения в JSON без
    unicode-escape: выбранные опции, проекты, данные объявлений.
     """

    def __init__(self, *args, **kwargs):
        # Удаляем параметр ensure_ascii, если его кто-то уже задал
        kwargs.pop('ensure_ascii', None)
        # Заново проставляем ensure_ascii=False
        super().__init__(*args, ensure_ascii=False, **kwargs)


class MyJSONField(JSONField):
    def __init__(self, *args, **kwargs):
        kwargs['encoder'] = MyJSONEncoder
        super().__init__(*args, **kwargs)


RUS_TO_ENG_DAYS = {
    'Пн': 'Monday',
    'Вт': 'Tuesday',
    'Ср': 'Wednesday',
    'Чт': 'Thursday',
    'Пт': 'Friday',
    'Сб': 'Saturday',
    'Вс': 'Sunday',
}

# Для быстрого определения индекса дня недели (Monday=0, Sunday=6)
DAY_NAME_TO_INDEX = {name: i for i, name in enumerate(calendar.day_name)}


def product_image_upload_to(instance, filename):
    """
    Формирует путь загрузки изображения продукта.
    """

    # Получаем дату в формате день-месяц-год
    today = datetime.now().strftime('%d-%m-%y')
    # Генерируем имя файла: id продукта + оригинальное имя
    new_filename = f"{instance.product.id}_{filename}"
    # Возвращаем путь: uploads/today/pk_imagename.jpg
    return os.path.join('uploads', today, new_filename)


class Category(models.Model):
    category = models.CharField(max_length=100, unique=True, help_text="Название категории")

    class Meta:
        verbose_name = "Категория объявлений"
        verbose_name_plural = "Категории объявлений"
        ordering = ['category']

    def __str__(self):
        return self.category


class ProductOptions(models.Model):
    option_title_ru = models.CharField(max_length=255, help_text="Название опции (например, Цвет, Размер)")
    option_title_en = models.CharField(max_length=150, help_text="Параметр для автозагрузки")
    allow_multiple_options = models.BooleanField(default=False,
                                                 help_text="Можно ли указать несколько значений для этой опции")
    categories = models.ManyToManyField(
        Category,
        related_name='options',
        blank=True,
        help_text="Категории, в которых доступна эта опция",
    )

    class Meta:
        verbose_name = "Опция товара"
        verbose_name_plural = "Опции товаров"
        ordering = ['option_title_ru']
        constraints = [
            models.UniqueConstraint(
                Lower(Trim("option_title_en")),
                name="uniq_product_options_option_title_en_ci_trim",
            ),
        ]

    def clean(self):
        super().clean()

        self.option_title_ru = self.option_title_ru.strip()
        self.option_title_en = self.option_title_en.strip()

        duplicate_exists = ProductOptions.objects.filter(
            option_title_en__iexact=self.option_title_en,
        ).exclude(pk=self.pk).exists()

        if duplicate_exists:
            raise ValueError({
                "option_title_en": "Опция с таким параметром автозагрузки уже существует."
            })

    def __str__(self):
        return self.option_title_ru


# Новые таблицы в базе данных (Рефакторинг)
class AvitoAccount(models.Model):
    """Аккаунт Avito внутри workspace. Заменяет старую сущность Project."""

    class SyncStatus(models.TextChoices):
        IDLE = "idle", "Нет активной синхронизации"
        QUEUED = "queued", "Синхронизация в очереди"
        SYNCING = "syncing", "Синхронизация выполняется"
        ERROR = "error", "Ошибка синхронизации"

    class ExportStatus(models.TextChoices):
        CLEAN = "clean", "CSV актуален"
        DIRTY = "dirty", "CSV требует пересборки"
        QUEUED = "queued", "CSV в очереди"
        EXPORTING = "exporting", "CSV пересобирается"
        ERROR = "error", "Ошибка пересборки CSV"

    workspace = models.ForeignKey(
        'accounts.Workspace',
        on_delete=models.CASCADE,
        related_name="avito_accounts",
    )

    name = models.CharField(max_length=255)
    external_account_id = models.CharField(max_length=255, blank=True, null=True)

    client_id = models.CharField(max_length=255, blank=True)
    client_secret = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)
    export_status = models.CharField(
        max_length=20,
        choices=ExportStatus.choices,
        default=ExportStatus.CLEAN
    )
    export_file_path = models.CharField(max_length=255, blank=True, null=True)
    export_requested_at = models.DateTimeField(null=True, blank=True)
    export_started_at = models.DateTimeField(null=True, blank=True)

    sync_status = models.CharField(
        max_length=20,
        choices=SyncStatus.choices,
        default=SyncStatus.IDLE,
    )
    sync_requested_at = models.DateTimeField(null=True, blank=True)
    sync_started_at = models.DateTimeField(null=True, blank=True)

    last_sync_total_received = models.PositiveIntegerField(default=0)
    last_sync_created_listings = models.PositiveIntegerField(default=0)
    last_sync_updated_listings = models.PositiveIntegerField(default=0)

    last_synced_at = models.DateTimeField(null=True, blank=True)
    sync_error = models.TextField(null=True, blank=True)

    last_exported_at = models.DateTimeField(null=True, blank=True)
    export_error = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    feed_token = models.CharField(
        max_length=64,
        unique=True,
        null=True,
        blank=True,
        help_text="Публичный токен для CSV-фида автозагрузки Avito.",
    )

    class Meta:
        verbose_name = "Аккаунт Авито"
        verbose_name_plural = "Аккаунты Авито"
        ordering = ["name"]
        indexes = [
            models.Index(fields=['workspace', 'is_active'], name='idx_avacc_ws_active'),
            models.Index(fields=["workspace", "export_status"], name='idx_avacc_ws_export'),
            models.Index(fields=["workspace", "sync_status"], name="idx_avacc_ws_sync"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['workspace', 'name'],
                name='uniq_avacc_ws_name',
            ),
            models.UniqueConstraint(
                fields=['workspace', 'external_account_id'],
                condition=Q(external_account_id__isnull=False) & ~Q(external_account_id=""),
                name='uniq_avacc_ws_ext',
            ),
        ]

    @classmethod
    def generate_unique_feed_token(cls):
        token = generate_avito_account_feed_token()

        while cls.objects.filter(feed_token=token).exists():
            token = generate_avito_account_feed_token()

        return token

    def save(self, *args, **kwargs):
        if not self.feed_token:
            self.feed_token = self.generate_unique_feed_token()

        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class AdImageAsset(models.Model):
    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="ad_image_assets",
    )
    uploaded_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_ad_image_assets",
    )

    image = models.ImageField(upload_to=ad_image_asset_upload_to)
    url = models.URLField(max_length=1000, blank=True)
    original_filename = models.CharField(max_length=255, blank=True)
    content_type = models.CharField(max_length=100, blank=True)
    size_bytes = models.PositiveIntegerField(default=0)
    checksum = models.CharField(max_length=64, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "-created_at"], name="idx_adimg_ws_created"),
            models.Index(fields=["workspace", "checksum"], name="idx_adimg_ws_checksum"),
        ]

    def __str__(self):
        return self.original_filename or str(self.id)


class AdGenerationTask(models.Model):
    """Задача генерации объявлений. Заменяет Product."""

    class IntervalDays(models.IntegerChoices):
        EVERY_7_DAYS = 7, "Каждые 7 дней"
        EVERY_14_DAYS = 14, "Каждые 14 дней"
        EVERY_21_DAYS = 21, "Каждые 21 день"
        EVERY_28_DAYS = 28, "Каждые 28 дней"

    class LastRunStatus(models.TextChoices):
        IDLE = "idle", "Ожидает"
        RUNNING = "running", "Выполняется"
        SUCCESS = "success", "Успешно"
        ERROR = "error", "Ошибка"

    workspace = models.ForeignKey(
        'accounts.Workspace',
        on_delete=models.CASCADE,
        related_name='ad_generation_tasks',
    )
    avito_accounts = models.ManyToManyField(
        AvitoAccount,
        related_name='generation_tasks',
        blank=True,
    )

    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    url = models.URLField(blank=True, null=True)

    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ad_generation_tasks',
    )

    titles = MyJSONField(default=list, blank=True)
    descriptions = MyJSONField(default=dict, blank=True)
    main_image_assets = models.ManyToManyField(
        AdImageAsset,
        related_name="main_image_generation_tasks",
        blank=True,
    )
    additional_image_assets = models.ManyToManyField(
        AdImageAsset,
        related_name="additional_image_generation_tasks",
        blank=True,
    )
    addresses = MyJSONField(default=list, blank=True)

    base_data = MyJSONField(
        default=dict, blank=True, help_text="Общие поля объявления для CSV: цена, контакты, тип объявления и т.д.",
    )
    selected_options = MyJSONField(
        default=dict,
        blank=True,
        help_text="Выбранные параметры Avito для задачи генерации."
    )

    price = models.IntegerField(null=True, blank=True, default=0)
    price_min = models.IntegerField(null=True, blank=True, default=0)
    price_max = models.IntegerField(null=True, blank=True, default=0)
    price_step = models.IntegerField(null=True, blank=True, default=0)
    price_randomization_enabled = models.BooleanField(default=False)

    possible_combinations = models.IntegerField(null=True, blank=True, default=0)

    schedule = MyJSONField(
        default=dict,
        blank=True,
        help_text="Расписание вида {'Пн': '12:00', 'Ср': '12:00'} или нормализованный аналог.",
    )

    publication_interval_days = models.PositiveSmallIntegerField(
        choices=IntervalDays.choices,
        default=IntervalDays.EVERY_7_DAYS,
    )

    schedule_anchor_date = models.DateField(
        default=django_timezone.localdate,
        help_text="Дата-якорь для расчета недельных интервалов 1/2/3/4.",
    )
    schedule_timezone = models.CharField(
        max_length=64,
        default="Europe/Moscow",
        help_text="Timezone расписания задачи, например Europe/Moscow.",
    )

    next_update_time = models.DateTimeField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_successful_run_at = models.DateTimeField(null=True, blank=True)
    last_run_status = models.CharField(
        max_length=20,
        choices=LastRunStatus.choices,
        default=LastRunStatus.IDLE,
    )

    last_run_error = models.TextField(null=True, blank=True)
    options = models.ManyToManyField(
        ProductOptions,
        through="AdGenerationTaskOptionAssignment",
        related_name='ad_generation_tasks',
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Задача генерации объявлений"
        verbose_name_plural = "Задачи генерации объявлений"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=["workspace", "is_active", "next_update_time"], name="idx_adtask_ws_next"),
            models.Index(fields=["workspace", "-created_at"], name="idx_adtask_ws_created_at"),
        ]

    def __str__(self):
        return self.name


class AdGenerationTaskRun(models.Model):
    """Один запуск задачи автогенерации: ручной или по расписанию."""

    class TriggeredBy(models.TextChoices):
        MANUAL = "manual", "Ручной запуск"
        SCHEDULE = "schedule", "Запуск по расписанию"

    class Status(models.TextChoices):
        RUNNING = "running", "Выполняется"
        SUCCESS = "success", "Успешно"
        ERROR = "error", "Ошибка"

    workspace = models.ForeignKey(
        'accounts.Workspace',
        on_delete=models.CASCADE,
        related_name='ad_generation_task_runs',
    )
    task = models.ForeignKey(
        AdGenerationTask,
        on_delete=models.CASCADE,
        related_name='runs',
    )

    triggered_by = models.CharField(max_length=20, choices=TriggeredBy.choices)
    scheduled_for = models.DateTimeField(null=True, blank=True)

    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.RUNNING,
    )

    batch = models.ForeignKey(
        'AdBatch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='task_runs',
    )
    creative = models.ForeignKey(
        'AdCreative',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='task_runs',
    )

    publications_count = models.PositiveIntegerField(default=0)
    csv_export_ids = MyJSONField(default=list, blank=True)
    error = models.TextField(null=True, blank=True)

    class Meta:
        verbose_name = "Запуск задачи генерации"
        verbose_name_plural = "Запуски задач генерации"
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=["workspace", "-started_at"], name="idx_adtaskrun_ws_started"),
            models.Index(fields=["task", "-started_at"], name="idx_adtaskrun_task_started"),
            models.Index(fields=["task", "status"], name="idx_adtaskrun_task_status"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["task", "scheduled_for"],
                condition=Q(scheduled_for__isnull=False),
                name="uniq_adtaskrun_task_scheduled",
            )
        ]

    def __str__(self):
        return f"{self.task_id} / {self.triggered_by} / {self.status}"


class AdGenerationTaskOptionAssignment(models.Model):
    """Выбранные значения опций Avito для новой задачи генерации."""
    task = models.ForeignKey(AdGenerationTask, on_delete=models.CASCADE)
    option = models.ForeignKey(ProductOptions, on_delete=models.CASCADE)
    selected_value = MyJSONField(default=list, blank=True)

    class Meta:
        verbose_name = "Опция задачи генерации"
        verbose_name_plural = "Опции задач генерации"
        constraints = [
            models.UniqueConstraint(
                fields=['task', 'option'],
                name='uniq_adtask_option',
            )
        ]


class AdBatch(models.Model):
    """Одна операция создания объявлений: автогенерация, ручной масс-постинг или импорт."""

    class Source(models.TextChoices):
        AUTO = "auto", "Автогенерация"
        MANUAL = "manual", "Ручной масс-постинг"
        IMPORT = "import", "Импорт из Avito"
        AVITO_EXCEL = "avito_excel", "Импорт из XLSX Avito"

    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        COMPLETED = "completed", "Завершено"
        FAILED = "failed", "Ошибка"

    workspace = models.ForeignKey(
        'accounts.Workspace',
        on_delete=models.CASCADE,
        related_name='ad_batches',
    )

    task = models.ForeignKey(
        AdGenerationTask,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='batches',
    )

    source = models.CharField(max_length=20, choices=Source.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)

    created_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_ad_batches',
    )

    total_creatives = models.PositiveIntegerField(default=0)
    total_publications = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Пакет объявлений"
        verbose_name_plural = "Пакеты объявлений"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=["workspace", "-created_at"], name="idx_adbatch_ws_created"),
            models.Index(fields=["workspace", "task"], name="idx_adbatch_ws_task"),
            models.Index(fields=["workspace", "status"], name="idx_adbatch_ws_status"),
        ]

    def __str__(self):
        return f"{self.get_source_display()} #{self.id}"


class AvitoExcelImport(models.Model):
    class Status(models.TextChoices):
        PREVIEWED = "previewed", "Проверен"
        PROCESSING = "processing", "Обрабатывается"
        COMPLETED = "completed", "Завершен"
        FAILED = "failed", "Ошибка"

    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="avito_excel_imports",
    )
    avito_account = models.ForeignKey(
        AvitoAccount,
        on_delete=models.CASCADE,
        related_name="excel_imports",
    )
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="avito_excel_imports",
    )

    source_file = models.FileField(upload_to="avito-excel-imports/%Y/%m/%d/")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PROCESSING,
    )

    total_rows = models.PositiveIntegerField(default=0)
    created_creatives = models.PositiveIntegerField(default=0)
    created_publications = models.PositiveIntegerField(default=0)
    updated_publications = models.PositiveIntegerField(default=0)
    created_listings = models.PositiveIntegerField(default=0)
    updated_listings = models.PositiveIntegerField(default=0)

    report = MyJSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Импорт XLSX Avito"
        verbose_name_plural = "Импорты XLSX Avito"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "avito_account", "-created_at"], name="idx_avxls_ws_acc_created"),
            models.Index(fields=["workspace", "status"], name="idx_avxls_ws_status"),
        ]


class AdCreative(models.Model):
    """Уникальный вариант объявления без привязки к конкретному адресу."""

    class Source(models.TextChoices):
        AUTO = "auto", "Автогенерация"
        MANUAL = "manual", "Ручное создание"

    workspace = models.ForeignKey(
        'accounts.Workspace',
        on_delete=models.CASCADE,
        related_name='ad_creatives',
    )
    task = models.ForeignKey(
        AdGenerationTask,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='creatives',
    )
    option_category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ad_creatives",
        help_text="Конечная категория, по которой выбираются разрешённые опции",
    )
    batch = models.ForeignKey(
        AdBatch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='creatives',
    )

    source = models.CharField(max_length=20, choices=Source.choices)
    title = models.CharField(max_length=255)
    description = models.TextField()
    image_urls = MyJSONField(default=list, blank=True)

    base_data = MyJSONField(
        default=dict,
        blank=True,
        help_text="Общие CSV-поля этого варианта объявления.",
    )
    option_data = MyJSONField(
        default=dict,
        blank=True,
        help_text="Параметры Avito для этого варианта объявления.",
    )
    identity_hash = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        help_text="Хэш набора title/description/images/options для быстрой проверки дублей.",
    )

    dedupe_title = models.CharField(max_length=255, blank=True, db_index=True)
    dedupe_description = models.TextField(blank=True)
    dedupe_images_hash = models.CharField(max_length=64, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Креатив объявления"
        verbose_name_plural = "Креативы объявлений"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=["workspace", "task", "-created_at"], name="idx_adcreative_ws_task"),
            models.Index(fields=["workspace", "batch"], name="idx_adcreative_ws_batch"),
            models.Index(fields=["workspace", "identity_hash"], name="idx_adcreative_ws_hash"),
        ]

    def __str__(self):
        return self.title


class AdPublication(models.Model):
    """Конкретная публикация: креатив + адрес + аккаунт Avito. Это будущая строка CSV."""

    class Source(models.TextChoices):
        AUTO = "auto", "Автогенерация"
        MANUAL = "manual", "Ручной масс-постинг"
        AVITO_EXCEL = "avito_excel", "Импорт из XLSX Avito"

    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        ACTIVE = "active", "Активно"
        PAUSED = "paused", "Приостановлено"
        ARCHIVED = "archived", "Архив"
        ERROR = "error", "Ошибка"

    workspace = models.ForeignKey(
        'accounts.Workspace',
        on_delete=models.CASCADE,
        related_name='ad_publications',
    )
    avito_account = models.ForeignKey(
        AvitoAccount,
        on_delete=models.CASCADE,
        related_name='publications',
    )
    creative = models.ForeignKey(
        AdCreative,
        on_delete=models.CASCADE,
        related_name='publications',
    )
    task = models.ForeignKey(
        AdGenerationTask,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='publications',
    )
    batch = models.ForeignKey(
        AdBatch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='publications',
    )

    source = models.CharField(max_length=20, choices=Source.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)

    row_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Наш внутренний ID строки для CSV и последующего связывания с Avito.",
    )
    address = models.TextField()
    address_data = MyJSONField(default=dict, blank=True)

    overrides = MyJSONField(default=dict, blank=True,
                            help_text="Индивидуальные изменения этой публикации поверх AdCreative.base_data.", )
    published_at = models.DateTimeField(null=True, blank=True)
    last_exported_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Публикация объявления"
        verbose_name_plural = "Публикации объявлений"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=["workspace", "avito_account", "status"], name="idx_adpub_ws_acc_status"),
            models.Index(fields=["workspace", "creative"], name="idx_adpub_ws_creative"),
            models.Index(fields=["workspace", "task", "status"], name="idx_adpub_ws_task_status"),
            models.Index(fields=["workspace", "batch"], name="idx_adpub_ws_batch"),
            models.Index(fields=["workspace", "avito_account", "row_id"], name="idx_adpub_ws_row"),
            models.Index(fields=["workspace", "avito_account", "-created_at"], name="idx_adpub_ws_created"),
            models.Index(fields=["workspace", "avito_account"], name="idx_adpub_active_export",
                         condition=Q(status='active')),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "avito_account", "row_id"],
                condition=Q(row_id__isnull=False) & ~Q(row_id=""),
                name="uniq_adpub_row"
            )
        ]

    def __str__(self):
        return f"{self.creative.title} / {self.address}"


class AvitoListing(models.Model):
    """Реальное объявление на Avito, полученное после публикации или импорта по API."""

    class DesiredStatus(models.TextChoices):
        PUBLISH = "publish", "Публиковать"
        PAUSE = "pause", "Приостановить"
        ARCHIVE = "archive", "Архивировать"

    class Source(models.TextChoices):
        API = "api", "Импорт из Avito API"
        AVITO_EXCEL = "avito_excel", "Импорт из XLSX Avito"
        SERVICE = "service", "Создано сервисом"

    class ManagementStatus(models.TextChoices):
        OBSERVED = "observed", "Только наблюдаем"
        MANAGED = "managed", "Управляется сервисом"
        OUT_OF_SYNC = "out_of_sync", "Есть расхождения"

    workspace = models.ForeignKey(
        'accounts.Workspace',
        on_delete=models.CASCADE,
        related_name='avito_listings',
    )
    avito_account = models.ForeignKey(
        AvitoAccount,
        on_delete=models.CASCADE,
        related_name='avito_listings',
    )
    publication = models.OneToOneField(
        AdPublication,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='avito_listing',
    )
    option_category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="avito_listings",
        help_text=(
            "Категория для отбора опций. "
            "Для импортированного объявления первоначально не заполняется."
        ),
    )
    source = models.CharField(
        max_length=20,
        choices=Source.choices,
        default=Source.API,
    )
    management_status = models.CharField(
        max_length=20,
        choices=ManagementStatus.choices,
        default=ManagementStatus.OBSERVED,
    )

    desired_status = models.CharField(
        max_length=20,
        choices=DesiredStatus.choices,
        default=DesiredStatus.PUBLISH,
        help_text="Желаемое состояние объявления в следующем файле автозагрузки.",
    )

    avito_id = models.CharField(max_length=100)
    row_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Id строки автозагрузки из XLSX/CSV.",
    )
    status = models.CharField(max_length=50, blank=True, null=True)
    title = models.CharField(max_length=255, blank=True, null=True)
    description = models.TextField(blank=True)
    url = models.URLField(blank=True, null=True)
    address = models.TextField(blank=True)
    sheet_name = models.CharField(max_length=255, blank=True)
    category_path = models.TextField(blank=True)

    image_urls = MyJSONField(default=list, blank=True)

    base_data = MyJSONField(
        default=dict,
        blank=True,
        help_text="Нормализованные базовые поля объявления по option_title_en.",
    )
    option_data = MyJSONField(
        default=dict,
        blank=True,
        help_text="Нормализованные параметры Avito по option_title_en.",
    )
    raw_data = MyJSONField(
        default=dict,
        blank=True,
        help_text="Исходная строка XLSX с русскими названиями колонок.",
    )
    unmapped_data = MyJSONField(
        default=dict,
        blank=True,
        help_text="Колонки XLSX, для которых не найден ProductOptions.",
    )

    imported_payload = MyJSONField(default=dict, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Объявление Avito"
        verbose_name_plural = "Объявления Avito"
        ordering = ['-created_at']

        indexes = [
            models.Index(fields=["workspace", "avito_account", "avito_id"], name="idx_avlisting_acc_id"),
            models.Index(fields=["publication"], name="idx_avlisting_pub"),
            models.Index(fields=["workspace", "-last_seen_at"], name="idx_avlisting_ws_seen"),
            models.Index(fields=["workspace", "status"], name="idx_avlisting_ws_status"),
            models.Index(fields=["workspace", "avito_account", "source"], name="idx_avlisting_acc_source"),
            models.Index(fields=["workspace", "avito_account", "management_status"], name="idx_avlisting_acc_mgmt"),
            models.Index(fields=["workspace", "avito_account", "row_id"], name="idx_avlisting_acc_row"),
            models.Index(fields=["workspace", "avito_account", "desired_status"], name="idx_avlisting_acc_desired"),
            models.Index(
                fields=["workspace", "avito_account", "-last_seen_at", "-created_at"],
                name="idx_avlisting_acc_seen",
            ),
        ]

        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "avito_account", "avito_id"],
                name="uniq_avlisting_id"
            )
        ]

    def __str__(self):
        return str(self.avito_id)


class AvitoOAuthToken(models.Model):
    """OAuth-состояние подключенного аккаунта Avito."""

    class AuthType(models.TextChoices):
        AUTHORIZATION_CODE = "authorization_code", "Authorization Code"
        CLIENT_CREDENTIALS = "client_credentials", "Client Credentials"

    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="avito_oauth_tokens",
    )

    avito_account = models.OneToOneField(
        AvitoAccount,
        on_delete=models.CASCADE,
        related_name='oauth_tokens',
    )
    auth_type = models.CharField(
        max_length=32,
        choices=AuthType.choices,
        default=AuthType.AUTHORIZATION_CODE
    )
    access_token = models.TextField()
    refresh_token = models.TextField(blank=True, null=True)
    token_type = models.CharField(max_length=32, default="Bearer")
    scope = models.TextField(blank=True, null=True)
    expires_at = models.DateTimeField(blank=True, null=True)

    user_info = MyJSONField(default=dict, blank=True)
    last_verified_at = models.DateTimeField(blank=True, null=True)
    last_refreshed_at = models.DateTimeField(blank=True, null=True)
    last_error = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "OAuth-токен Avito"
        verbose_name_plural = "OAuth-токены Avito"
        indexes = [
            models.Index(fields=["workspace", "expires_at"], name="idx_avtoken_ws_exp"),
            models.Index(fields=["workspace", "auth_type"], name="idx_avtoken_ws_auth"),
        ]

    def __str__(self):
        return f"Avito token for {self.avito_account_id}"
