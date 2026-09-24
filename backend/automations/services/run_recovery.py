from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.db.models import Q

from automations.models import AutomationRun

RECOVERY_BATCH_SIZE = 100
MAX_RUN_RETRIES = 3
RUN_HEARTBEAT_TIMEOUT = timedelta(minutes=10)

WORKER_LOST_MESSAGE = (
    "Worker перестал обновлять состояние запуска автоматизации."
)


@dataclass(frozen=True, slots=True)
class RunRecoveryResult:
    """Результат одного ограниченного прохода recovery."""

    selected: int
    dispatched: int
    failed: int


def recover_automation_runs(
        *,
        recovered_at,
) -> RunRecoveryResult:
    """
    Возвращает в очередь due и зависшие run.

    За один вызов обрабатывается не более 100 строк. Выбранные строки
    блокируются через skip_locked, поэтому параллельный recovery не ждёт
    уже обрабатываемый batch.
    """

    stale_before = recovered_at - RUN_HEARTBEAT_TIMEOUT

    due_runnable = (
            Q(
                status__in=[
                    AutomationRun.Status.QUEUED,
                    AutomationRun.Status.WAITING_FOR_DATA,
                ],
            )
            & (
                    Q(next_attempt_at__isnull=True)
                    | Q(next_attempt_at__lte=recovered_at)
            )
    )
    stale_evaluating = (
            Q(status=AutomationRun.Status.EVALUATING)
            & (
                    Q(next_attempt_at__isnull=True)
                    | Q(next_attempt_at__lte=recovered_at)
            )
            & (
                    Q(heartbeat_at__isnull=True)
                    | Q(heartbeat_at__lte=stale_before)
            )
    )

    dispatch_ids: list[int] = []
    changed_runs: list[AutomationRun] = []
    failed_count = 0

    with transaction.atomic():
        runs = list(
            AutomationRun.objects
            .select_for_update(skip_locked=True)
            .filter(due_runnable | stale_evaluating)
            .only(
                "id",
                "status",
                "retry_count",
                "next_attempt_at",
                "run_token",
                "heartbeat_at",
                "finished_at",
                "error_code",
                "error_message",
                "updated_at",
            )
            .order_by("id")[:RECOVERY_BATCH_SIZE]
        )

        for run in runs:
            if run.status != AutomationRun.Status.EVALUATING:
                dispatch_ids.append(run.id)
                continue

            run.run_token = None
            run.heartbeat_at = None
            run.next_attempt_at = None
            run.error_code = "worker_lost"
            run.error_message = WORKER_LOST_MESSAGE
            run.updated_at = recovered_at

            if run.retry_count < MAX_RUN_RETRIES:
                run.status = AutomationRun.Status.QUEUED
                run.retry_count += 1
                dispatch_ids.append(run.id)
            else:
                run.status = AutomationRun.Status.FAILED
                run.finished_at = recovered_at
                failed_count += 1

            changed_runs.append(run)

        if changed_runs:
            AutomationRun.objects.bulk_update(
                changed_runs,
                fields=[
                    "status",
                    "retry_count",
                    "next_attempt_at",
                    "run_token",
                    "heartbeat_at",
                    "finished_at",
                    "error_code",
                    "error_message",
                    "updated_at",
                ],
            )

        _dispatch_runs_after_commit(dispatch_ids)

    return RunRecoveryResult(
        selected=len(runs),
        dispatched=len(dispatch_ids),
        failed=failed_count,
    )


def _dispatch_runs_after_commit(run_ids: list[int]) -> None:
    """Отправляет run в Celery только после успешного commit."""

    if not run_ids:
        return

    frozen_run_ids = tuple(run_ids)

    def dispatch() -> None:
        from automations.tasks import evaluate_automation_run_task

        for run_id in frozen_run_ids:
            evaluate_automation_run_task.delay(run_id)

    transaction.on_commit(dispatch)
