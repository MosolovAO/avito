import calendar
import os
import random
from datetime import timedelta, datetime
from django.db import models

from system import settings

RUS_TO_ENG_DAYS = {
    'Пн': 'Monday',
    'Вт': 'Tuesday',
    'Ср': 'Wednesday',
    'Чт': 'Thursday',
    'Пт': 'Friday',
    'Сб': 'Saturday',
    'Вс': 'Sunday',
}


def product_image_upload_to(instance, filename):
    # Получаем дату в формате день-месяц-год
    today = datetime.now().strftime('%d-%m-%y')
    # Генерируем имя файла: id продукта + оригинальное имя
    new_filename = f"{instance.product.id}_{filename}"
    # Возвращаем путь: uploads/today/pk_imagename.jpg
    return os.path.join('uploads', today, new_filename)


class Project(models.Model):
    project_name = models.CharField(max_length=100, null=True, blank=True, )

    def __str__(self):
        return self.project_name


class Product1(models.Model):
    title = models.CharField(max_length=255, db_index=True, help_text="Заголовок продукта")
    urls = models.JSONField(default=list, blank=True, help_text="Список URL фото продукта")
    description = models.TextField(help_text="Описание продукта")
    created_date = models.DateField(auto_now_add=True, help_text="Дата добавления записи")
    task_id = models.IntegerField(null=True, blank=True, default=0)


class Product(models.Model):
    name = models.CharField(max_length=255)
    url = models.URLField()
    price = models.IntegerField(null=True, blank=True, default=0)
    price_min = models.IntegerField(null=True, blank=True, default=0)
    price_max = models.IntegerField(null=True, blank=True, default=0)
    price_step = models.IntegerField(null=True, blank=True, default=0)
    possible_combinations = models.IntegerField(null=True, blank=True, default=0)
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

    category = models.CharField(max_length=50, null=True, blank=True)
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
        Обновляет `next_update_time` в соответствии с расписанием.
        """
        if not self.schedule:
            return

        now = datetime.now()
        current_day_eng = now.strftime('%A')  # Английское название текущего дня недели
        current_time = now.time()

        # Преобразуем расписание в английский формат
        schedule_eng = {
            RUS_TO_ENG_DAYS[rus_day]: time for rus_day, time in self.schedule.items()
        }

        # Сортируем дни недели и время
        sorted_schedule = sorted(
            [(day, datetime.strptime(time, '%H:%M').time()) for day, time in schedule_eng.items()],
            key=lambda x: (current_day_eng != x[0], x[1])
        )

        for day, time in sorted_schedule:
            day_index = list(calendar.day_name).index(day)
            current_index = now.weekday()

            if day_index > current_index or (day_index == current_index and time > current_time):
                next_day = now + timedelta(days=(day_index - current_index))
                self.next_update_time = datetime.combine(next_day, time)
                self.save()
                return

        # Если ближайшее время в следующей неделе
        first_day, first_time = sorted_schedule[0]
        next_day = now + timedelta(days=(7 - current_index + list(calendar.day_name).index(first_day)))
        self.next_update_time = datetime.combine(next_day, first_time)
        self.save()

    def update_selected_options(self):
        assignments = self.productoptionassignment_set.select_related('option').all()
        self.selected_options = {
            assignment.option.option_title: assignment.selected_value
            for assignment in assignments
        }
        self.save()

    def __str__(self):
        return self.name

    def random_title(self):
        return random.choice(self.titles)

    def random_description(self):
        return random.choice(list(self.descriptions.values()))

    def random_main_image(self):
        return f"localhost:8001{random.choice(self.main_images)}"

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
    option_title = models.CharField(max_length=255, unique=True, help_text="Название опции (например, Цвет, Размер)")
    option_value = models.JSONField(default=list, blank=True, null=True,
                                    help_text="Список значений опции (например, ['Красный', 'Синий', 'Зелёный'])")

    def __str__(self):
        return self.option_title


class ProductOptionAssignment(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    option = models.ForeignKey(ProductOptions, on_delete=models.CASCADE)
    selected_value = models.CharField(max_length=255, help_text="Выбранное значение опции")
