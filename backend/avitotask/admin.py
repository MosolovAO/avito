from django.contrib import admin
from .models import Product, ProductOptions, Project, Category, ProductOptionAssignment


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('category', 'options_count', 'products_count')
    search_fields = ('category',)
    ordering = ('category',)

    def options_count(self, obj):
        """Количество опций, привязанных к категории"""
        return obj.options.count()

    options_count.short_description = "Опций"

    def products_count(self, obj):
        """Количество товаров в категории"""
        return obj.products.count()

    products_count.short_description = "Товаров"


@admin.register(ProductOptions)
class ProductOptionAdmin(admin.ModelAdmin):
    list_display = ('option_title_ru', 'get_categories', 'categories_count')
    search_fields = ('option_title_ru',)
    filter_horizontal = ('categories',)  # Горизонтальный фильтр для M2M
    ordering = ('option_title_ru',)

    def get_categories(self, obj):
        """Список категорий, к которым привязана опция"""
        categories = Category.objects.all()
        if categories.exists():
            return ", ".join(cat.category for cat in categories)
        return "Не привязана"

    get_categories.short_description = "Категории"

    def categories_count(self, obj):
        return obj.categories.count()

    categories_count.short_description = "Кол-во категорий"

    def save_model(self, request, obj, form, change):
        # Сохраняем объект сначала
        super().save_model(request, obj, form, change)
        # Получаем категории из form.cleaned_data
        categories = form.cleaned_data.get('categories')
        # Проверяем наличие категорий после сохранения M2M
        if not categories or categories.count() == 0:
            from django.core.exceptions import ValidationError
            raise ValidationError("Опция должна быть привязана хотя бы к одной категории")


# ==================== ProductOptionAssignment ====================

class ProductOptionAssignmentInline(admin.TabularInline):
    """Inline для отображения опций товара в админке Product"""
    model = ProductOptionAssignment
    extra = 1
    autocomplete_fields = ('option',)
    verbose_name = "Опция товара"
    verbose_name_plural = "Опции товара"


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'price', 'next_update_time', 'last_updated', 'activate')
    list_editable = ('category', 'next_update_time', 'activate')
    list_filter = ('category', 'activate', 'projects')
    search_fields = ('name', 'titles')
    filter_horizontal = ('projects',)
    ordering = ('-last_updated',)

    # Подключаем inline для опции
    inlines = [ProductOptionAssignmentInline]

    fieldsets = (
        ('Основная информация', {
            'fields': ('name', 'category', 'url', 'price', 'price_min', 'price_max', 'price_step', 'activate')
        }),
        ('Контент', {
            'fields': ('titles', 'main_images', 'additional_images', 'descriptions', 'addresses')
        }),
        ('Расписание', {
            'fields': ('schedule', 'next_update_time'),
            'classes': ('collapse',)  # Сворачиваемая секция
        }),
        ('Авито параметры', {
            'fields': ('listingfee', 'email', 'contactphone', 'managername',
                       'avitostatus', 'companyname', 'contactmethod', 'adtype', 'availability'),
            'classes': ('collapse',)
        }),
        ('Проекты и опции', {
            'fields': ('projects', 'selected_options'),
            'classes': ('collapse',)
        })
    )

    def save_model(self, request, obj, form, change):
        """Сохраняет товар и обновляет selected_options"""
        super().save_model(request, obj, form, change)
        obj.update_selected_options()


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('project_name',)
