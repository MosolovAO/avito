from http import HTTPStatus

from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated

from rest_framework.response import Response
from rest_framework.views import APIView

from django.shortcuts import get_object_or_404

from accounts.permissions import (
    WorkspacePermission,
)

from django.utils import timezone

from avitotask.services.avito_api import (
    AvitoApiError,
    AvitoApiClient,
    connect_avito_account_with_client_credentials,
)

from avitotask.api_views import get_request_workspace
from avitotask.models import AvitoAccount, AvitoOAuthToken

from avitotask.tasks import (
    import_avito_account_daily_stats_task,
    import_avito_account_listings_task,
    link_avito_account_publications_task,
)


class AvitoAccountImportListingsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, avito_account_id):
        workspace = get_request_workspace(
            request,
            required_permission=WorkspacePermission.MANAGE_AVITO_ACCOUNTS,
        )
        avito_account = get_object_or_404(
            AvitoAccount,
            id=avito_account_id,
            workspace=workspace,
        )

        avito_account.sync_status = AvitoAccount.SyncStatus.QUEUED
        avito_account.sync_requested_at = timezone.now()
        avito_account.sync_error = None
        avito_account.save(
            update_fields=[
                "sync_status",
                "sync_requested_at",
                "sync_error",
                "updated_at",
            ]
        )

        async_result = import_avito_account_listings_task.delay(avito_account.id)

        return Response(
            {
                "status": "queued",
                "task_id": async_result.id,
                "avito_account_id": avito_account.id,
                "sync_status": avito_account.sync_status,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class AvitoAccountLinkPublicationsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, avito_account_id):
        serializer = AvitoAccountLinkPublicationsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        workspace = get_request_workspace(
            request,
            required_permission=WorkspacePermission.MANAGE_AVITO_ACCOUNTS,
        )

        avito_account = get_object_or_404(
            AvitoAccount,
            id=avito_account_id,
            workspace=workspace,
        )

        async_result = link_avito_account_publications_task.delay(
            avito_account.id,
            serializer.validated_data.get("row_ids")
        )

        return Response(
            {
                "status": "queued",
                "task_id": async_result.id,
                "avito_account_id": avito_account.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class AvitoAccountImportDailyStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, avito_account_id):
        serializer = AvitoAccountImportDailyStatsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        workspace = get_request_workspace(
            request,
            required_permission=WorkspacePermission.VIEW_ANALYTICS,
        )
        avito_account = get_object_or_404(
            AvitoAccount,
            id=avito_account_id,
            workspace=workspace,
        )

        async_result = import_avito_account_daily_stats_task.delay(
            avito_account.id,
            serializer.validated_data["date_from"].isoformat(),
            serializer.validated_data["date_to"].isoformat(),
            serializer.validated_data.get("listing_ids"),
        )

        return Response(
            {
                "status": "queued",
                "task_id": async_result.id,
                "avito_account_id": avito_account.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class AvitoAccountLinkPublicationsSerializer(serializers.Serializer):
    row_ids = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=False
    )


class AvitoAccountImportDailyStatsSerializer(serializers.Serializer):
    date_from = serializers.DateField()
    date_to = serializers.DateField()
    listing_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        allow_empty=False
    )

    def validate(self, attrs):
        if attrs["date_from"] > attrs["date_to"]:
            raise serializers.ValidationError({
                "date_to": "date_to должен быть больше или равен date_from."
            })

        return attrs


# backend/avitotask/avito_api_views.py
class AvitoAccountVerifyConnectionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, avito_account_id):
        workspace = get_request_workspace(
            request,
            required_permission=WorkspacePermission.MANAGE_AVITO_ACCOUNTS,
        )
        avito_account = get_object_or_404(
            AvitoAccount,
            id=avito_account_id,
            workspace=workspace,
        )

        try:
            token = avito_account.oauth_tokens
        except AvitoOAuthToken.DoesNotExist:
            return Response(
                {
                    "status": "not_connected",
                    "detail": "Avito-аккаунт еще не подключен через OAuth.",
                    "external_account_id": avito_account.external_account_id,
                    "last_verified_at": None,
                },
                status=HTTPStatus.BAD_REQUEST,
            )

        client = AvitoApiClient()

        try:
            user_info = client.get_current_user(token)
        except AvitoApiError as exc:
            token.last_error = str(exc)
            token.save(update_fields=["last_error", "updated_at"])

            return Response(
                {
                    "status": "token_error",
                    "detail": str(exc),
                    "external_account_id": avito_account.external_account_id,
                    "last_verified_at": token.last_verified_at,
                },
                status=exc.status_code or HTTPStatus.BAD_REQUEST,
            )

        external_account_id = str(user_info.get("id") or "")

        if not external_account_id:
            return Response(
                {
                    "status": "token_error",
                    "detail": "Avito API не вернул id пользователя.",
                    "external_account_id": avito_account.external_account_id,
                    "last_verified_at": token.last_verified_at,
                },
                status=HTTPStatus.BAD_REQUEST,
            )

        avito_account.external_account_id = external_account_id
        avito_account.save(update_fields=["external_account_id", "updated_at"])

        token.user_info = user_info
        token.last_verified_at = timezone.now()
        token.last_error = None
        token.save(
            update_fields=[
                "user_info",
                "last_verified_at",
                "last_error",
                "updated_at",
            ]
        )

        return Response({
            "status": "connected",
            "external_account_id": external_account_id,
            "last_verified_at": token.last_verified_at,
        })


class AvitoAccountConnectByCredentialsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, avito_account_id):
        workspace = get_request_workspace(
            request,
            required_permission=WorkspacePermission.MANAGE_AVITO_ACCOUNTS
        )
        avito_account = get_object_or_404(
            AvitoAccount,
            id=avito_account_id,
            workspace=workspace,
        )

        try:
            avito_account = connect_avito_account_with_client_credentials(
                avito_account
            )
        except AvitoApiError as exc:
            return Response(
                {
                    "detail": str(exc),
                    "payload": exc.payload,
                },
                status=exc.status_code or HTTPStatus.BAD_REQUEST
            )

        return Response({
            "status": "connected",
            "avito_account_id": avito_account.id,
            "external_account_id": avito_account.external_account_id,
        })
