from django.urls import path

from .api_views import (
    WorkspaceInvitationAcceptView,
    WorkspaceInvitationPublicDetailView,
    WorkspaceInvitationRegisterView,
)

urlpatterns = [
    path(
        "<str:token>/",
        WorkspaceInvitationPublicDetailView.as_view(),
        name="workspace-invitation-detail",
    ),
    path(
        "<str:token>/accept/",
        WorkspaceInvitationAcceptView.as_view(),
        name="workspace-invitation-accept",
    ),
    path(
        "<str:token>/register/",
        WorkspaceInvitationRegisterView.as_view(),
        name="workspace-invitation-register",
    ),
]
