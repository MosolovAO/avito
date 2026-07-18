from rest_framework.exceptions import (
    PermissionDenied,
    ValidationError
)

from accounts.models import WorkspaceMembership
from accounts.permissions import membership_has_permission


def get_request_membership(request, required_permission=None):
    memberships = WorkspaceMembership.objects.select_related("workspace").filter(
        user=request.user,
        status=WorkspaceMembership.Status.ACTIVE,
    )

    workspace_id = request.headers.get("X-Workspace-Id")

    if workspace_id:
        membership = memberships.filter(workspace_id=workspace_id).first()

        if membership is None:
            raise PermissionDenied("У вас нет доступа к этому кабинету.")
    else:
        count = memberships.count()

        if count == 0:
            raise PermissionDenied("У пользователя нет активного кабинета.")

        if count > 1:
            raise ValidationError({
                "workspace": "Передайте X-Workspace-Id, потому что у пользователя несколько кабинетов."
            })

        membership = memberships.first()

    if required_permission and not membership_has_permission(membership, required_permission):
        raise PermissionDenied("Недостаточно прав для выполнения действия.")

    return membership


def get_request_workspace(request, required_permission=None):
    return get_request_membership(request, required_permission).workspace
