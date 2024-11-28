from django.contrib import admin
from .models import Product


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'next_update_time', 'last_updated')
    list_editable = ('next_update_time',)