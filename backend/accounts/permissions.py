from .models import WorkspaceMembership


class WorkspacePermission:
    MANAGE_WORKSPACE = "manage_workspace"
    MANAGE_BILLING = "manage_billing"
    MANAGE_USERS = "manage_users"

    MANAGE_ADS = "manage_ads"
    VIEW_ADS = "view_ads"

    MANAGE_TASKS = "manage_tasks"
    VIEW_TASKS = "view_tasks"

    MANAGE_AVITO_ACCOUNTS = "manage_avito_accounts"
    MANAGE_PROMOTION = "manage_promotion"

    MANAGE_CHATS = "manage_chats"
    VIEW_CHATS = "view_chats"

    VIEW_ANALYTICS = "view_analytics"
    VIEW_DETAILED_ANALYTICS = "view_detailed_analytics"


ROLE_PERMISSIONS = {
    WorkspaceMembership.Role.OWNER: {
        WorkspacePermission.MANAGE_WORKSPACE,
        WorkspacePermission.MANAGE_BILLING,
        WorkspacePermission.MANAGE_USERS,
        WorkspacePermission.MANAGE_ADS,
        WorkspacePermission.VIEW_ADS,
        WorkspacePermission.MANAGE_TASKS,
        WorkspacePermission.VIEW_TASKS,
        WorkspacePermission.MANAGE_AVITO_ACCOUNTS,
        WorkspacePermission.MANAGE_PROMOTION,
        WorkspacePermission.MANAGE_CHATS,
        WorkspacePermission.VIEW_CHATS,
        WorkspacePermission.VIEW_ANALYTICS,
        WorkspacePermission.VIEW_DETAILED_ANALYTICS,
    },
    WorkspaceMembership.Role.ADMIN: {
        WorkspacePermission.MANAGE_USERS,
        WorkspacePermission.MANAGE_ADS,
        WorkspacePermission.VIEW_ADS,
        WorkspacePermission.MANAGE_TASKS,
        WorkspacePermission.VIEW_TASKS,
        WorkspacePermission.MANAGE_AVITO_ACCOUNTS,
        WorkspacePermission.MANAGE_PROMOTION,
        WorkspacePermission.MANAGE_CHATS,
        WorkspacePermission.VIEW_CHATS,
        WorkspacePermission.VIEW_ANALYTICS,
        WorkspacePermission.VIEW_DETAILED_ANALYTICS,
    },
    WorkspaceMembership.Role.MANAGER: {
        WorkspacePermission.MANAGE_ADS,
        WorkspacePermission.VIEW_ADS,
        WorkspacePermission.MANAGE_TASKS,
        WorkspacePermission.VIEW_TASKS,
        WorkspacePermission.MANAGE_CHATS,
        WorkspacePermission.VIEW_CHATS,
        WorkspacePermission.VIEW_ANALYTICS,
    },
    WorkspaceMembership.Role.ANALYST: {
        WorkspacePermission.VIEW_ADS,
        WorkspacePermission.VIEW_TASKS,
        WorkspacePermission.VIEW_ANALYTICS,
        WorkspacePermission.VIEW_DETAILED_ANALYTICS,
    },
    WorkspaceMembership.Role.VIEWER: {
        WorkspacePermission.VIEW_ADS,
        WorkspacePermission.VIEW_TASKS,
        WorkspacePermission.VIEW_ANALYTICS,
    },
}


def get_role_permissions(role):
    return sorted(ROLE_PERMISSIONS.get(role, set()))


def membership_has_permission(membership, permission):
    if membership is None:
        return False
    if membership.status != WorkspaceMembership.Status.ACTIVE:
        return False

    return permission in ROLE_PERMISSIONS.get(membership.role, set())
