from django.contrib import admin

from analytics.models import AvitoListingDailyStats


@admin.register(AvitoListingDailyStats)
class AvitoListingDailyStatsAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "workspace",
        "listing",
        "date",
        "views",
        "contacts",
        "favorites",
        "total_spend",
        "updated_at",
    )
    list_filter = ("workspace", "date")
    search_fields = ("listing__avito_id", "listing__title")
    readonly_fields = ("created_at", "updated_at")