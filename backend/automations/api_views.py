from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.viewsets import GenericViewSet, ModelViewSet

from accounts.permissions import WorkspacePermission
from accounts.workspace_context import get_request_workspace
from automations.models import (
    Automation,
    AutomationRun,
    AvitoListingDecision,
)
from automations.registry import build_modules_catalog_payload
from automations.serializers import (
    AutomationCreateSerializer,
    AutomationReadSerializer,
    AutomationRunDetailSerializer,
    AutomationRunListSerializer,
    AutomationRunRequestSerializer,
    AutomationUpdateSerializer,
    AvitoListingDecisionListSerializer,
)
from automations.services.automation_management import (
    AutomationManagementError,
    archive_automation,
    create_automation,
    update_automation,
)
from automations.services.run_creation import (
    RunCreationError,
    create_or_get_manual_run,
    create_or_get_preview_run,
)
from automations.modules.avito_listings.decision_approval import (
    DecisionApprovalError,
    approve_decision as approve_listing_decision,
)
from automations.modules.avito_listings.decision_lifecycle import (
    DecisionTransitionError,
    reject_decision as reject_listing_decision,
)


class AutomationPagination(PageNumberPagination):
    """Ограниченная пагинация списка автоматизаций."""

    page_size = 20


class AutomationViewSet(ModelViewSet):
    permission_classes = (IsAuthenticated,)
    pagination_class = AutomationPagination
    http_method_names = (
        "get",
        "post",
        "patch",
        "delete",
        "head",
        "options",
    )

    def get_workspace(self):
        if not hasattr(self, "_request_workspace"):
            self._request_workspace = get_request_workspace(
                self.request,
                required_permission=(
                    WorkspacePermission.MANAGE_AUTOMATIONS
                ),
            )

        return self._request_workspace

    def get_queryset(self):
        return (
            Automation.objects
            .filter(
                workspace=self.get_workspace(),
            )
            .exclude(
                state=Automation.State.ARCHIVED,
            )
            .select_related(
                "avito_listing_config",
            )
            .order_by(
                "-created_at",
                "-id",
            )
        )

    def get_serializer_class(self):
        if self.action == "create":
            return AutomationCreateSerializer

        if self.action == "partial_update":
            return AutomationUpdateSerializer

        if self.action in {"preview", "run"}:
            return AutomationRunRequestSerializer

        if self.action == "runs":
            return AutomationRunListSerializer

        return AutomationReadSerializer

    @action(
        detail=False,
        methods=("get",),
        url_path="inbox-summary",
    )
    def inbox_summary(self, _request):
        """Возвращает число актуальных решений для подтверждения."""

        pending_approval_count = (
            AvitoListingDecision.objects
            .filter(
                workspace=self.get_workspace(),
                status=(
                    AvitoListingDecision.Status.PENDING_APPROVAL
                ),
                expires_at__gt=timezone.now(),
            )
            .count()
        )

        return Response({
            "pending_approval_count": pending_approval_count,
        })

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            automation = create_automation(
                workspace=self.get_workspace(),
                actor=request.user,
                **serializer.validated_data,
            )
        except AutomationManagementError as error:
            return self._domain_error_response(error)

        return Response(
            self._serialize_automation(automation),
            status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)

        try:
            automation = update_automation(
                workspace=self.get_workspace(),
                actor=request.user,
                automation_id=kwargs["pk"],
                **serializer.validated_data,
            )
        except AutomationManagementError as error:
            return self._domain_error_response(error)

        return Response(self._serialize_automation(automation))

    def destroy(self, request, *args, **kwargs):
        try:
            archive_automation(
                workspace=self.get_workspace(),
                actor=request.user,
                automation_id=kwargs["pk"],
            )
        except AutomationManagementError as error:
            return self._domain_error_response(error)

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(
        detail=False,
        methods=("get",),
        url_path="catalog",
    )
    def catalog(self, request):
        self.get_workspace()

        return Response({
            "modules": build_modules_catalog_payload(),
        })

    @action(
        detail=True,
        methods=("get",),
        url_path="runs",
    )
    def runs(self, request, pk=None):
        automation = self.get_object()
        queryset = (
            AutomationRun.objects
            .filter(
                workspace=self.get_workspace(),
                automation=automation,
            )
            .select_related(
                "avito_listing_result",
            )
            .order_by(
                "-created_at",
                "-id",
            )
        )

        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)

        return self.get_paginated_response(serializer.data)

    @action(
        detail=True,
        methods=("post",),
        url_path="preview",
    )
    def preview(self, request, pk=None):
        return self._create_run(
            request=request,
            automation_id=pk,
            creator=create_or_get_preview_run,
        )

    @action(
        detail=True,
        methods=("post",),
        url_path="run",
    )
    def run(self, request, pk=None):
        return self._create_run(
            request=request,
            automation_id=pk,
            creator=create_or_get_manual_run,
        )

    def _create_run(
            self,
            *,
            request,
            automation_id,
            creator,
    ):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            creation = creator(
                workspace=self.get_workspace(),
                automation_id=automation_id,
                created_by=request.user,
                idempotency_key=request.headers.get(
                    "Idempotency-Key",
                ),
            )
        except RunCreationError as error:
            return self._domain_error_response(error)

        return Response(
            {
                "run_id": creation.run.id,
                "status": creation.run.status,
                "created": creation.created,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    def _serialize_automation(self, automation):
        return AutomationReadSerializer(
            automation,
            context=self.get_serializer_context(),
        ).data

    @staticmethod
    def _domain_error_response(error):
        if error.code == "automation_not_found":
            response_status = status.HTTP_404_NOT_FOUND
        elif error.code in {
            "resource_busy",
            "avito_account_immutable",
            "automation_archived",
            "invalid_automation_state",
            "open_preview_conflict",
            "open_execute_conflict",
            "preview_required",
        }:
            response_status = status.HTTP_409_CONFLICT
        else:
            response_status = status.HTTP_400_BAD_REQUEST

        payload = {
            "code": error.code,
            "message": str(error),
        }

        open_run_id = getattr(error, "open_run_id", None)
        if open_run_id is not None:
            payload["open_run_id"] = open_run_id

        return Response(
            payload,
            status=response_status,
        )


class AutomationRunViewSet(
    RetrieveModelMixin,
    GenericViewSet,
):
    """Возвращает запуск, его решения и ручные команды."""

    permission_classes = (IsAuthenticated,)
    pagination_class = AutomationPagination
    http_method_names = (
        "get",
        "post",
        "head",
        "options",
    )

    def get_workspace(self):
        if not hasattr(self, "_request_workspace"):
            self._request_workspace = get_request_workspace(
                self.request,
                required_permission=(
                    WorkspacePermission.MANAGE_AUTOMATIONS
                ),
            )

        return self._request_workspace

    def get_serializer_class(self):
        if self.action == "decisions":
            return AvitoListingDecisionListSerializer

        if self.action in {
            "approve_decision",
            "reject_decision",
        }:
            return AutomationRunRequestSerializer

        return AutomationRunDetailSerializer

    def get_queryset(self):
        queryset = AutomationRun.objects.filter(
            workspace=self.get_workspace(),
        )

        if self.action == "retrieve":
            queryset = queryset.select_related(
                "avito_listing_result",
            )

        return queryset

    @action(
        detail=True,
        methods=("get",),
        url_path="decisions",
    )
    def decisions(self, request, pk=None):
        automation_run = self.get_object()
        queryset = (
            AvitoListingDecision.objects
            .filter(
                run=automation_run,
                workspace_id=automation_run.workspace_id,
            )
            .defer(
                "condition_snapshot",
            )
            .order_by(
                "-created_at",
                "-id",
            )
        )

        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)

        return self.get_paginated_response(serializer.data)

    @action(
        detail=True,
        methods=("post",),
        url_path=(
                r"decisions/(?P<decision_id>[0-9]+)/approve"
        ),
    )
    def approve_decision(
            self,
            request,
            pk=None,
            decision_id=None,
    ):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = approve_listing_decision(
                workspace=self.get_workspace(),
                run_id=pk,
                decision_id=decision_id,
                approved_by=request.user,
            )
        except DecisionApprovalError as error:
            return self._decision_error_response(error)

        return self._decision_command_response(
            decision=result.decision,
            outcome=result.outcome,
            reason=result.reason,
            changed=result.changed,
            required_export_revision=(
                result.required_export_revision
            ),
        )

    @action(
        detail=True,
        methods=("post",),
        url_path=(
                r"decisions/(?P<decision_id>[0-9]+)/reject"
        ),
    )
    def reject_decision(
            self,
            request,
            pk=None,
            decision_id=None,
    ):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = reject_listing_decision(
                workspace=self.get_workspace(),
                run_id=pk,
                decision_id=decision_id,
                rejected_by=request.user,
            )
        except DecisionTransitionError as error:
            return self._decision_error_response(error)

        outcome = (
            result.decision.status
            if result.changed
            else "unchanged"
        )

        return self._decision_command_response(
            decision=result.decision,
            outcome=outcome,
            reason=None,
            changed=result.changed,
            required_export_revision=(
                result.decision.required_export_revision
            ),
        )

    @staticmethod
    def _decision_command_response(
            *,
            decision,
            outcome,
            reason,
            changed,
            required_export_revision,
    ):
        return Response({
            "decision_id": decision.id,
            "status": decision.status,
            "outcome": outcome,
            "reason": reason,
            "changed": changed,
            "required_export_revision": (
                required_export_revision
            ),
        })

    @staticmethod
    def _decision_error_response(error):
        if error.code == "decision_not_found":
            response_status = status.HTTP_404_NOT_FOUND
        elif error.code in {
            "resource_busy",
            "invalid_decision_state",
            "invalid_run_state",
        }:
            response_status = status.HTTP_409_CONFLICT
        else:
            response_status = status.HTTP_400_BAD_REQUEST

        return Response(
            {
                "code": error.code,
                "message": str(error),
            },
            status=response_status,
        )
