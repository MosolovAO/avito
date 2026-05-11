from django.urls import path

from avitotask.avito_api_views import (
    AvitoAccountImportDailyStatsView,
    AvitoAccountImportListingsView,
    AvitoAccountLinkPublicationsView,
    AvitoAccountVerifyConnectionView,
    AvitoAccountConnectByCredentialsView
)

urlpatterns = [
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
    path(
        "accounts/<int:avito_account_id>/verify-connection/",
        AvitoAccountVerifyConnectionView.as_view(),
        name="avito-account-verify-connection",
    ),
    path(
        "accounts/<int:avito_account_id>/connect-by-credentials/",
        AvitoAccountConnectByCredentialsView.as_view(),
        name="avito-account-connect-by-credentials",
    ),
]
