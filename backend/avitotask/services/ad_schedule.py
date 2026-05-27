import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone

from avitotask.models import AdGenerationTask, AdGenerationTaskRun
from avitotask.services.ad_generation import AdGenerationError, generate_ads_from_task

logger = logging.getLogger(__name__)

VALID_INTERVAL_DAYS = {7, 14, 21, 28}

DEFAULT_SCHEDULE_TIMEZONE = "Europe/Moscow"

FREQUENCY_TO_INTERVAL_DAYS = {
    1: 7,
    2: 14,
    3: 21,
    4: 28,
}

INTERVAL_DAYS_TO_FREQUENCY = {
    7: 1,
    14: 2,
    21: 3,
    28: 4,
}

DAY_ALIASES = {
    "Пн": 0, "Понедельник": 0, "Monday": 0, "monday": 0,
    "Вт": 1, "Вторник": 1, "Tuesday": 1, "tuesday": 1,
    "Ср": 2, "Среда": 2, "Wednesday": 2, "wednesday": 2,
    "Чт": 3, "Четверг": 3, "Thursday": 3, "thursday": 3,
    "Пт": 4, "Пятница": 4, "Friday": 4, "friday": 4,
    "Сб": 5, "Суббота": 5, "Saturday": 5, "saturday": 5,
    "Вс": 6, "Воскресенье": 6, "Sunday": 6, "sunday": 6,
}

STRICT_HH_MM_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class AdScheduleError(AdGenerationError):
    """Ошибка расписания задачи генерации."""


def normalize_schedule(schedule, *, publication_interval_days=None):
    """
    Возвращает расписание в едином формате:
    {
        "frequency": 1|2|3|4,
        "days": ["10:00", None, None, None, None, None, None],
    }

    Поддержка старого формата {'Пн': '10:00'} нужна только на переходный период.
    """
    if not schedule:
        raise AdScheduleError("У задачи нет расписания")

    if isinstance(schedule, dict) and "frequency" in schedule and "days" in schedule:
        frequency = schedule["frequency"]
        days = schedule["days"]
    elif isinstance(schedule, dict):
        frequency = INTERVAL_DAYS_TO_FREQUENCY.get(int(publication_interval_days or 7))
        days = [None] * 7

        for raw_day, raw_time in schedule.items():
            day_index = parse_day_index(raw_day)

            if isinstance(raw_time, list):
                filled_times = [value for value in raw_time if value]
                if len(filled_times) > 1:
                    raise AdScheduleError("В новом расписании поддерживается один слот времени на день")
                raw_time = filled_times[0] if filled_times else None

            days[day_index] = raw_time
    else:
        raise AdScheduleError("Некорректный формат расписания")

    if frequency not in FREQUENCY_TO_INTERVAL_DAYS:
        raise AdScheduleError("frequency должен быть 1, 2, 3 или 4")
    if not isinstance(days, list) or len(days) != 7:
        raise AdScheduleError("days должен быть массивом из 7 элементов")

    normalized_days = []
    for value in days:
        if value in ("", None):
            normalized_days.append(None)
            continue

        if not isinstance(value, str) or not STRICT_HH_MM_RE.match(value):
            raise AdScheduleError("Время в расписании должно быть строго в формате HH:mm")

        normalized_days.append(value)

    if not any(normalized_days):
        raise AdScheduleError("В расписании должен быть выбран хотя бы один день")

    return {
        "frequency": int(frequency),
        "days": normalized_days,
    }


def parse_day_index(day_name):
    if day_name not in DAY_ALIASES:
        raise AdScheduleError(f"Неизвестный день недели: {day_name}")

    return DAY_ALIASES[day_name]


def get_schedule_timezone(timezone_name):
    timezone_name = timezone_name or DEFAULT_SCHEDULE_TIMEZONE

    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        raise AdScheduleError(f"Неизвестный timezone расписания: {timezone_name}")


def parse_anchor_date(anchor_date):
    if isinstance(anchor_date, date) and not isinstance(anchor_date, datetime):
        return anchor_date
    if isinstance(anchor_date, datetime):
        return anchor_date.date()
    if isinstance(anchor_date, str):
        return date.fromisoformat(anchor_date)
    raise AdScheduleError("schedule_anchor_date должен быть датой YYYY-MM-DD")


def make_aware_in_schedule_timezone(value, tz):
    if timezone.is_aware(value):
        return value.astimezone(tz)
    return value.replace(tzinfo=tz)


def iso_week_start(value):
    return value - timedelta(days=value.weekday())


def is_valid_frequency_week(candidate_date, anchor_date, frequency):
    weeks_diff = (iso_week_start(candidate_date) - iso_week_start(anchor_date)).days // 7
    return weeks_diff >= 0 and weeks_diff % frequency == 0


def calculate_next_run_at(schedule, anchor_date, now, timezone_name):
    """
    Считает ближайший будущий слот запуска.

    frequency:
    1 = каждую неделю
    2 = раз в 2 ISO-недели от anchor
    3 = раз в 3 ISO-недели от anchor
    4 = раз в 4 ISO-недели от anchor
    """
    if not schedule:
        return None

    norzalized_schedule = normalize_schedule(schedule)
    tz = get_schedule_timezone(timezone_name)
    local_now = make_aware_in_schedule_timezone(now, tz)
    anchor = parse_anchor_date(anchor_date)

    frequency = norzalized_schedule["frequency"]
    days = norzalized_schedule["days"]

    for offset in range(0, 370):
        candidate_date = local_now.date() + timedelta(days=offset)
        day_time = days[candidate_date.weekday()]

        if not day_time:
            continue

        if not is_valid_frequency_week(candidate_date, anchor, frequency):
            continue

        hour, minute = map(int, day_time.split(":"))
        candidate = datetime.combine(
            candidate_date,
            time(hour=hour, minute=minute),
            tzinfo=tz
        )

        if candidate > local_now:
            return candidate

    raise AdScheduleError("Не удалось рассчитать следующую дату запуска")


def recalculate_task_next_update_time(task, *, now=None, save=True):
    now = now or timezone.now()

    if not task.is_active:
        task.next_update_time = None

        if save:
            task.save(update_fields=["next_update_time", "updated_at"])

        return None

    normalized_schedule = normalize_schedule(
        task.schedule,
        publication_interval_days=task.publication_interval_days
    )

    if not task.schedule_anchor_date:
        task.schedule_anchor_date = timezone.localtime(now).date()

    task.schedule = normalized_schedule
    task.publication_interval_days = FREQUENCY_TO_INTERVAL_DAYS[normalized_schedule["frequency"]]
    task.next_update_time = calculate_next_run_at(
        normalized_schedule,
        task.schedule_anchor_date,
        now,
        task.schedule_timezone
    )

    if save:
        task.save(update_fields=[
            "schedule",
            "publication_interval_days",
            "schedule_anchor_date",
            "next_update_time",
            "updated_at"
        ])

    return task.next_update_time


def initialize_task_schedule(task, *, from_dt=None):
    return recalculate_task_next_update_time(task, now=from_dt or timezone.now())


def advance_task_schedule_after_run(task, *, run_at=None):
    run_at = run_at or timezone.now()

    task.last_run_at = run_at
    task.last_successful_run_at = run_at
    task.last_run_status = AdGenerationTask.LastRunStatus.SUCCESS
    task.last_run_error = None
    task.next_update_time = calculate_next_run_at(
        task.schedule,
        task.schedule_anchor_date,
        run_at,
        task.schedule_timezone
    )

    task.save(update_fields=[
        "last_run_at",
        "last_successful_run_at",
        "last_run_status",
        "last_run_error",
        "next_update_time",
        "updated_at"
    ])

    return task.next_update_time


def run_due_ad_generation_tasks(*, limit=50, now_dt=None):
    from avitotask.services.ad_task_runner import run_autogeneration_task

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
        scheduled_for = task.next_update_time

        try:
            if not is_schedule_due_at(task, now_dt):
                recalculate_task_next_update_time(task, now=now_dt)
                continue

            result = run_autogeneration_task(
                task.id,
                triggered_by="schedule",
                scheduled_for=scheduled_for,
                workspace=task.workspace,
                now=now_dt,
            )

            if result.created and result.run.status == AdGenerationTaskRun.Status.SUCCESS:
                generated_count += 1

        except AdGenerationError:
            logger.exception("Failed to generate ads for task_id=%s", task.id)
            continue

    return generated_count


@dataclass(frozen=True)
class ScheduleSlot:
    day_index: int
    slot_time: time


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


def is_schedule_due_at(task, now_dt):
    if not task.next_update_time:
        return False

    scheduled_for = make_aware_in_schedule_timezone(
        task.next_update_time,
        get_schedule_timezone(task.schedule_timezone),
    )
    local_now = make_aware_in_schedule_timezone(
        now_dt,
        get_schedule_timezone(task.schedule_timezone),
    )

    if scheduled_for.replace(second=0, microsecond=0) != local_now.replace(second=0, microsecond=0):
        return False

    expected_next_run = calculate_next_run_at(
        task.schedule,
        task.schedule_anchor_date,
        local_now - timedelta(minutes=1),
        task.schedule_timezone,
    )

    return (
            expected_next_run.replace(second=0, microsecond=0)
            == scheduled_for.replace(second=0, microsecond=0)
    )
