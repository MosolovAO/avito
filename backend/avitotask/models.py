import calendar
import os
import random
from datetime import timedelta, datetime
from django.db import models
from django.utils.timezone import now

from system import settings
from django.db.models import JSONField
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
    project_name = models.CharField(max_length=100, null=True, blank=True, )

    def __str__(self):
        return self.project_name


# Уже созданные товары
class Product1(models.Model):
    """Уже сгенерированное объявление."""
    title = models.CharField(max_length=255, db_index=True, help_text="Заголовок продукта")
    urls = models.JSONField(default=list, blank=True, help_text="Список URL фото продукта")
    description = models.TextField(help_text="Описание продукта")
    created_date = models.DateField(auto_now_add=True, help_text="Дата добавления записи")
    task_id = models.IntegerField(null=True, blank=True, default=0)
    selected_option = MyJSONField(default=dict, blank=True, null=True)
    project_name = MyJSONField(default=list, blank=True, null=True)


# Создание задачи для автоматического создания товаров
class Product(models.Model):
    """Задача генерации объявлений."""
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
