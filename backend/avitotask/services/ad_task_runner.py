from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from avitotask.models import (
    AdGenerationTask,
    AdGenerationTaskRun,
    AdPublication,
)
from avitotask.services.ad_generation import (
    AdGenerationError,
    GenerationResult,
    generate_ads_from_task,
)
from avitotask.services.ad_schedule import recalculate_task_next_update_time
from avitotask.services.ad_export_queue import queue_avito_account_csv_exports


@dataclass(frozen=True)
class AutogenerationTaskRunResult:
    run: AdGenerationTaskRun
    batch: object | None
    creative: object | None
    publications: list[AdPublication]
    csv_export_status: str
    created: bool

    @property
    def publications_count(self):
        return self.run.publications_count


def run_autogeneration_task(
        task_id,
        *,
        triggered_by,
        scheduled_for=None,
        workspace=None,
        user=None,
        now=None,
):
    """
    Единая точка запуска задачи.

    Manual и scheduler должны вызывать эту функцию, чтобы генерация,
    статусы, run-таблица и CSV dirty-state не расходились.
    """
    if triggered_by not in AdGenerationTaskRun.TriggeredBy.values:
        raise AdGenerationError("triggered_by должен быть manual или schedule")

    now_dt = now or timezone.now()
    caught_error = None
    result = None

    with transaction.atomic():
        task = _get_locked_task(task_id=task_id, workspace=workspace)

        if scheduled_for is not None:
            existing_run = (
                AdGenerationTaskRun.objects
                .select_for_update()
                .filter(task=task, scheduled_for=scheduled_for)
                .first()
            )
            if existing_run is not None:
                return _build_result_from_existing_run(existing_run)

        run = AdGenerationTaskRun.objects.create(
            workspace=task.workspace,
            task=task,
            triggered_by=triggered_by,
            scheduled_for=scheduled_for,
            started_at=now_dt,
            status=AdGenerationTaskRun.Status.RUNNING,
        )

        _mark_task_running(task)

        try:
            if triggered_by == AdGenerationTaskRun.TriggeredBy.SCHEDULE and not task.is_active:
                raise AdGenerationError("Задача генерации не активна")

            generation_result = generate_ads_from_task(
                task.id,
                workspace=task.workspace,
                user=user,
                require_active=triggered_by == AdGenerationTaskRun.TriggeredBy.SCHEDULE,
            )

            csv_export_ids = list(
                task.avito_accounts.values_list("id", flat=True)
            )
            csv_export_status = queue_avito_account_csv_exports(csv_export_ids)
            run.batch = generation_result.batch
            run.creative = generation_result.creative
            run.publications_count = len(generation_result.publications)
            run.csv_export_ids = csv_export_ids
            run.status = AdGenerationTaskRun.Status.SUCCESS
            run.finished_at = now_dt
            run.error = None
            run.save(update_fields=[
                "batch",
                "creative",
                "publications_count",
                "csv_export_ids",
                "status",
                "finished_at",
                "error",
            ])

            _mark_task_success(task, now_dt=now_dt)

            result = AutogenerationTaskRunResult(
                run=run,
                batch=generation_result.batch,
                creative=generation_result.creative,
                publications=generation_result.publications,
                csv_export_status=csv_export_status,
                created=True,
            )
        except Exception as exc:
            caught_error = exc

            run.status = AdGenerationTaskRun.Status.ERROR
            run.finished_at = now_dt
            run.error = str(exc)
            run.save(update_fields=["status", "finished_at", "error"])

            _mark_task_error(task, now_dt=now_dt, error=exc)

    if caught_error is not None:
        raise caught_error

    return result


def _get_locked_task(*, task_id, workspace=None):
    queryset = (
        AdGenerationTask.objects
        .select_for_update(of=("self",))
        .select_related("workspace")
        .prefetch_related("avito_accounts")
        .filter(id=task_id)
    )

    if workspace is not None:
        queryset = queryset.filter(workspace=workspace)

    try:
        return queryset.get()
    except AdGenerationTask.DoesNotExist:
        raise AdGenerationError("Задача генерации не найдена")



def _mark_task_running(task):
    task.last_run_status = AdGenerationTask.LastRunStatus.RUNNING
    task.last_run_error = None
    task.save(update_fields=["last_run_status", "last_run_error", "updated_at"])


def _mark_task_success(task, *, now_dt):
    task.last_run_at = now_dt
    task.last_successful_run_at = now_dt
    task.last_run_status = AdGenerationTask.LastRunStatus.SUCCESS
    task.last_run_error = None

    if task.is_active and task.schedule:
        recalculate_task_next_update_time(task, now=now_dt, save=False)
    else:
        task.next_update_time = None

    task.save(update_fields=[
        "last_run_at",
        "last_successful_run_at",
        "last_run_status",
        "last_run_error",
        "schedule",
        "publication_interval_days",
        "schedule_anchor_date",
        "next_update_time",
        "updated_at",
    ])


def _mark_task_error(task, *, now_dt, error):
    task.last_run_at = now_dt
    task.last_run_status = AdGenerationTask.LastRunStatus.ERROR
    task.last_run_error = str(error)
    task.save(update_fields=[
        "last_run_at",
        "last_run_status",
        "last_run_error",
        "updated_at",
    ])


def _build_result_from_existing_run(run):
    publications = []

    if run.creative_id:
        publications = list(
            AdPublication.objects.filter(
                workspace=run.workspace,
                creative_id=run.creative_id,
            )
        )

    return AutogenerationTaskRunResult(
        run=run,
        batch=run.batch,
        creative=run.creative,
        publications=publications,
        csv_export_status="queued" if run.csv_export_ids else "none",
        created=False,
    )
