from django.urls import path

from analytics.api_views import (
    AvitoAccountImportDailyStatsView,
    AvitoAccountListingStatsView,
)

urlpatterns = [
    path(
        "avito-accounts/<int:avito_account_id>/import-daily-stats/",
        AvitoAccountImportDailyStatsView.as_view(),
        name="analytics-avito-account-import-daily-stats",
    ),
    path(
        "avito-accounts/<int:avito_account_id>/listing-stats/",
        AvitoAccountListingStatsView.as_view(),
        name="analytics-avito-account-listing-stats",
    ),
]