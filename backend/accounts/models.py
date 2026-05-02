import secrets
from datetime import timedelta

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.mail import send_mail
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone


class UserManager(BaseUserManager):
    """Управление email manager"""

    def normalize_email_value(self, email):
        if not email:
            raise ValueError('Email должен быть заполнен')
        return self.normalize_email(email).strip().lower()

    def create_user(self, email, password=None, **extra_fields):
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)

        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()

        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email=email, password=password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """Application user. Uses email as login."""
    email = models.EmailField(max_length=255, unique=True, db_index=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
        constraints = [
            models.UniqueConstraint(
                Lower('email'),
                name='unique_user_email_lower',
            ),
        ]

    def __str__(self):
        return self.email

    def clean(self):
        super().clean()
        self.email = User.objects.normalize_email_value(self.email)

    def get_full_name(self):
        full_name = f"{self.first_name} {self.last_name}".strip()
        return full_name or self.email

    def get_short_name(self):
        return self.first_name or self.email

    def email_user(self, subject, message, from_email=None, **kwargs):
        send_mail(subject, message, from_email, [self.email], **kwargs)


class Workspace(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, db_index=True)
    owner = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="owned_workspaces"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Workspace"
        verbose_name_plural = "Workspaces"
        ordering = ["name"]

    def __str__(self):
        return self.name


class WorkspaceMembership(models.Model):
    """User access to a workspace."""

    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        MANAGER = "manager", "Manager"
        ANALYST = "analyst", "Analyst"
        VIEWER = "viewer", "Viewer"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INVITED = "invited", "Invited"
        DISABLED = "disabled", "Disabled"

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="workspace_memberships",
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.VIEWER,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    invited_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_workspace_invitations",
    )
    joined_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Workspace membership"
        verbose_name_plural = "Workspace memberships"
        ordering = ["workspace", "user"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "user"],
                name="uniq_workspace_user_membership",
            ),
            models.UniqueConstraint(
                fields=["workspace"],
                condition=Q(role="owner", status="active"),
                name="uniq_active_owner_per_workspace"
            ),
        ]

    def __str__(self):
        return f"{self.user.email} -> {self.workspace.name} - ({self.role})"

    @property
    def is_active_member(self):
        return self.status == self.Status.ACTIVE


def default_invitation_expires_at():
    return timezone.now() + timedelta(days=7)


def generate_invitation_token():
    return secrets.token_urlsafe(32)


class WorkspaceInvitation(models.Model):
    """Invitation to join a workspace."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REVOKED = "revoked", "Revoked"
        EXPIRED = "expired", "Expired"

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="invitations",
    )
    email = models.EmailField(db_index=True)
    role = models.CharField(
        max_length=20,
        choices=WorkspaceMembership.Role.choices,
        default=WorkspaceMembership.Role.VIEWER
    )
    token = models.CharField(
        max_length=128,
        unique=True,
        default=generate_invitation_token,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    invited_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="created_workspace_invitations",
    )

    expires_at = models.DateTimeField(default=default_invitation_expires_at)
    accepted_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Workspace Invitation"
        verbose_name_plural = "Workspace Invitations"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "email"],
                condition=Q(status="pending"),
                name="uniq_pending_workspace_invitation_email",
            )
        ]

    def __str__(self):
        return f"{self.email} -> {self.workspace.name} ({self.status})"

    def clean(self):
        super().clean()
        self.email = User.objects.normalize_email_value(self.email)

    @property
    def is_expired(self):
        return self.status == self.Status.PENDING and self.expires_at <= timezone.now()
