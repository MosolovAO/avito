from pathlib import Path
from uuid import uuid4
from typing import Any

from rest_framework.views import APIView
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, parser_classes, permission_classes
from rest_framework.response import Response
from rest_framework.parsers import FormParser, MultiPartParser

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.pagination import PageNumberPagination
from rest_framework.fields import DateTimeField
from rest_framework.exceptions import ValidationError

from accounts.permissions import WorkspacePermission
from accounts.workspace_context import get_request_workspace

from django.shortcuts import get_object_or_404
from django.db.models import Q, Count, Prefetch

from django.core.files.storage import default_storage

from .models import (
    ProductOptions,
    Category,
    AvitoAccount,
    AvitoListing,
    AdPublication,
    AdBatch,
    AdCreative,
    AdGenerationTask,
    AdImageAsset

)

from .serializers import (
    ProductSerializer,
    ProductOptionsSerializer,
    AvitoAccountSerializer,
    AvitoListingSerializer,
    AvitoListingUpdateSerializer,
    AdPublicationSerializer,
    AdPublicationUpdateSerializer,
    AdBatchSerializer,
    AdCreativeSerializer,
    AdCreativeEditSerializer,
    AdCreativeUpdateSerializer,
    ManualMassPostingSerializer,

)

from .services.avito_listing_editing import update_avito_listing, extend_avito_listing_date_end

from .services.ad_editing import (
    AdEditingError,
    update_ad_creative,
    update_ad_publication,
    delete_ad_creative,
)

from .services.ad_publication_dates import (
    extend_ad_creative_publications,
    extend_ad_publication,
    inherit_creative_date_end_for_publication,
)

from .services.ad_generation import (
    AdGenerationError,
    create_manual_mass_posting,
)

from .services.ad_schedule import (
    AdScheduleError,
    recalculate_task_next_update_time,
)

from .services.ad_task_runner import (
    run_autogeneration_task
)


class WorkspaceScopedModelViewSet(viewsets.ModelViewSet):
    request: Request
    action: str
    _workspace = None

    read_permission = None
    write_permission = None
    read_actions = {"list", "retrieve"}

    def get_required_workspace_permission(self):
        if self.action in self.read_actions:
            return self.read_permission
        return self.write_permission

    def get_workspace(self):
        if self._workspace is None:
            self._workspace = get_request_workspace(
                self.request,
                required_permission=self.get_required_workspace_permission(),
            )

        return self._workspace

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        context["workspace"] = self.get_workspace()
        return context


class ProductViewSet(WorkspaceScopedModelViewSet):
    """
    Frontend-compatible /api/products/ endpoint.

    URL пока называется products, но источником данных уже является
    новая модель AdGenerationTask.
    """
    serializer_class = ProductSerializer
    permission_classes = [IsAuthenticated]
    read_permission = WorkspacePermission.VIEW_TASKS
    write_permission = WorkspacePermission.MANAGE_TASKS

    def get_queryset(self):
        return (
            AdGenerationTask.objects
            .filter(workspace=self.get_workspace())
            .select_related("category")
            .prefetch_related(
                "avito_accounts",
                "adgenerationtaskoptionassignment_set__option",
            )
        )

    def perform_create(self, serializer):
        serializer.save(workspace=self.get_workspace())


class ProductOptionsViewSet(viewsets.ModelViewSet):
    """ API endpoint для управления опциями продуктов"""
    serializer_class = ProductOptionsSerializer
    permission_classes = [IsAuthenticated]
    queryset = ProductOptions.objects.prefetch_related('categories').order_by('option_title_ru')

    def get_queryset(self):
        queryset = super().get_queryset()
        category_id = self.request.query_params.get('category_id')
        category_name = (self.request.query_params.get('category') or '').strip()

        if category_id:
            return queryset.filter(
                Q(categories_id=category_id) | Q(categories__isnull=True)
            ).distinct()

        if category_name:
            return queryset.filter(
                Q(categories__category__iexact=category_name) | Q(categories__isnull=True)
            ).distinct()

        return queryset.none()


# backend/avitotask/api_views.py

class AvitoAccountViewSet(WorkspaceScopedModelViewSet):
    serializer_class = AvitoAccountSerializer
    permission_classes = [IsAuthenticated]
    read_permission = WorkspacePermission.VIEW_TASKS
    write_permission = WorkspacePermission.MANAGE_AVITO_ACCOUNTS

    def get_queryset(self):
        return (
            AvitoAccount.objects
            .filter(workspace=self.get_workspace())
            .order_by("name")
        )

    def perform_create(self, serializer):
        serializer.save(workspace=self.get_workspace())


ALLOWED_IMAGE_CONTENT_TYPES = {'image/jpeg', 'image/png'}
MAX_IMAGE_SIZE_BYTES = 2 * 1024 * 1024


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def upload_product_image(request):
    get_request_workspace(request, WorkspacePermission.MANAGE_TASKS)
    uploaded_file = request.FILES.get('image')
    if uploaded_file is None:
        return Response(
            {'error': 'Изображение обязательно'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if uploaded_file.content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        return Response(
            {'error': 'Можно загружать только JPEG или PNG изображения.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if uploaded_file.size > MAX_IMAGE_SIZE_BYTES:
        return Response(
            {'error': 'Размер файла не должен превышать 2MB.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    extension = Path(uploaded_file.name).suffix.lower()

    if extension not in ('.jpg', '.jpeg', '.png'):
        return Response(
            {'error': 'Недопустимое расширение файла.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    import hashlib

    file_bytes = uploaded_file.read()
    uploaded_file.seek(0)
    checksum = hashlib.sha256(file_bytes).hexdigest()

    asset = AdImageAsset.objects.create(
        workspace=get_request_workspace(request, WorkspacePermission.MANAGE_TASKS),
        uploaded_by=request.user,
        image=uploaded_file,
        original_filename=uploaded_file.name,
        content_type=uploaded_file.content_type or "",
        size_bytes=uploaded_file.size,
        checksum=checksum,
    )

    asset.url = request.build_absolute_uri(asset.image.url)
    asset.save(update_fields=["url"])

    return Response(
        {
            "id": asset.id,
            "url": asset.url,
            "original_filename": asset.original_filename,
            "content_type": asset.content_type,
            "size_bytes": asset.size_bytes,
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def product_random(request, product_id):
    """
    Ручной запуск автогенерации.

    URL сохраняет старое имя frontend-а /api/product-random/{id},
    но внутри работает только через единый pipeline AdGenerationTask.
    """
    workspace = get_request_workspace(request, WorkspacePermission.MANAGE_TASKS)

    try:
        result = run_autogeneration_task(
            product_id,
            triggered_by="manual",
            workspace=workspace,
            user=request.user,
        )
    except AdGenerationError as exc:
        return Response(
            {"error": str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return Response({
        "run_id": result.run.id,
        "creative_id": result.creative.id if result.creative else None,
        "batch_id": result.batch.id if result.batch else None,
        "publications_count": result.publications_count,
        "csv_export_status": result.csv_export_status,
        "next_update_time": DateTimeField().to_representation(
            result.run.task.next_update_time,
        ),
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def toggle_product_active(request, product_id):
    """
    Активация/деактивация задачи автогенерации.

    Endpoint сохраняет старый URL frontend-а, но работает уже с AdGenerationTask.
    """
    workspace = get_request_workspace(request, WorkspacePermission.MANAGE_TASKS)
    task = get_object_or_404(
        AdGenerationTask,
        pk=product_id,
        workspace=workspace,
    )

    action = request.data.get("action")
    active_value = request.data.get("active")

    if action == "activate":
        should_activate = True
    elif action == "deactivate":
        should_activate = False
    elif isinstance(active_value, bool):
        should_activate = active_value
    else:
        return Response(
            {"error": "Передайте action=activate/deactivate или active=true/false"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if should_activate:
        task.is_active = True

        try:
            recalculate_task_next_update_time(task)
        except AdScheduleError as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        task.save(update_fields=[
            "is_active",
            "schedule",
            "publication_interval_days",
            "schedule_anchor_date",
            "next_update_time",
            "updated_at",
        ])
    else:
        task.is_active = False
        task.next_update_time = None
        task.save(update_fields=["is_active", "next_update_time", "updated_at"])

    return Response({
        "status": "ok",
        "active": task.is_active,
        "next_update_time": DateTimeField().to_representation(task.next_update_time),
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_product_categories(request):
    categories = Category.objects.order_by("category")

    detailed = (
            request.query_params.get("detailed", "").strip().lower()
            in {"1", "true", "yes"}
    )

    if detailed:
        return Response([
            {
                "id": category.id,
                "name": category.category,
            }
            for category in categories
        ])

    # Старый формат сохраняем для обратной совместимости.
    return Response(
        list(categories.values_list("category", flat=True))
    )


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 100


class AvitoListingViewSet(WorkspaceScopedModelViewSet):
    serializer_class = AvitoListingSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    http_method_names = ["get", "patch", "head", "options"]
    read_permission = WorkspacePermission.VIEW_ADS
    write_permission = WorkspacePermission.MANAGE_ADS

    def get_queryset(self):
        queryset = (
            AvitoListing.objects
            .filter(workspace=self.get_workspace())
            .select_related(
                "avito_account",
                "publication",
                "option_category",
            )
            .order_by("-last_seen_at", "-created_at")
        )

        avito_account_id = self.request.query_params.get("avito_account_id")
        status_value = self.request.query_params.get("status")
        search = (self.request.query_params.get("search") or "").strip()
        source_value = self.request.query_params.get("source")
        management_status = self.request.query_params.get("management_status")
        desired_status = self.request.query_params.get("desired_status")
        has_unmapped = self.request.query_params.get("has_unmapped")

        if desired_status:
            queryset = queryset.filter(desired_status=desired_status)

        if has_unmapped in ["1", "true", "True"]:
            queryset = queryset.exclude(unmapped_data={})

        if has_unmapped in ["0", "false", "False"]:
            queryset = queryset.filter(unmapped_data={})

        if avito_account_id:
            queryset = queryset.filter(avito_account_id=avito_account_id)

        if source_value:
            queryset = queryset.filter(source=source_value)

        if management_status:
            queryset = queryset.filter(management_status=management_status)

        if status_value:
            queryset = queryset.filter(status=status_value)

        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) |
                Q(avito_id__icontains=search) |
                Q(row_id__icontains=search) |
                Q(address__icontains=search)
            )
        return queryset

    def partial_update(self, request, *args, **kwargs):
        listing = self.get_object()
        serializer = AvitoListingUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            updated_listing = update_avito_listing(
                listing_id=listing.id,
                workspace=self.get_workspace(),
                **serializer.validated_data,
            )
        except AdEditingError as exc:
            raise ValidationError({"detail": str(exc)})

        output_serializer = self.get_serializer(updated_listing)
        return Response(output_serializer.data)

    @action(detail=True, methods=["patch"], url_path="extend")
    def extend(self, request, *args, **kwargs):
        listing = self.get_object()

        try:
            updated_listing = extend_avito_listing_date_end(
                listing_id=listing.id,
                workspace=self.get_workspace(),
            )
        except AdEditingError as exc:
            raise ValidationError({"detail": str(exc)})

        output_serializer = self.get_serializer(updated_listing)
        return Response(output_serializer.data)


class AdPublicationViewSet(WorkspaceScopedModelViewSet):
    serializer_class = AdPublicationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    http_method_names = ["get", "patch", "head", "options"]
    read_permission = WorkspacePermission.VIEW_ADS
    write_permission = WorkspacePermission.MANAGE_ADS

    def get_queryset(self):
        queryset = (
            AdPublication.objects
            .filter(workspace=self.get_workspace())
            .exclude(source="import")
            .select_related(
                "avito_account",
                "creative",
                "task",
                "batch",
            )
            .order_by("-created_at")
        )

        batch_id = self.request.query_params.get("batch")
        avito_account_id = self.request.query_params.get("avito_account")
        status_value = self.request.query_params.get("status")
        source_value = self.request.query_params.get("source")
        search = (self.request.query_params.get("search") or "").strip()

        allowed_sources = [
            AdPublication.Source.AUTO,
            AdPublication.Source.MANUAL,
            AdPublication.Source.AVITO_EXCEL,
        ]

        if source_value:
            if source_value not in allowed_sources:
                return queryset.none()

            queryset = queryset.filter(source=source_value)

        if batch_id:
            queryset = queryset.filter(batch_id=batch_id)

        if avito_account_id:
            queryset = queryset.filter(avito_account_id=avito_account_id)

        if status_value:
            queryset = queryset.filter(status=status_value)

        if search:
            queryset = queryset.filter(
                Q(row_id__icontains=search) |
                Q(address__icontains=search) |
                Q(creative__title__icontains=search) |
                Q(avito_listing__avito_id__icontains=search)
            )

        return queryset

    def partial_update(self, request, *args, **kwargs):
        publication = self.get_object()
        serializer = AdPublicationUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            updated_publication = update_ad_publication(
                publication_id=publication.id,
                workspace=self.get_workspace(),
                **serializer.validated_data,
            )
        except AdEditingError as exc:
            raise ValidationError({"detail": str(exc)})

        output_serializer = self.get_serializer(updated_publication)
        return Response(output_serializer.data)

    @action(detail=True, methods=["patch"], url_path="extend")
    def extend(self, request, *args, **kwargs):
        publication = self.get_object()

        try:
            updated_publication = extend_ad_publication(
                publication_id=publication.id,
                workspace=self.get_workspace(),
            )
        except AdPublication.DoesNotExist:
            raise ValidationError({"detail": "Публикация не найдена."})

        output_serializer = self.get_serializer(updated_publication)
        return Response(output_serializer.data)

    @action(detail=True, methods=["patch"], url_path="inherit-creative-date-end")
    def inherit_creative_date_end(self, request, *args, **kwargs):
        publication = self.get_object()

        try:
            updated_publication = inherit_creative_date_end_for_publication(
                publication_id=publication.id,
                workspace=self.get_workspace(),
            )
        except AdPublication.DoesNotExist:
            raise ValidationError({"detail": "Публикация не найдена."})

        output_serializer = self.get_serializer(updated_publication)
        return Response(output_serializer.data)


class AdBatchViewSet(WorkspaceScopedModelViewSet):
    serializer_class = AdBatchSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    http_method_names = ["get", "head", "options"]
    read_permission = WorkspacePermission.VIEW_ADS

    def get_queryset(self):
        queryset = (
            AdBatch.objects
            .filter(workspace=self.get_workspace())
            .select_related("task", "created_by")
            .order_by("-created_at")
        )

        source_value = self.request.query_params.get("source")
        status_value = self.request.query_params.get("status")

        if source_value:
            queryset = queryset.filter(source=source_value)
        if status_value:
            queryset = queryset.filter(status=status_value)

        return queryset


class AdCreativeViewSet(WorkspaceScopedModelViewSet):
    serializer_class = AdCreativeSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    http_method_names = ["get", "patch", "delete", "head", "options"]
    read_permission = WorkspacePermission.VIEW_ADS
    write_permission = WorkspacePermission.MANAGE_ADS

    def get_serializer_class(self):
        if self.action in {"retrieve", "partial_update"}:
            return AdCreativeEditSerializer

        return AdCreativeSerializer

    def get_queryset(self):
        if self.action in {"retrieve", "partial_update", "destroy"}:
            return (
                AdCreative.objects
                .filter(workspace=self.get_workspace())
                .exclude(source="import")
                .select_related("option_category")
                .only(
                    "id",
                    "workspace_id",
                    "option_category_id",
                    "option_category__category",
                    "title",
                    "description",
                    "image_urls",
                    "base_data",
                    "option_data",
                    "updated_at",
                )
            )

        queryset = (
            AdCreative.objects
            .filter(workspace=self.get_workspace())
            .exclude(source="import")
            .select_related(
                "task",
                "batch",
                "option_category",
            )
            .prefetch_related(
                Prefetch(
                    "publications",
                    queryset=AdPublication.objects.select_related("avito_account"),
                )
            )
            .annotate(publications_count=Count("publications", distinct=True))
            .order_by("-created_at")
        )

        source_value = self.request.query_params.get("source")
        task_id = self.request.query_params.get("task")
        batch_id = self.request.query_params.get("batch")
        avito_account_id = self.request.query_params.get("avito_account")
        search = (self.request.query_params.get("search") or "").strip()

        if source_value:
            if source_value not in [AdCreative.Source.AUTO, AdCreative.Source.MANUAL]:
                return queryset.none()

            queryset = queryset.filter(source=source_value)

        if task_id:
            queryset = queryset.filter(task_id=task_id)

        if batch_id:
            queryset = queryset.filter(batch_id=batch_id)

        if avito_account_id:
            queryset = queryset.filter(publications__avito_account_id=avito_account_id)

        if search:
            queryset = queryset.filter(title__icontains=search)

        return queryset.distinct()

    def partial_update(self, request, *args, **kwargs):
        creative = self.get_object()
        serializer = AdCreativeUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            updated_creative = update_ad_creative(
                creative_id=creative.id,
                workspace=self.get_workspace(),
                **serializer.validated_data,
            )
        except AdEditingError as exc:
            raise ValidationError({"detail": str(exc)})

        output_serializer = self.get_serializer(updated_creative)
        return Response(output_serializer.data)

    def destroy(self, request, *args, **kwargs):
        creative = self.get_object()

        delete_ad_creative(
            creative_id=creative.id,
            workspace=self.get_workspace(),
        )

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["patch"], url_path="extend-publications")
    def extend_publications(self, request, *args, **kwargs):
        creative = self.get_object()

        try:
            updated_creative = extend_ad_creative_publications(
                creative_id=creative.id,
                workspace=self.get_workspace(),
            )
        except AdCreative.DoesNotExist:
            raise ValidationError({"detail": "Креатив не найден."})

        output_serializer = AdCreativeSerializer(
            updated_creative,
            context=self.get_serializer_context(),
        )
        return Response(output_serializer.data)


# backend/avitotask/api_views.py
class ManualMassPostingView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        workspace = get_request_workspace(
            request,
            required_permission=WorkspacePermission.MANAGE_ADS,
        )

        serializer = ManualMassPostingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        avito_accounts = list(
            AvitoAccount.objects.filter(
                workspace=workspace,
                id__in=serializer.validated_data["avito_account_ids"],
                is_active=True,
            )
        )

        found_ids = {account.id for account in avito_accounts}
        requested_ids = set(serializer.validated_data["avito_account_ids"])
        missing_ids = sorted(requested_ids - found_ids)

        if missing_ids:
            raise ValidationError({
                "avito_account_ids": f"Аккаунты Avito не найдены или неактивны: {missing_ids}"
            })

        try:
            result = create_manual_mass_posting(
                workspace=workspace,
                avito_accounts=avito_accounts,
                addresses=serializer.validated_data["addresses"],
                title=serializer.validated_data["title"],
                description=serializer.validated_data["description"],
                image_urls=serializer.validated_data.get("image_urls", []),
                base_data=serializer.validated_data.get("base_data", {}),
                option_data=serializer.validated_data.get("option_data", {}),
                option_category=serializer.validated_data["option_category"],
                user=request.user,
            )
        except AdGenerationError as exc:
            raise ValidationError({"detail": str(exc)})

        return Response(
            {
                "batch": {
                    "id": result.batch.id,
                    "source": result.batch.source,
                    "status": result.batch.status,
                    "total_creatives": result.batch.total_creatives,
                    "total_publications": result.batch.total_publications,
                },
                "creative": {
                    "id": result.creative.id,
                    "title": result.creative.title,
                    "option_category_id": result.creative.option_category_id,
                    "option_category": (
                        result.creative.option_category.category
                        if result.creative.option_category
                        else None
                    ),
                },
                "publications": [
                    {
                        "id": publication.id,
                        "row_id": publication.row_id,
                        "avito_account_id": publication.avito_account_id,
                        "address": publication.address,
                        "status": publication.status,
                    }
                    for publication in result.publications
                ],
            },
            status=status.HTTP_201_CREATED,
        )
