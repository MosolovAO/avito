from django.contrib import admin
from .models import ProductOptions, Category


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('category', 'options_count', 'ad_generation_tasks_count')
    search_fields = ('category',)
    ordering = ('category',)

    def options_count(self, obj):
        """Количество опций, привязанных к категории"""
        return obj.options.count()

    options_count.short_description = "Опций"

    def ad_generation_tasks_count(self, obj):
        """Количество задач генерации в категории"""
        return obj.ad_generation_tasks.count()

    ad_generation_tasks_count.short_description = "Задач генерации"


@admin.register(ProductOptions)
class ProductOptionAdmin(admin.ModelAdmin):
    list_display = ('option_title_ru', 'get_categories', 'categories_count')
    search_fields = ('option_title_ru',)
    filter_horizontal = ('categories',)  # Горизонтальный фильтр для M2M
    ordering = ('option_title_ru',)

    def get_categories(self, obj):
        """Список категорий, к которым привязана опция"""
        categories = obj.categories.all()
        if categories.exists():
            return ", ".join(cat.category for cat in categories)
        return "Не привязана"

    get_categories.short_description = "Категории"

    def categories_count(self, obj):
        return obj.categories.count()

    categories_count.short_description = "Кол-во категорий"
