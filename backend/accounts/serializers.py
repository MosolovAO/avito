from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .permissions import get_role_permissions

from .models import Workspace, WorkspaceInvitation, WorkspaceMembership

User = get_user_model()

MANAGEABLE_WORKSPACE_ROLE_CHOICES = [
    choice
    for choice in WorkspaceMembership.Role.choices
    if choice[0] != WorkspaceMembership.Role.OWNER
]



class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name"]


class WorkspaceContextSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="workspace.id")
    name = serializers.CharField(source="workspace.name")
    slug = serializers.CharField(source="workspace.slug")
    role = serializers.CharField()
    status = serializers.CharField()
    permissions = serializers.SerializerMethodField()

    def get_permissions(self, membership):
        return get_role_permissions(membership.role)

class WorkspaceMemberSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = WorkspaceMembership
        fields = [
            "id",
            "user",
            "role",
            "status",
            "permissions",
            "joined_at",
            "created_at",
            "updated_at",
        ]
        
    def get_permissions(self, membership):
        if membership.status != WorkspaceMembership.Status.ACTIVE:
            return []
        return get_role_permissions(membership.role)
    
class WorkspaceMemberRoleUpdateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(
        choices=MANAGEABLE_WORKSPACE_ROLE_CHOICES
    )    
    
class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    workspace_name = serializers.CharField(max_length=255)

    def validate_email(self, value):
        email = User.objects.normalize_email_value(value)

        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError("Пользователь с таким email уже существует.")

        return email

    def validate_password(self, value):
        validate_password(value)
        return value

    def validate_workspace_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Название кабинета обязательно.")
        return value

    def _generate_unique_workspace_slug(self, workspace_name):
        base_slug = slugify(workspace_name) or "workspace"
        slug = base_slug
        counter = 1

        while Workspace.objects.filter(slug=slug).exists():
            counter += 1
            slug = f"{base_slug}-{counter}"

        return slug

    @transaction.atomic
    def create(self, validated_data):
        workspace_name = validated_data.pop("workspace_name")
        password = validated_data.pop("password")

        user = User.objects.create_user(password=password, **validated_data)

        workspace = Workspace.objects.create(name=workspace_name,
                                             slug=self._generate_unique_workspace_slug(workspace_name),
                                             owner=user)
        membership = WorkspaceMembership.objects.create(workspace=workspace,
                                                        user=user,
                                                        role=WorkspaceMembership.Role.OWNER,
                                                        status=WorkspaceMembership.Status.ACTIVE,
                                                        joined_at=timezone.now()
                                                        )
        refresh = RefreshToken.for_user(user)

        return {
            "user": user,
            "workspace": workspace,
            "membership": membership,
            "tokens": {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            },
        }

class WorkspaceInvitationSerializer(serializers.ModelSerializer):
    workspace = serializers.SerializerMethodField()
    invited_by = UserSerializer(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = WorkspaceInvitation
        fields = [
            "id",
            "workspace",
            "email",
            "role",
            "status",
            "invited_by",
            "expires_at",
            "accepted_at",
            "is_expired",
            "created_at",
            "updated_at",
        ]
        
    def get_workspace(self, invitation):
        return {
            "id": invitation.workspace_id,
            "name": invitation.workspace.name,
            "slug": invitation.workspace.slug,
        }
        
class WorkspaceInvitationCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(
        choices=MANAGEABLE_WORKSPACE_ROLE_CHOICES,
        default=WorkspaceMembership.Role.VIEWER
    )
    
    def validate_email(self, value):
        email = User.objects.normalize_email_value(value)
        workspace = self.context["workspace"]
        
        existing_user = User.objects.filter(email__iexact=email).first()
        
        if existing_user and WorkspaceMembership.objects.filter(
            workspace=workspace,
            user=existing_user,
            status=WorkspaceMembership.Status.ACTIVE,
        ).exists():
            raise serializers.ValidationError("Пользователь уже состоит в этом кабинете.")
        
        if WorkspaceInvitation.objects.filter(
            workspace=workspace,
            email__iexact=email,
            status=WorkspaceInvitation.Status.PENDING,
        ).exists():
            raise serializers.ValidationError("Для этого email уже есть активное приглашение.")
        
        return email
    
class WorkspaceInvitationRegisterSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    
    def validate_password(self, value):
        validate_password(value)
        return value