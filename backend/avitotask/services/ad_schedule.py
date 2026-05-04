import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from django.utils import timezone

from avitotask.models import AdGenerationTask
from avitotask.services.ad_generation import AdGenerationError, generate_ads_from_task

logger = logging.getLogger(__name__)

VALID_INTERVAL_DAYS = {7, 14, 21, 28}

DAY_ALIASES = {
    "Пн": 0, "Понедельник": 0, "Monday": 0, "monday": 0,
    "Вт": 1, "Вторник": 1, "Tuesday": 1, "tuesday": 1,
    "Ср": 2, "Среда": 2, "Wednesday": 2, "wednesday": 2,
    "Чт": 3, "Четверг": 3, "Thursday": 3, "thursday": 3,
    "Пт": 4, "Пятница": 4, "Friday": 4, "friday": 4,
    "Сб": 5, "Суббота": 5, "Saturday": 5, "saturday": 5,
    "Вс": 6, "Воскресенье": 6, "Sunday": 6, "sunday": 6,
}


class AdScheduleError(AdGenerationError):
    """Ошибка расписания задачи генерации."""


@dataclass(frozen=True)
class ScheduleSlot:
    day_index: int
    slot_time: time


def initialize_task_schedule(task, *, from_dt=None):
    from_dt = from_dt or timezone.now()
    slots = parse_schedule_slots(task.schedule)
    interval_days = get_interval_days(task)

    first_slot = slots[0]
    cycle_start = get_cycle_start_for_week(from_dt, first_slot)
    cycle_datetimes = build_cycle_datetimes(cycle_start, slots)

    future_slots = [slot_dt for slot_dt in cycle_datetimes if slot_dt > from_dt]

    if not future_slots:
        cycle_start = cycle_start + timedelta(days=7)
        cycle_datetimes = build_cycle_datetimes(cycle_start, slots)
        future_slots = [slot_dt for slot_dt in cycle_datetimes if slot_dt > from_dt]

    if not future_slots:
        raise AdScheduleError("Не удалось рассчитать следующую дату публикации.")

    task.schedule_cycle_started_at = cycle_start
    task.next_update_time = future_slots[0]
    task.save(update_fields=["schedule_cycle_started_at", "next_update_time"])

    return task.next_update_time


def advance_task_schedule_after_run(task, *, run_at=None):
    run_at = run_at or timezone.now()
    slots = parse_schedule_slots(task.schedule)
    interval_days = get_interval_days(task)

    if not task.schedule_cycle_started_at:
        initialize_task_schedule(task, from_dt=run_at)
        task.refresh_from_db()

    schedule_dt = task.next_update_time or run_at
    cycle_start = task.schedule_cycle_started_at

    cycle_datetimes = build_cycle_datetimes(cycle_start, slots)
    future_slots_in_cycle = [
        slot_dt for slot_dt in cycle_datetimes
        if slot_dt > schedule_dt
    ]

    if future_slots_in_cycle:
        next_update_time = future_slots_in_cycle[0]
        next_cycle_start = cycle_start
    else:
        next_cycle_start = cycle_start + timedelta(days=interval_days)
        next_update_time = build_cycle_datetimes(next_cycle_start, slots)[0]

    task.schedule_cycle_started_at = next_cycle_start
    task.next_update_time = next_update_time
    task.last_run_at = run_at
    task.save(update_fields=["schedule_cycle_started_at", "next_update_time", "last_run_at"])

    return next_update_time


def run_due_ad_generation_tasks(*, limit=50, now_dt=None):
    now_dt = now_dt or timezone.now()

    tasks = list(
        AdGenerationTask.objects
        .select_related("workspace")
        .filter(
            is_active=True,
            next_update_time__isnull=False,
            next_update_time__lte=now_dt,
        )
        .order_by("next_update_time", "id")[:limit]
    )

    generated_count = 0

    for task in tasks:
        try:
            generate_ads_from_task(task.id, workspace=task.workspace)
        except AdGenerationError:
            logger.exception("Failed to generate ads for task_id=%s", task.id)
            advance_task_schedule_after_run(task, run_at=now_dt)
            continue

        advance_task_schedule_after_run(task, run_at=now_dt)
        generated_count += 1

    return generated_count


def parse_schedule_slots(schedule):
    if not schedule:
        raise AdScheduleError("У задачи нет расписания")

    slots = []

    for day_name, raw_times in schedule.items():
        day_index = parse_day_index(day_name)
        times = raw_times if isinstance(raw_times, list) else [raw_times]

        for raw_time in times:
            if raw_time:
                slots.append(ScheduleSlot(
                    day_index=day_index,
                    slot_time=parse_time(raw_time),
                ))
    if not slots:
        raise AdScheduleError("У задачи нет активных слотов расписания")

    return sorted(slots, key=lambda slot: (slot.day_index, slot.slot_time))


def parse_day_index(day_name):
    if day_name not in DAY_ALIASES:
        raise AdScheduleError(f"Неизвестный день недели: {day_name}")

    return DAY_ALIASES[day_name]


def parse_time(raw_time):
    if isinstance(raw_time, time):
        return raw_time

    return datetime.strptime(raw_time, "%H:%M").time()


def get_interval_days(task):
    interval_days = int(task.publication_interval_days)

    if interval_days not in VALID_INTERVAL_DAYS:
        raise AdScheduleError("Интервал публикации должен быть 7, 14, 21 или 28 дней.")

    return interval_days


def get_cycle_start_for_week(from_dt, first_slot):
    week_start_date = from_dt.date() - timedelta(days=from_dt.weekday())
    first_slot_date = week_start_date + timedelta(days=first_slot.day_index)

    return datetime.combine(first_slot_date, first_slot.slot_time)


def build_cycle_datetimes(cycle_start, slots):
    first_slot = slots[0]
    cycle_datetimes = []

    for slot in slots:
        day_offset = (slot.day_index - first_slot.day_index) % 7
        slot_date = cycle_start.date() + timedelta(days=day_offset)
        cycle_datetimes.append(datetime.combine(slot_date, slot.slot_time))

    return sorted(cycle_datetimes)
