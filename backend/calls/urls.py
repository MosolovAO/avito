from django.urls import path

from calls.api_views import (
    CallAudioView,
    CallDailyReportView,
    CallListView,
    CallReportView,
    CallSyncStatusView,
)

urlpatterns = [
    path("", CallListView.as_view(), name="call-list"),
    path(
        "reports/daily/",
        CallDailyReportView.as_view(),
        name="call-daily-report",
    ),
    path("sync-status/", CallSyncStatusView.as_view(), name="call-sync-status"),
    path("<int:pk>/audio/", CallAudioView.as_view(), name="call-audio"),
    path("<int:pk>/report/", CallReportView.as_view(), name="call-report"),
]
