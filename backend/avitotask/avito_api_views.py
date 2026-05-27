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
    extract_avito_user_id,
)

from avitotask.serializers import (
    AvitoListingBulkDesiredStatusSerializer,
    AvitoListingBulkManagementStatusSerializer,
)

from avitotask.services.avito_ads import (
    AvitoAdListFilters,
    list_avito_account_ads,
)

from avitotask.services.avito_excel_import import (
    AvitoExcelImportError,
    import_avito_excel_file,
    preview_avito_excel_file,
)

from avitotask.services.ad_editing import AdEditingError

from avitotask.services.avito_listing_editing import bulk_update_avito_listing_desired_status, \
    bulk_update_avito_listing_management_status
from avitotask.services.avito_listing_lifecycle import build_avito_listing_lifecycle_report
from avitotask.services.avito_listing_unmapped import (
    build_avito_listing_unmapped_summary,
)
from avitotask.services.avito_listing_remap import (
    remap_imported_avito_listings,
)
from avitotask.services.avito_autoload_report_sync import sync_avito_autoload_report
from avitotask.api_views import get_request_workspace
from avitotask.models import AvitoAccount, AvitoListing, AvitoOAuthToken

from avitotask.tasks import (
    import_avito_account_daily_stats_task,
    import_avito_account_listings_task,
    link_avito_account_publications_task,
    sync_last_completed_avito_autoload_report_task,
)
from avitotask.tasks import export_avito_account_csv_task

from pathlib import Path

from django.http import FileResponse

from django.conf import settings
from datetime import timedelta


def build_autoload_report_sync_rate_limit_response(avito_account):
    rate_limit_seconds = int(
        getattr(settings, "AVITO_AUTOLOAD_REPORT_SYNC_RATE_LIMIT_SECONDS", 0)
        or 0
    )

    if rate_limit_seconds <= 0:
        return None

    if not avito_account.sync_requested_at:
        return None

    elapsed = timezone.now() - avito_account.sync_requested_at
    retry_after_seconds = rate_limit_seconds - int(elapsed.total_seconds())

    if retry_after_seconds <= 0:
        return None

    return Response(
        {
            "detail": "Синхронизацию отчета автозагрузки можно запускать не чаще одного раза в заданный интервал.",
            "retry_after_seconds": retry_after_seconds,
        },
        status=status.HTTP_429_TOO_MANY_REQUESTS,
        headers={
            "Retry-After": str(retry_after_seconds),
        },
    )


def serialize_avito_listing_lifecycle_report(report, items_limit=100):
    return {
        "total_checked": report.total_checked,
        "expired": report.expired,
        "expires_soon": report.expires_soon,
        "active_ok": report.active_ok,
        "items": [
            {
                "listing_id": item.listing_id,
                "avito_id": item.avito_id,
                "row_id": item.row_id,
                "title": item.title,
                "status": item.status,
                "desired_status": item.desired_status,
                "date_end": item.date_end,
                "days_left": item.days_left,
                "action": item.action,
            }
            for item in report.items[:items_limit]
        ],
    }


def serialize_avito_excel_preview(result, rows_limit=20):
    return {
        "total_sheets": result.total_sheets,
        "total_rows": result.total_rows,
        "rows_with_errors": result.rows_with_errors,
        "categories": result.categories,
        "unmapped_columns": result.unmapped_columns,
        "rows": [
            {
                "sheet_name": row.sheet_name,
                "category_path": row.category_path,
                "row_number": row.row_number,
                "row_id": row.row_id,
                "avito_id": row.avito_id,
                "title": row.title,
                "status": row.status,
                "mapped_data": row.mapped_data,
                "unmapped_data": row.unmapped_data,
                "errors": row.errors,
            }
            for row in result.rows[:rows_limit]
        ],
    }


class AvitoAccountDownloadCsvView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, avito_account_id):
        workspace = get_request_workspace(
            request,
            required_permission=WorkspacePermission.VIEW_ADS
        )
        avito_account = get_object_or_404(
            AvitoAccount,
            id=avito_account_id,
            workspace=workspace,
        )

        if not avito_account.export_file_path:
            return Response(
                {"detail": "CSV-файл еще не сформирован"},
                status=status.HTTP_404_NOT_FOUND,
            )

        file_path = Path(avito_account.export_file_path)

        if not file_path.exists():
            return Response(
                {"detail": "CSV-файл не найден на сервере"},
                status=status.HTTP_404_NOT_FOUND,
            )

        return FileResponse(
            open(file_path, "rb"),
            as_attachment=True,
            filename=file_path.name,
            content_type="text/csv",
        )


class AvitoAccountPublicCsvFeedView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, feed_token):
        avito_account = get_object_or_404(
            AvitoAccount,
            feed_token=feed_token,
            is_active=True,
        )

        if not avito_account.export_file_path:
            return Response(
                {"detail": "CSV-файл еще не сформирован"},
                status=status.HTTP_404_NOT_FOUND,
            )

        file_path = Path(avito_account.export_file_path)

        if not file_path.exists():
            return Response(
                {"detail": "CSV-файл не найден на сервере"},
                status=status.HTTP_404_NOT_FOUND,
            )

        response = FileResponse(
            open(file_path, "rb"),
            as_attachment=False,
            filename=file_path.name,
            content_type="text/csv; charset=utf-8",
        )
        response["Cache-Control"] = "no-store"
        response["X-Avito-Account-Id"] = str(avito_account.id)
        response["X-Avito-Export-Status"] = avito_account.export_status

        return response


class AvitoAccountRequestCsvExportView(APIView):
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
        avito_account.export_status = AvitoAccount.ExportStatus.QUEUED
        avito_account.export_requested_at = timezone.now()
        avito_account.export_error = None
        avito_account.save(
            update_fields=[
                "export_status",
                "export_requested_at",
                "export_error",
                "updated_at"
            ]
        )

        async_result = export_avito_account_csv_task.delay(avito_account.id)

        return Response(
            {
                "status": "queued",
                "task_id": async_result.id,
                "avito_account_id": avito_account.id,
                "export_status": avito_account.export_status,
            },
            status=status.HTTP_202_ACCEPTED,
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

        rate_limit_response = build_autoload_report_sync_rate_limit_response(
            avito_account
        )

        if rate_limit_response is not None:
            return rate_limit_response

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

        async_result = sync_last_completed_avito_autoload_report_task.delay(
            avito_account.id,
        )

        return Response(
            {
                "status": "queued",
                "task_id": async_result.id,
                "avito_account_id": avito_account.id,
                "sync_status": avito_account.sync_status,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class AvitoAccountAutoloadReportSyncView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, avito_account_id):
        serializer = AvitoAccountAutoloadReportSyncSerializer(data=request.data)
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

        result = sync_avito_autoload_report(
            workspace=workspace,
            avito_account=avito_account,
            report_rows=serializer.validated_data["report_rows"],
        )

        return Response(
            {
                "total_rows": result.total_rows,
                "accepted_rows": result.accepted_rows,
                "rejected_rows": result.rejected_rows,
                "linked_publications": result.linked_publications,
                "updated_listings": result.updated_listings,
                "created_listings": result.created_listings,
                "missing_row_id": result.missing_row_id,
                "missing_publications": result.missing_publications,
                "conflicts": result.conflicts,
                "errors": result.errors,
            }
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


class AvitoListingLifecycleReportSerializer(serializers.Serializer):
    soon_days = serializers.IntegerField(
        required=False,
        min_value=0,
        max_value=30,
        default=3,
    )


class AvitoListingUnmappedSummarySerializer(serializers.Serializer):
    limit = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=500,
        default=100,
    )


class AvitoAccountAdsListSerializer(serializers.Serializer):
    entity_type = serializers.ChoiceField(
        choices=["", "avito_listing", "ad_publication"],
        required=False,
        allow_blank=True,
        default="",
    )
    source = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    status = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    desired_status = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    management_status = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    has_avito_id = serializers.ChoiceField(
        choices=["", "1", "0", "true", "false", "True", "False"],
        required=False,
        allow_blank=True,
        default="",
    )
    has_errors = serializers.ChoiceField(
        choices=["", "1", "0", "true", "false", "True", "False"],
        required=False,
        allow_blank=True,
        default="",
    )
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    page = serializers.IntegerField(
        required=False,
        min_value=1,
        default=1,
    )
    page_size = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=100,
        default=50,
    )


class AvitoAccountLinkPublicationsSerializer(serializers.Serializer):
    row_ids = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=False
    )


class AvitoAccountAutoloadReportSyncSerializer(serializers.Serializer):
    report_rows = serializers.ListField(
        child=serializers.DictField(),
        allow_empty=False,
    )


class AvitoExcelImportPreviewSerializer(serializers.Serializer):
    file = serializers.FileField()

    def validate_file(self, value):
        file_name = value.name.lower()

        if not file_name.endswith(".xlsx"):
            raise serializers.ValidationError("Загрузите файл XLSX.")

        return value


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

        external_account_id = extract_avito_user_id(user_info)

        if not external_account_id:
            token.user_info = user_info
            token.last_error = "Avito API не вернул id пользователя."
            token.save(update_fields=["user_info", "last_error", "updated_at"])

            return Response(
                {
                    "status": "token_error",
                    "detail": "Avito API не вернул id пользователя.",
                    "external_account_id": avito_account.external_account_id,
                    "last_verified_at": token.last_verified_at,
                    "payload": user_info,
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


class AvitoAccountExcelImportPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, avito_account_id):
        serializer = AvitoExcelImportPreviewSerializer(data=request.data)
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

        try:
            result = preview_avito_excel_file(serializer.validated_data["file"])
        except AvitoExcelImportError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(serialize_avito_excel_preview(result))


class AvitoAccountExcelImportApplyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, avito_account_id):
        serializer = AvitoExcelImportPreviewSerializer(data=request.data)
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

        try:
            result = import_avito_excel_file(
                workspace=workspace,
                avito_account=avito_account,
                file_obj=serializer.validated_data["file"],
            )
        except AvitoExcelImportError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "total_rows": result.total_rows,
                "skipped_rows": result.skipped_rows,
                "created_listings": result.created_listings,
                "updated_listings": result.updated_listings,
                "rows_with_errors": result.rows_with_errors,
                "unmapped_columns": result.unmapped_columns,
            },
            status=status.HTTP_201_CREATED,
        )


class AvitoAccountBulkListingDesiredStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, avito_account_id):
        serializer = AvitoListingBulkDesiredStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        workspace = get_request_workspace(
            request,
            required_permission=WorkspacePermission.MANAGE_ADS,
        )
        avito_account = get_object_or_404(
            AvitoAccount,
            id=avito_account_id,
            workspace=workspace,
        )

        try:
            result = bulk_update_avito_listing_desired_status(
                workspace=workspace,
                avito_account=avito_account,
                listing_ids=serializer.validated_data["listing_ids"],
                desired_status=serializer.validated_data["desired_status"],
            )
        except AdEditingError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(result)


class AvitoAccountListingLifecycleReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, avito_account_id):
        serializer = AvitoListingLifecycleReportSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        workspace = get_request_workspace(
            request,
            required_permission=WorkspacePermission.VIEW_ADS,
        )
        avito_account = get_object_or_404(
            AvitoAccount,
            id=avito_account_id,
            workspace=workspace,
        )

        report = build_avito_listing_lifecycle_report(
            workspace=workspace,
            avito_account=avito_account,
            soon_days=serializer.validated_data["soon_days"],
        )

        return Response(serialize_avito_listing_lifecycle_report(report))


class AvitoAccountListingUnmappedSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, avito_account_id):
        serializer = AvitoListingUnmappedSummarySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        workspace = get_request_workspace(
            request,
            required_permission=WorkspacePermission.VIEW_ADS,
        )
        avito_account = get_object_or_404(
            AvitoAccount,
            id=avito_account_id,
            workspace=workspace,
        )

        result = build_avito_listing_unmapped_summary(
            workspace=workspace,
            avito_account=avito_account,
            limit=serializer.validated_data["limit"],
        )

        return Response(result)


class AvitoAccountAdsListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, avito_account_id):
        serializer = AvitoAccountAdsListSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        workspace = get_request_workspace(
            request,
            required_permission=WorkspacePermission.VIEW_ADS,
        )
        avito_account = get_object_or_404(
            AvitoAccount,
            id=avito_account_id,
            workspace=workspace,
        )

        filters = AvitoAdListFilters(
            entity_type=serializer.validated_data["entity_type"],
            source=serializer.validated_data["source"],
            status=serializer.validated_data["status"],
            desired_status=serializer.validated_data["desired_status"],
            management_status=serializer.validated_data["management_status"],
            has_avito_id=serializer.validated_data["has_avito_id"],
            has_errors=serializer.validated_data["has_errors"],
            search=serializer.validated_data["search"].strip(),
        )

        result = list_avito_account_ads(
            workspace=workspace,
            avito_account=avito_account,
            filters=filters,
            page=serializer.validated_data["page"],
            page_size=serializer.validated_data["page_size"],
        )

        return Response({
            "count": result.count,
            "page": result.page,
            "page_size": result.page_size,
            "results": result.results,
        })


class AvitoAccountListingRemapImportFieldsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, avito_account_id):
        workspace = get_request_workspace(
            request,
            required_permission=WorkspacePermission.MANAGE_ADS,
        )
        avito_account = get_object_or_404(
            AvitoAccount,
            id=avito_account_id,
            workspace=workspace,
        )

        result = remap_imported_avito_listings(
            workspace=workspace,
            avito_account=avito_account,
        )

        return Response(
            {
                "total_checked": result.total_checked,
                "updated": result.updated,
                "skipped_without_raw_data": result.skipped_without_raw_data,
                "still_with_unmapped": result.still_with_unmapped,
                "resolved_columns": result.resolved_columns,
            },
        )


class AvitoAccountBulkListingManagementStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, avito_account_id):
        serializer = AvitoListingBulkManagementStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        workspace = get_request_workspace(
            request,
            required_permission=WorkspacePermission.MANAGE_ADS,
        )
        avito_account = get_object_or_404(
            AvitoAccount,
            id=avito_account_id,
            workspace=workspace,
        )

        try:
            result = bulk_update_avito_listing_management_status(
                workspace=workspace,
                avito_account=avito_account,
                listing_ids=serializer.validated_data["listing_ids"],
                management_status=serializer.validated_data["management_status"],
            )
        except AdEditingError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(result)
