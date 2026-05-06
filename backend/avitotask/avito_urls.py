from django.urls import path

from avitotask.avito_api_views import (
    AvitoAccountImportDailyStatsView,
    AvitoAccountImportListingsView,
    AvitoAccountLinkPublicationsView,
    AvitoOAuthCallbackView,
    AvitoOAuthStartView,
)

urlpatterns = [
    path(
        "accounts/<int:avito_account_id>/oauth/start/",
        AvitoOAuthStartView.as_view(),
        name="avito-oauth-start",
    ),
    path(
        "oauth/callback/",
        AvitoOAuthCallbackView.as_view(),
        name="avito-oauth-callback",
    ),
    path(
        "accounts/<int:avito_account_id>/import-listings/",
        AvitoAccountImportListingsView.as_view(),
        name="avito-account-import-listings",
    ),
    path(
        "accounts/<int:avito_account_id>/link-publications/",
        AvitoAccountLinkPublicationsView.as_view(),
        name="avito-account-link-publications",
    ),
    path(
        "accounts/<int:avito_account_id>/import-daily-stats/",
        AvitoAccountImportDailyStatsView.as_view(),
        name="avito-account-import-daily-stats",
    ),
]
