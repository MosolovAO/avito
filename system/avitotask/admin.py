from django.contrib import admin
from .models import Product, ProductOptions, Project


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'next_update_time', 'last_updated')
    list_editable = ('next_update_time',)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('project_name',)


@admin.register(ProductOptions)
class ProductOptionsAdmin(admin.ModelAdmin):
    list_display = ('option_title', 'formatted_option_value')  # Отображение полей в списке
    search_fields = ('option_title',)  # Поле для поиска по заголовку свойства

    def formatted_option_value(self, obj):
        """Отображает JSON-поле в читаемом формате"""
        if isinstance(obj.option_value, list):
            return ", ".join(str(v) for v in obj.option_value)
        return str(obj.option_value)

    formatted_option_value.short_description = "Свойства"  # Название колонки в админке
