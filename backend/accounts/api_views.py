from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import PermissionDenied, ValidationError

from .models import WorkspaceMembership
from .permissions import WorkspacePermission, membership_has_permission
from .serializers import (
    RegisterSerializer,
    UserSerializer,
    WorkspaceContextSerializer,
    WorkspaceInvitationCreateSerializer,
    WorkspaceInvitationRegisterSerializer,
    WorkspaceInvitationSerializer,
    WorkspaceMemberSerializer,
    WorkspaceMemberRoleUpdateSerializer,
)

from django.db import transaction
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from .models import WorkspaceInvitation, WorkspaceMembership

User = get_user_model()

def set_refresh_cookie(response, refresh_token):
    response.set_cookie(
        key=settings.AUTH_REFRESH_COOKIE_NAME,
        value=str(refresh_token),
        httponly=True,
        secure=settings.AUTH_REFRESH_COOKIE_SECURE,
        samesite=settings.AUTH_REFRESH_COOKIE_SAMESITE,
        path=settings.AUTH_REFRESH_COOKIE_PATH,
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
    )


def delete_refresh_cookie(response):
    response.delete_cookie(
        key=settings.AUTH_REFRESH_COOKIE_NAME,
        path=settings.AUTH_REFRESH_COOKIE_PATH,
        samesite=settings.AUTH_REFRESH_COOKIE_SAMESITE,
    )


class RegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = serializer.save()

        response = Response(
            {
                "user": UserSerializer(result["user"]).data,
                "workspace": {
                    "id": result["workspace"].id,
                    "name": result["workspace"].name,
                    "slug": result["workspace"].slug,
                },
                "membership": {
                    "role": result["membership"].role,
                    "status": result["membership"].status,
                },
                "access": result["tokens"]["access"],
            },
            status=status.HTTP_201_CREATED,
        )

        set_refresh_cookie(response, result["tokens"]["refresh"])
        return response


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        membership = (
            WorkspaceMembership.objects.select_related("workspace").filter(
                user=request.user, status=WorkspaceMembership.Status.ACTIVE,
            ).order_by("workspace__name")
        )

        return Response({
            "user": UserSerializer(request.user).data,
            "workspaces": WorkspaceContextSerializer(membership, many=True).data
        })


class CookieLoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = TokenObtainPairSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        response = Response({"access": serializer.validated_data["access"]})
        set_refresh_cookie(response, serializer.validated_data["refresh"])
        return response


class CookieRefreshView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        refresh = request.COOKIES.get(settings.AUTH_REFRESH_COOKIE_NAME)
        if not refresh:
            return Response(
                {"detail": "Refresh token cookie is missing."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        serializer = TokenRefreshSerializer(data={"refresh": refresh})
        serializer.is_valid(raise_exception=True)

        response = Response({"access": serializer.validated_data["access"]})

        rotated_refresh = serializer.validated_data.get("refresh")
        if rotated_refresh:
            set_refresh_cookie(response, rotated_refresh)

        return response


class CookieLogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        response = Response(status=status.HTTP_204_NO_CONTENT)
        refresh = request.COOKIES.get(settings.AUTH_REFRESH_COOKIE_NAME)

        if refresh:
            try:
                RefreshToken(refresh).blacklist()
            except TokenError:
                pass

        delete_refresh_cookie(response)
        return response

def get_manage_users_membership(request, workspace_id):
    membership = (
        WorkspaceMembership.objects
        .select_related("workspace")
        .filter(
            user=request.user,
            workspace_id=workspace_id,
            status=WorkspaceMembership.Status.ACTIVE,
        )
        .first()
    )
    
    if membership is None:
        raise PermissionDenied("У вас нет доступа к этому кабинету.")

    if not membership_has_permission(membership, WorkspacePermission.MANAGE_USERS):
        raise PermissionDenied("Недостаточно прав для управления пользователями.")

    return membership

def get_workspace_member_or_404(workspace_id, membership_id):
    return get_object_or_404(
        WorkspaceMembership.objects.select_related("user", "workspace"),
        id=membership_id,
        workspace_id=workspace_id
    )
    
def validate_member_can_changed(target_membership, current_user):
    if target_membership.role == WorkspaceMembership.Role.OWNER:
        raise ValidationError("Владельца кабинета нельзя изменить или отключить.")
    
    if target_membership.user_id == current_user.id:
        raise ValidationError("Нельзя изменить собственную роль или отключить самого себя.")

    if target_membership.status != WorkspaceMembership.Status.ACTIVE:
        raise ValidationError("Можно управлять только активными участниками.")

class WorkspaceMemberListView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request, workspace_id):
        get_manage_users_membership(request, workspace_id)
        
        memberships = (
            WorkspaceMembership.objects
            .select_related("user")
            .filter(workspace_id=workspace_id)
            .order_by("user__email")
        )
        
        return Response(WorkspaceMemberSerializer(memberships, many=True).data)

class WorkspaceMemberDetailView(APIView):
    permission_classes = [IsAuthenticated]
    
    @transaction.atomic
    def patch(self, request, workspace_id, membership_id):
        get_manage_users_membership(request, workspace_id)
        
        target_membership = (
            WorkspaceMembership.objects
            .select_for_update()
            .select_related("user", "workspace")
            .get(id=membership_id, workspace_id=workspace_id)
        )
        
        validate_member_can_changed(target_membership, request.user)
        
        serializer = WorkspaceMemberRoleUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        target_membership.role = serializer.validated_data["role"]
        target_membership.save(update_fields=["role", "updated_at"])
        
        return Response(WorkspaceMemberSerializer(target_membership).data)
    
class WorkspaceMemberDisableView(APIView):
    permission_classes = [IsAuthenticated]
    
    @transaction.atomic
    def post(self, request, workspace_id, membership_id):
        get_manage_users_membership(request, workspace_id)
        
        target_membership = (
            WorkspaceMembership.objects
            .select_for_update()
            .select_related("user", "workspace")
            .get(id=membership_id, workspace_id=workspace_id)
        )
        
        validate_member_can_changed(target_membership, request.user)
        
        target_membership.status = WorkspaceMembership.Status.DISABLED
        target_membership.save(update_fields=["status", "updated_at"])
        
        return Response(WorkspaceMemberSerializer(target_membership).data)
    
def build_invitation_url(invitation):
    return f"{settings.FRONTEND_URL.rstrip('/')}/invites/{invitation.token}"

def send_workspace_invitation_email(invitation):
    invite_url = build_invitation_url(invitation)
    
    send_mail(
        subject=f"Приглашение в кабинет {invitation.workspace.name}",
        message=(
            f"Вас пригласили в кабинет {invitation.workspace.name}.\n\n"
            f"Перейдите по ссылке, чтобы принять приглашение:\n{invite_url}\n\n"
            f"Ссылка действует до {invitation.expires_at}."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list={invitation.email},
        fail_silently=False
    )
    
def ensure_invitation_can_be_used(invitation):
    if invitation.status != WorkspaceInvitation.Status.PENDING:
        raise ValidationError("Это приглашение уже не активно")
    
    if invitation.is_expired:
        invitation.status = WorkspaceInvitation.Status.EXPIRED
        invitation.save(update_fields=["status", "updated_at"])
        raise ValidationError("Скрой действия приглашения истек")
    
    if invitation.role == WorkspaceMembership.Role.OWNER:
        raise ValidationError("Нельзя принять приглашение с ролью владельца")
    
    
class WorkspaceInvitationListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request, workspace_id):
        get_manage_users_membership(request, workspace_id)
        
        invitations = (
            WorkspaceInvitation.objects
            .select_related("workspace", "invited_by")
            .filter(workspace_id=workspace_id)
            .order_by("-created_at")
        )
        
        return Response(WorkspaceInvitationSerializer(invitations, many=True).data)
    
    @transaction.atomic
    def post(self, request, workspace_id):
        manager_membership = get_manage_users_membership(request, workspace_id)
        workspace = manager_membership.workspace
        
        serializer = WorkspaceInvitationCreateSerializer(
            data=request.data,
            context={"workspace": workspace},
        )
        
        serializer.is_valid(raise_exception=True)
        
        invitation = WorkspaceInvitation.objects.create(
            workspace=workspace,
            email=serializer.validated_data["email"],
            role=serializer.validated_data["role"],
            invited_by=request.user,
        )
        
        send_workspace_invitation_email(invitation)
        
        data = WorkspaceInvitationSerializer(invitation).data
        data["accept_url"] = build_invitation_url(invitation)
        
        return Response(data, status=status.HTTP_201_CREATED)
    
class WorkspaceInvitationRevokeView(APIView):
    permission_classes = [IsAuthenticated]
    
    @transaction.atomic
    def post(self, request, workspace_id, invitation_id):
        get_manage_users_membership(request, workspace_id)
        
        invitation = get_object_or_404(
            WorkspaceInvitation.objects.select_for_update(),
            id=invitation_id,
            workspace_id=workspace_id
        )
        
        if invitation.status != WorkspaceInvitation.Status.PENDING:
            raise ValidationError("Можно отозвать только активное приглашение.")
        
        invitation.status = WorkspaceInvitation.Status.REVOKED
        invitation.save(update_fields=["status", "updated_at"])
        
        return Response(WorkspaceInvitationSerializer(invitation).data)
    
class WorkspaceInvitationPublicDetailView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    
    def get(self, request, token):
        invitation = get_object_or_404(
            WorkspaceInvitation.objects.select_related("workspace"),
            token=token,
        )
        
        if invitation.is_expired:
            invitation.status = WorkspaceInvitation.Status.EXPIRED
            invitation.save(update_fields=["status", "updated_at"])
            
        return Response({
            "workspace": {
                "id": invitation.workspace_id,
                "name": invitation.workspace.name,
                "slug": invitation.workspace.slug,
            },
            "email": invitation.email,
            "role": invitation.role,
            "status": invitation.status,
            "expires_at": invitation.expires_at,
        })
        
class WorkspaceInvitationAcceptView(APIView):
    permission_classes = [IsAuthenticated]
    
    @transaction.atomic
    def post(self, request, token):
        invitation = get_object_or_404(
            WorkspaceInvitation.objects
            .select_for_update()
            .select_related("workspace"),
            token=token,
        )
        
        ensure_invitation_can_be_used(invitation)
        
        if request.user.email.lower() != invitation.email.lower():
            raise ValidationError("Это приглашение создано для другого email.")

        existing_membership = (
            WorkspaceMembership.objects
            .select_for_update()
            .filter(workspace=invitation.workspace, user=request.user)
            .first()
        )
        
        if existing_membership:
            if existing_membership.status == WorkspaceMembership.Status.ACTIVE:
                raise ValidationError("Пользователь уже состоит в этом кабинете")
            if existing_membership.status == WorkspaceMembership.Status.DISABLED:
                raise ValidationError("Доступ пользователя к этому кабинету отключен.")
            
            existing_membership.role = invitation.role
            existing_membership.status = WorkspaceMembership.Status.ACTIVE
            existing_membership.joined_at = timezone.now()
            existing_membership.save(update_fields=["role", "status", "joined_at", "updated_at"])
            membership = existing_membership
            
        else:
            membership = WorkspaceMembership.objects.create(
                workspace=invitation.workspace,
                user=request.user,
                role=invitation.role,
                status=WorkspaceMembership.Status.ACTIVE,
                invited_by=invitation.invited_by,
                joined_at=timezone.now(),
            )
        
        invitation.status = WorkspaceInvitation.Status.ACCEPTED
        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=["status", "accepted_at", "updated_at"])
        
        return Response({
            "user": UserSerializer(request.user).data,
            "workspace": {
                "id": invitation.workspace.id,
                "name": invitation.workspace.name,
                "slug": invitation.workspace.slug
            },
            "membership": WorkspaceMemberSerializer(membership).data,
        })
        
class WorkspaceInvitationRegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    
    @transaction.atomic
    def post(self, request, token):
        invitation = get_object_or_404(
            WorkspaceInvitation.objects
            .select_for_update()
            .select_related("workspace", "invited_by"),
            token=token
        )
        
        ensure_invitation_can_be_used(invitation)
        
        if User.objects.filter(email__iexact=invitation.email).exists():
            raise ValidationError("Пользователь с таким email уже существует. Войдите и примите приглашение.")
        
        serializer = WorkspaceInvitationRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = User.objects.create_user(
            email=invitation.email,
            password=serializer.validated_data["password"],
            first_name=serializer.validated_data.get("first_name", ""),
            last_name=serializer.validated_data.get("last_name", "")
            
        )
        
        membership = WorkspaceMembership.objects.create(
            workspace=invitation.workspace,
            user=user,
            role=invitation.role,
            status=WorkspaceMembership.Status.ACTIVE,
            invited_by=invitation.invited_by,
            joined_at=timezone.now()
        )
        
        invitation.status = WorkspaceInvitation.Status.ACCEPTED
        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=["status", "accepted_at", "updated_at"])
        
        refresh = RefreshToken.for_user(user)
        
        response = Response({
            "user": UserSerializer(user).data,
            "workspace": {
                "id": invitation.workspace.id,
                "name": invitation.workspace.name,
                "slug": invitation.workspace.slug,
            },
            "membership": WorkspaceMemberSerializer(membership).data,
            "access": str(refresh.access_token),
        },  status=status.HTTP_201_CREATED)
        
        set_refresh_cookie(response, str(refresh))
        
        return response
       