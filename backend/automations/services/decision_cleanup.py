from dataclasses import dataclass

from django.utils import timezone

from automations.models import AvitoListingDecision
from automations.modules.avito_listings.decision_lifecycle import (
    DecisionTransitionError,
    expire_decision,
)

DECISION_CLEANUP_BATCH_SIZE = 100


@dataclass(frozen=True, slots=True)
class DecisionCleanupResult:
    """Результат одного ограниченного прохода очистки."""

    selected: int
    expired: int
    skipped: int
    busy: int


def expire_pending_decisions(*, expired_at) -> DecisionCleanupResult:
    """
    Закрывает не более 100 решений с истёкшим сроком подтверждения.

    Список идентификаторов фиксируется одним индексированным запросом.
    Каждое решение затем обрабатывается собственной короткой транзакцией.
    """
    if timezone.is_naive(expired_at):
        raise ValueError(
            "Время очистки решений должно содержать часовой пояс.",
        )

    candidates = tuple(
        AvitoListingDecision.objects
        .filter(
            status=AvitoListingDecision.Status.PENDING_APPROVAL,
            expires_at__lte=expired_at,
        )
        .order_by("expires_at", "id")
        .values_list(
            "workspace_id",
            "run_id",
            "id",
        )[:DECISION_CLEANUP_BATCH_SIZE]
    )

    expired_count = 0
    skipped_count = 0
    busy_count = 0

    for workspace_id, run_id, decision_id in candidates:
        try:
            transition = expire_decision(
                workspace_id=workspace_id,
                run_id=run_id,
                decision_id=decision_id,
                expired_at=expired_at,
            )
        except DecisionTransitionError as error:
            if error.code != "resource_busy":
                raise

            busy_count += 1
            continue

        if transition.changed:
            expired_count += 1
        else:
            skipped_count += 1

    return DecisionCleanupResult(
        selected=len(candidates),
        expired=expired_count,
        skipped=skipped_count,
        busy=busy_count,
    )
