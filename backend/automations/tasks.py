from celery import shared_task
from django.utils import timezone

from automations.services.run_executor import execute_run

from automations.services.run_recovery import (
    recover_automation_runs,
)
from automations.services.decision_cleanup import (
    expire_pending_decisions,
)
from automations.modules.avito_listings.effect_recovery import (
    recover_pending_listing_effects,
)


@shared_task(
    queue="automations",
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=True,
    soft_time_limit=240,
    time_limit=300,
)
def evaluate_automation_run_task(run_id: int):
    """Передаёт обработку run доменному executor-у."""

    return execute_run(run_id=run_id)


@shared_task(
    queue="automations",
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=True,
    soft_time_limit=60,
    time_limit=90,
)
def recover_automation_runs_task():
    """Запускает один ограниченный проход recovery и TTL cleanup."""

    recovered_at = timezone.now()

    recovery_result = recover_automation_runs(
        recovered_at=recovered_at,
    )
    expire_pending_decisions(
        expired_at=recovered_at,
    )
    recover_pending_listing_effects(
        recovered_at=recovered_at,
    )

    return recovery_result
