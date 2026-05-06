from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from avitotask.models import AdPublication


@dataclass(frozen=True)
class AdCleanupResult:
    archived_publications: int


@transaction.atomic
def archive_stale_publications(workspace=None, older_than_days=60, limit=1000):
    cutoff = timezone.now() - timedelta(days=older_than_days)

    queryset = (
        AdPublication.objects
        .select_related("avito_listing")
        .filter(created_at__lt=cutoff)
        .exclude(status__in=[AdPublication.Status.ACTIVE, AdPublication.Status.ARCHIVED])
        .filter(
            Q(avito_listing__isnull=True)
            | Q(avito_listing__status__in=["removed", "old", "blocked", "rejected", "not_found"])
        )
        .order_by("id")
    )

    if workspace is not None:
        queryset = queryset.filter(workspace=workspace)

    publication_ids = list(queryset.values_list("id", flat=True)[:limit])

    if not publication_ids:
        return AdCleanupResult(archived_publications=0)

    archived_at = timezone.now()

    updated_count = (
        AdPublication.objects
        .filter(id__in=publication_ids)
        .update(
            status=AdPublication.Status.ARCHIVED,
            archived_at=archived_at,
        )
    )

    return AdCleanupResult(archived_publications=updated_count)


