from django.shortcuts import get_object_or_404
from django.utils import timezone

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
from analytics.tasks import (
    enqueue_avito_profile_daily_sync,
    enqueue_avito_stats_sync,
)
from accounts.workspace_context import get_request_workspace
from avitotask.models import AvitoAccount

from datetime import timedelta


class AvitoAccountImportDailyStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, avito_account_id):
        serializer = AvitoAccountImportDailyStatsSerializer(data=request.data)
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

        has_explicit_range_or_listings = any(
            field in serializer.validated_data
            for field in (
                "date_from",
                "date_to",
                "listing_ids",
            )
        )

        if has_explicit_range_or_listings:
            # Диагностический режим: явно заданный stats/v1 импорт.
            enqueue_result = enqueue_avito_stats_sync(
                avito_account=avito_account,
                date_from=serializer.validated_data.get("date_from"),
                date_to=serializer.validated_data.get("date_to"),
                listing_ids=serializer.validated_data.get("listing_ids"),
            )
        else:
            # Основной сценарий ручной кнопки:
            # stats/v2 за последний полностью завершённый день,
            # затем отдельный исторический backfill через stats/v1.
            target_date = (
                    timezone.localdate() - timedelta(days=1)
            )
            enqueue_result = enqueue_avito_profile_daily_sync(
                avito_account=avito_account,
                stat_date=target_date,
            )

        sync_state = enqueue_result["sync_state"]

        return Response(
            {
                "status": sync_state.status,
                "task_id": enqueue_result["task_id"],
                "queued": enqueue_result["queued"],
                "avito_account_id": avito_account.id,
                "date_from": enqueue_result["date_from"].isoformat(),
                "date_to": enqueue_result["date_to"].isoformat(),
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
            page=serializer.validated_data["page"],
            page_size=serializer.validated_data["page_size"],
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
