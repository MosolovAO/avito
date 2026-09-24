from types import SimpleNamespace

from django.test import SimpleTestCase

from accounts.models import WorkspaceMembership
from accounts.permissions import membership_has_permission


MANAGE_AUTOMATIONS_PERMISSION = "manage_automations"


class AutomationPermissionTests(SimpleTestCase):
    def test_owner_and_admin_can_manage_automations(self):
        for role in (
            WorkspaceMembership.Role.OWNER,
            WorkspaceMembership.Role.ADMIN,
        ):
            with self.subTest(role=role):
                membership = SimpleNamespace(
                    role=role,
                    status=WorkspaceMembership.Status.ACTIVE,
                )

                self.assertTrue(
                    membership_has_permission(
                        membership,
                        MANAGE_AUTOMATIONS_PERMISSION,
                    )
                )

    def test_other_roles_cannot_manage_automations(self):
        for role in (
            WorkspaceMembership.Role.MANAGER,
            WorkspaceMembership.Role.ANALYST,
            WorkspaceMembership.Role.VIEWER,
        ):
            with self.subTest(role=role):
                membership = SimpleNamespace(
                    role=role,
                    status=WorkspaceMembership.Status.ACTIVE,
                )

                self.assertFalse(
                    membership_has_permission(
                        membership,
                        MANAGE_AUTOMATIONS_PERMISSION,
                    )
                )
