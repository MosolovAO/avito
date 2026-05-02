from django.urls import path

from .api_views import (
    WorkspaceInvitationListCreateView,
    WorkspaceInvitationRevokeView,
    WorkspaceMemberDetailView,
    WorkspaceMemberDisableView,
    WorkspaceMemberListView,
)

urlpatterns = [
    path(
        "<int:workspace_id>/members/",
        WorkspaceMemberListView.as_view(),
        name="workspace-members-list"
    ),
    path(
        "<int:workspace_id>/members/<int:membership_id>/",
        WorkspaceMemberDetailView.as_view(),
        name="workspace-members-detail",
    ),
    path(
        "<int:workspace_id>/members/<int:membership_id>/disable/",
        WorkspaceMemberDisableView.as_view(),
        name="workspace-members-disable",
    ),
    path(
        "<int:workspace_id>/invites/",
        WorkspaceInvitationListCreateView.as_view(),
        name="workspace-invitations-list-create",
        ),
    path(
        "<int:workspace_id>/invites/<int:invitation_id>/revoke/",
        WorkspaceInvitationRevokeView.as_view(),
        name="workspace-invitations-revoke",
    ),
]
