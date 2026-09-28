from django.urls import path

from calls.api_views import CallAudioView, CallListView, CallSyncStatusView


urlpatterns = [
    path("", CallListView.as_view(), name="call-list"),
    path("sync-status/", CallSyncStatusView.as_view(), name="call-sync-status"),
    path("<int:pk>/audio/", CallAudioView.as_view(), name="call-audio"),
]