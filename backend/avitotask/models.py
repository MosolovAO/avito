import calendar
import os
import random
from datetime import timedelta, datetime
from django.db import models
from django.utils.timezone import now

from system import settings
from django.db.models import JSONField, Q
from django.core.serializers.json import DjangoJSONEncoder


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


# Проекты на аккаунте
class Project(models.Model):
    workspace = models.ForeignKey(
        'accounts.Workspace',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    project_name = models.CharField(max_length=100, null=True, blank=True, )

    def __str__(self):
        return self.project_name


# Уже созданные товары
class Product1(models.Model):
    """Уже сгенерированное объявление."""
    workspace = models.ForeignKey(
        'accounts.Workspace',
        on_delete=models.CASCADE,
        related_name='generated_products',
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=255, db_index=True, help_text="Заголовок продукта")
    urls = models.JSONField(default=list, blank=True, help_text="Список URL фото продукта")
    description = models.TextField(help_text="Описание продукта")
    created_date = models.DateField(auto_now_add=True, help_text="Дата добавления записи")
    task_id = models.IntegerField(null=True, blank=True, default=0)
    selected_option = MyJSONField(default=dict, blank=True, null=True)
    project_name = MyJSONField(default=list, blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=['task_id', 'created_date'], name='idx_product1_task_date'),
            models.Index(fields=['workspace', 'task_id', 'created_date'], name='idx_product1_ws_task_date'),
        ]


# Создание задачи для автоматического создания товаров
class Product(models.Model):
    """Задача генерации объявлений."""
    workspace = models.ForeignKey(
        'accounts.Workspace',
        on_delete=models.CASCADE,
        related_name='products',
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    url = models.URLField()
    price = models.IntegerField(null=True, blank=True, default=0)
    activate = models.BooleanField(default=True, null=True, help_text="Активна ли задача для выполнения")
    price_min = models.IntegerField(null=True, blank=True, default=0)
    price_max = models.IntegerField(null=True, blank=True, default=0)
    price_step = models.IntegerField(null=True, blank=True, default=0)
    possible_combinations = models.IntegerField(null=True, blank=True, default=0)
    price_randomization_enabled = models.BooleanField(
        default=False,
        help_text="Включена ли рандомизация цены"
    )
    schedule = models.JSONField(
        default=dict,
        blank=True,
        help_text="Расписание обновлений в формате {'Monday': '13:00', 'Saturday': '14:00'}"
    )
    next_update_time = models.DateTimeField(
        null=True, blank=True,
        help_text="Точное время следующего обновления цены"
    )
    last_updated = models.DateTimeField(auto_now=True)
    titles = models.JSONField(default=list, blank=True, help_text="Список заголовков для продукта")

    main_images = models.JSONField(default=list, blank=True, null=True, help_text="Основные изображения задачи")
    additional_images = models.JSONField(default=list, blank=True, null=True,
                                         help_text="Дополнительные изображения задачи")
    descriptions = models.JSONField(default=dict, blank=True, null=True, help_text="Описание задачи")
    addresses = models.JSONField(default=list, blank=True, null=True, help_text="Адреса продукта")
    options = models.ManyToManyField(
        'ProductOptions',
        through='ProductOptionAssignment',
        related_name='products',
        blank=True
    )
    selected_options = models.JSONField(default=dict, blank=True, help_text="Сохраненные опции и значения")
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='products',
                                 help_text="Категория товара")
    listingfee = models.CharField(max_length=10, blank=True, null=True)
    email = models.CharField(max_length=50, blank=True, null=True)
    contactphone = models.CharField(max_length=12, blank=True, null=True)
    managername = models.CharField(max_length=20, blank=True, null=True)
    avitostatus = models.CharField(max_length=10, blank=True, null=True)
    companyname = models.CharField(max_length=50, blank=True, null=True)
    contactmethod = models.CharField(max_length=50, blank=True, null=True)
    adtype = models.CharField(max_length=30, blank=True, null=True)
    availability = models.CharField(max_length=100, blank=True, null=True)
    projects = models.ManyToManyField(Project, related_name="projects")

    def update_next_update_time(self):
        """
        Обновляет `self.next_update_time` в соответствии с расписанием, хранящимся в `self.schedule`.
        """
        if not self.schedule:
            return

        now = datetime.now()
        current_day_index = now.weekday()  # Monday=0, Sunday=6

        # Конвертируем расписание в английские дни и время
        converted_schedule = {
            RUS_TO_ENG_DAYS[rus_day]: datetime.strptime(time_str, '%H:%M').time()
            for rus_day, time_str in self.schedule.items()
        }

        # Сортируем расписание по ближайшим дням относительно текущего, затем по времени
        sorted_schedule = sorted(
            converted_schedule.items(),
            key=lambda item: (
                (DAY_NAME_TO_INDEX[item[0]] - current_day_index) % 7,  # Приоритет по близости к текущему дню
                item[1]
            )
        )

        next_scheduled_datetime = None
        for day_name, schedule_time in sorted_schedule:
            day_index = DAY_NAME_TO_INDEX[day_name]
            days_diff = (day_index - current_day_index) % 7
            potential_date = now + timedelta(days=days_diff)
            potential_datetime = datetime.combine(potential_date.date(), schedule_time)

            if potential_datetime > now:
                next_scheduled_datetime = potential_datetime
                break

        # Если не найдено, берем первый элемент следующей недели
        if next_scheduled_datetime is None:
            first_day_name, first_time = sorted_schedule[0]
            days_diff = (DAY_NAME_TO_INDEX[first_day_name] - current_day_index) % 7 + 7
            next_date = now + timedelta(days=days_diff)
            next_scheduled_datetime = datetime.combine(next_date.date(), first_time)

        self.next_update_time = next_scheduled_datetime
        self.save()

    def update_selected_options(self):
        assignments = self.productoptionassignment_set.select_related('option').all()
        self.selected_options = {
            assignment.option.option_title_en: assignment.selected_value
            for assignment in assignments
        }
        self.save(update_fields=['selected_options'])

    def __str__(self):
        return self.name

    def random_title(self):
        return random.choice(self.titles)

    def random_description(self):
        return random.choice(list(self.descriptions.values()))

    def random_main_image(self):
        return random.choice(self.main_images)

    def random_additional_image(self, count=9):
        if len(self.additional_images) <= count:
            # Если в списке меньше или равно `count` элементов, возвращаем весь список
            return self.additional_images
            # Выбираем `count` уникальных элементов случайным образом
        return random.sample(self.additional_images, count)

    def title_count(self):
        return len(self.titles)


class ProductImage(models.Model):
    product = models.ForeignKey(Product, related_name='images', on_delete=models.CASCADE)
    image = models.ImageField(upload_to=product_image_upload_to)

    def __str__(self):
        return f"Image for {self.product.name}: {self.image.url}"


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

    # option_value = models.JSONField(default=list, blank=True, null=True,
    #                                help_text="Список значений опции (например, ['Красный', 'Синий', 'Зелёный'])")

    def __str__(self):
        return self.option_title_ru


class ProductOptionAssignment(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    option = models.ForeignKey(ProductOptions, on_delete=models.CASCADE)
    selected_value = models.JSONField(default=list, blank=True,
                                      help_text="Значения, введенные пользователем для этой опции")

    class Meta:
        unique_together = [('product', 'option')]


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
    last_synced_at = models.DateTimeField(null=True, blank=True)
    sync_error = models.TextField(null=True, blank=True)

    last_exported_at = models.DateTimeField(null=True, blank=True)
    export_error = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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

    def __str__(self):
        return self.name


class AdGenerationTask(models.Model):
    """Задача генерации объявлений. Заменяет Product."""

    class IntervalDays(models.IntegerChoices):
        EVERY_7_DAYS = 7, "Каждые 7 дней"
        EVERY_14_DAYS = 14, "Каждые 14 дней"
        EVERY_21_DAYS = 21, "Каждые 21 день"
        EVERY_28_DAYS = 28, "Каждые 28 дней"

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
    main_images = MyJSONField(default=list, blank=True)
    additional_images = MyJSONField(default=list, blank=True)
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

    schedule_cycle_started_at = models.DateTimeField(null=True, blank=True)
    next_update_time = models.DateTimeField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)

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


class AdCreative(models.Model):
    """Уникальный вариант объявления без привязки к конкретному адресу."""

    class Source(models.TextChoices):
        AUTO = "auto", "Автогенерация"
        MANUAL = "manual", "Ручное создание"
        IMPORT = "import", "Импорт из Avito"

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
        constraints = [
            models.UniqueConstraint(
                fields=['workspace', 'task', 'identity_hash'],
                condition=Q(identity_hash__isnull=False) & ~Q(identity_hash=""),
                name='uniq_adcreative_hash',
            )
        ]

    def __str__(self):
        return self.title


class AdPublication(models.Model):
    """Конкретная публикация: креатив + адрес + аккаунт Avito. Это будущая строка CSV."""

    class Source(models.TextChoices):
        AUTO = "auto", "Автогенерация"
        MANUAL = "manual", "Ручной масс-постинг"
        IMPORT = "import", "Импорт из Avito"

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

    avito_id = models.CharField(max_length=100)
    status = models.CharField(max_length=50, blank=True, null=True)
    title = models.CharField(max_length=255, blank=True, null=True)
    url = models.URLField(blank=True, null=True)

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
            models.Index(fields=["workspace", "status"], name="idx_avlisting_ws_status")
        ]

        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "avito_account", "avito_id"],
                name="uniq_avlisting_id"
            )
        ]

    def __str__(self):
        return str(self.avito_id)


class AvitoListingDailyStats(models.Model):
    """Дневная статистика объявления Avito."""
    workspace = models.ForeignKey(
        'accounts.Workspace',
        on_delete=models.CASCADE,
        related_name='avito_listing_daily_stats',
    )
    listing = models.ForeignKey(
        AvitoListing,
        on_delete=models.CASCADE,
        related_name='daily_stats',
    )

    date = models.DateField()
    views = models.PositiveIntegerField(default=0)
    contacts = models.PositiveIntegerField(default=0)
    favorites = models.PositiveIntegerField(default=0)
    calls = models.PositiveIntegerField(default=0)
    messages = models.PositiveIntegerField(default=0)

    raw_metrics = MyJSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Дневная статистика Авито"
        verbose_name_plural = "Дневная статистика Авито"
        ordering = ['-date']
        indexes = [
            models.Index(fields=["listing", "date"], name="idx_avstats_listing_date"),
            models.Index(fields=["workspace", "-date"], name="idx_avstats_ws_date")
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["listing", "date"],
                name="uniq_avstats_listing_date"
            )
        ]

    def __str__(self):
        return f"{self.listing.avito_id} / {self.date}"


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
