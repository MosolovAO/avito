from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from django.utils import timezone
from asgiref.sync import sync_to_async

from django.db.models import Exists, OuterRef, Q
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import WorkspacePermission
from accounts.workspace_context import get_request_workspace
from avitotask.models import AvitoAccount, AvitoListing, AvitoOAuthToken
from avitotask.services.avito_api import AvitoApiError
from calls.models import Call, CallSyncState
from calls.services import AudioUnavailable, open_call_audio

MOSCOW = ZoneInfo("Europe/Moscow")


class CallQuerySerializer(serializers.Serializer):
    avito_account_id = serializers.IntegerField(min_value=1)
    date = serializers.DateField(required=False)
    search = serializers.CharField(required=False, allow_blank=True, max_length=100)


class CallSerializer(serializers.ModelSerializer):
    listing = serializers.SerializerMethodField()

    class Meta:
        model = Call
        fields = [
            "id", "external_id", "occurred_at", "buyer_phone",
            "talk_duration", "waiting_duration", "is_missed",
            "call_type", "listing",
        ]

    def get_listing(self, obj):
        listing = (
            obj.listing if obj.listing_id
            else self.context.get("late_listings", {}).get(obj.avito_item_id)
        )
        if listing:
            return {
                "id": listing.pk,
                "avito_id": listing.avito_id,
                "title": listing.title,
                "url": listing.url,
            }
        if obj.avito_item_id:
            return {
                "id": None,
                "avito_id": obj.avito_item_id,
                "title": None,
                "url": None,
            }
        return None


class CallPagination(PageNumberPagination):
    page_size = 30
    page_size_query_param = "page_size"
    max_page_size = 100


class CallListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CallSerializer
    pagination_class = CallPagination

    def get_serializer(self, *args, **kwargs):
        if args and kwargs.get("many"):
            calls = args[0]
            missing_ids = {
                call.avito_item_id for call in calls
                if not call.listing_id and call.avito_item_id
            }
            if missing_ids:
                first = calls[0]
                listings = AvitoListing.objects.filter(
                    workspace_id=first.workspace_id,
                    avito_account_id=first.avito_account_id,
                    avito_id__in=missing_ids,
                )
                kwargs.setdefault("context", self.get_serializer_context())[
                    "late_listings"
                ] = {listing.avito_id: listing for listing in listings}
        return super().get_serializer(*args, **kwargs)

    def get_queryset(self):
        workspace = get_request_workspace(
            self.request,
            required_permission=WorkspacePermission.VIEW_CALLS,
        )
        query = CallQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        account = get_object_or_404(
            AvitoAccount,
            pk=query.validated_data["avito_account_id"],
            workspace=workspace,
        )

        calls = Call.objects.filter(
            workspace=workspace,
            avito_account=account,
        ).select_related("listing").order_by("-occurred_at", "-id")

        day = query.validated_data.get("date")
        if day:
            start = datetime.combine(day, time.min, tzinfo=MOSCOW)
            end = datetime.combine(
                day + timedelta(days=1), time.min, tzinfo=MOSCOW,
            )
            calls = calls.filter(occurred_at__gte=start, occurred_at__lt=end)

        search = query.validated_data.get("search", "").strip()
        if search:
            matching_late_listing = AvitoListing.objects.filter(
                workspace=workspace,
                avito_account=account,
                avito_id=OuterRef("avito_item_id"),
                title__icontains=search,
            )
            calls = calls.alias(
                matching_late_listing=Exists(matching_late_listing),
            )
            matches = (
                Q(buyer_phone__icontains=search)
                | Q(listing__title__icontains=search)
                | Q(avito_item_id__icontains=search)
                | Q(matching_late_listing=True)
            )
            if all(char.isdigit() or char in "+ ()-" for char in search):
                digits = "".join(char for char in search if char.isdigit())
                if digits:
                    matches |= Q(normalized_phone__contains=digits)
            calls = calls.filter(matches)

        return calls


class _CallAudioStream:
    def __init__(self, upstream):
        self.upstream = upstream
        self.chunks = iter(upstream.iter_content(chunk_size=64 * 1024))

    async def __aiter__(self):
        read_chunk = sync_to_async(next)
        try:
            while True:
                chunk = await read_chunk(self.chunks, None)
                if chunk is None:
                    break
                yield chunk
        finally:
            await sync_to_async(self.close)()

    def close(self):
        self.upstream.close()


class CallAudioView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        workspace = get_request_workspace(
            request,
            required_permission=WorkspacePermission.VIEW_CALLS,
        )
        call = get_object_or_404(
            Call.objects.select_related("avito_account"),
            pk=pk,
            workspace=workspace,
            avito_account__workspace=workspace,
        )
        try:
            token = call.avito_account.oauth_tokens
        except AvitoOAuthToken.DoesNotExist:
            return Response(
                {"detail": "Аккаунт Авито не подключён."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        try:
            upstream = open_call_audio(token, call.external_id)
        except AudioUnavailable:
            return Response(
                {
                    "code": "audio_unavailable",
                    "detail": "Аудио пока недоступно.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        except AvitoApiError:
            return Response(
                {"detail": "Не удалось получить аудио от Авито."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        def chunks():
            try:
                yield from upstream.iter_content(chunk_size=64 * 1024)
            finally:
                upstream.close()

        response = StreamingHttpResponse(
            _CallAudioStream(upstream), content_type="audio/mpeg",
        )
        length = upstream.headers.get("Content-Length")
        if length and length.isdigit():
            response["Content-Length"] = length
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class CallSyncStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        workspace = get_request_workspace(
            request,
            required_permission=WorkspacePermission.VIEW_CALLS,
        )
        query = CallQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        account = get_object_or_404(
            AvitoAccount,
            pk=query.validated_data["avito_account_id"],
            workspace=workspace,
        )
        state = CallSyncState.objects.filter(avito_account=account).first()

        active = bool(
            state and state.lease_until
            and state.lease_until > timezone.now()
        )

        return Response({
            "last_synced_at": (
                state.last_synced_at.isoformat()
                if state and state.last_synced_at else None
            ),
            "backfill_complete": state.backfill_complete if state else False,
            "classification_complete": (
                state.classification_complete if state else False
            ),
            "is_syncing": active,
            "phase": state.phase if active else None,
            "last_error": state.last_error if state else "",
        })
