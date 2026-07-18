from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import WorkspacePermission
from analytics.selectors.avito_stats import build_avito_listing_stats_report
from analytics.serializers import (
    AvitoAccountImportDailyStatsSerializer,
    AvitoListingStatsQuerySerializer,
)
from analytics.tasks import import_avito_account_daily_stats_task
from accounts.workspace_context import get_request_workspace
from avitotask.models import AvitoAccount


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


class AvitoAccountListingStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, avito_account_id):
        serializer = AvitoListingStatsQuerySerializer(data=request.query_params)
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

        listing_ids = serializer.validated_data.get("listing_ids")
        ensure_listings_belong_to_account(
            avito_account=avito_account,
            listing_ids=listing_ids,
        )

        report = build_avito_listing_stats_report(
            workspace=workspace,
            avito_account=avito_account,
            date_from=serializer.validated_data["date_from"],
            date_to=serializer.validated_data["date_to"],
            listing_ids=listing_ids,
        )

        return Response(report)


def ensure_listings_belong_to_account(*, avito_account, listing_ids):
    if not listing_ids:
        return

    existing_count = avito_account.avito_listings.filter(id__in=listing_ids).count()

    if existing_count != len(set(listing_ids)):
        raise ValidationError({
            "listing_ids": "Один или несколько listing_ids не относятся к этому Avito-аккаунту."
        })