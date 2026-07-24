from django.contrib import admin

from analytics.models import (
    AvitoListingDailyStats,
    AvitoStatsSyncState,
)


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


@admin.register(AvitoStatsSyncState)
class AvitoStatsSyncStateAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "workspace",
        "avito_account",
        "status",
        "coverage_from",
        "coverage_to",
        "last_successful_at",
        "updated_at",
    )
    list_filter = ("status", "workspace")
    search_fields = (
        "avito_account__name",
        "avito_account__external_account_id",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
    )
