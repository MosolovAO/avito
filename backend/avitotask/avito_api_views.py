from http import HTTPStatus

from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django.shortcuts import get_object_or_404

from accounts.permissions import WorkspacePermission
from avitotask.api_views import get_request_workspace
from avitotask.models import AvitoAccount
from avitotask.services.avito_api import (
    AvitoApiError,
    build_avito_authorization_url,
    connect_avito_account_from_authorization_code,
)

from avitotask.tasks import (
    import_avito_account_daily_stats_task,
    import_avito_account_listings_task,
    link_avito_account_publications_task,
)


class AvitoOAuthCallbackSerializer(serializers.Serializer):
    code = serializers.CharField(required=False)
    state = serializers.CharField(required=False)
    error = serializers.CharField(required=False)
    error_description = serializers.CharField(required=False)

    def validate(self, attrs):
        if attrs.get("error"):
            message = attrs.get("error_description") or attrs["error"]
            raise serializers.ValidationError({"avito": message})
        if not attrs.get("code"):
            raise serializers.ValidationError({"code": "Параметр code обязателен."})
        if not attrs.get("state"):
            raise serializers.ValidationError({"state": "Параметр state обязателен."})

        return attrs


class AvitoOAuthStartView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, avito_account_id):
        workspace = get_request_workspace(
            request,
            required_permission=WorkspacePermission.MANAGE_AVITO_ACCOUNTS,
        )
        avito_account = get_object_or_404(
            AvitoAccount,
            id=avito_account_id,
            workspace=workspace,
        )

        return Response({
            "authorization_url": build_avito_authorization_url(avito_account),
        })


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

        async_result = import_avito_account_listings_task.delay(avito_account.id)

        return Response(
            {
                "status": "queued",
                "task_id": async_result.id,
                "avito_account_id": avito_account.id,
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


class AvitoOAuthCallbackView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = AvitoOAuthCallbackSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        try:
            avito_account = connect_avito_account_from_authorization_code(
                code=serializer.validated_data["code"],
                state=serializer.validated_data["state"],
            )
        except AvitoApiError as exc:
            return Response(
                {
                    "detail": str(exc),
                    "payload": exc.payload,
                },
                status=HTTPStatus.BAD_REQUEST,
            )

        return Response({
            "status": "connected",
            "avito_account_id": avito_account.id,
            "external_account_id": avito_account.external_account_id,
        })


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
