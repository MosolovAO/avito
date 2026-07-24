from dataclasses import dataclass
from datetime import date, timedelta

from django.conf import settings

from analytics.models import (
    AvitoListingDailyStats,
    AvitoListingStatsCoverage,
)
from django.db import transaction
from django.db.models import (
    Case,
    CharField,
    DateField,
    DateTimeField,
    F,
    Q,
    TextField,
    Value,
    When,
)
from django.db.models.functions import Cast, Concat
from django.utils import timezone

from avitotask.models import AvitoListing, AvitoOAuthToken
from avitotask.services.avito_api import AvitoApiClient, AvitoApiError

AVITO_STATS_MAX_PERIOD_DAYS = 270
AVITO_STATS_DB_BATCH_SIZE = 500


@dataclass(frozen=True)
class AvitoProfileDailyStatsImportResult:
    total_received: int
    matched_listings: int
    created_stats: int
    updated_stats: int
    deleted_zero_stats: int
    confirmed_listings: int


@dataclass(frozen=True)
class AvitoStatsImportResult:
    total_listings: int
    total_days: int
    created_stats: int
    updated_stats: int
    unchanged_stats: int = 0


@dataclass(frozen=True)
class AvitoDailyStatsWriteResult:
    total_days: int
    created_stats: int
    updated_stats: int
    unchanged_stats: int


@dataclass(frozen=True)
class AvitoStatsBackfillRequest:
    date_from: date
    date_to: date
    listing_ids: tuple[int, ...]


def import_avito_listing_daily_stats_for_account(
        avito_account,
        date_from,
        date_to,
        listing_ids=None,
        session=None,
):
    """
    Загружает только базовые метрики stats/v1.

    Сетевые запросы намеренно выполняются вне общей транзакции.
    Повторный импорт безопасен благодаря unique(listing, date).
    """

    if not avito_account.external_account_id:
        raise AvitoApiError(
            "У AvitoAccount не заполнен external_account_id."
        )

    if date_from > date_to:
        raise ValueError("date_from не может быть больше date_to.")

    token = get_account_token(avito_account)
    listings = get_listings_for_stats(
        avito_account,
        listing_ids=listing_ids,
    )

    validate_listing_coverage_range(
        listings=listings,
        date_from=date_from,
        date_to=date_to,
    )

    if not listings:
        return AvitoStatsImportResult(
            total_listings=0,
            total_days=0,
            created_stats=0,
            updated_stats=0,
            unchanged_stats=0,
        )

    date_from = normalize_date(date_from)
    date_to = normalize_date(date_to)

    if date_from > date_to:
        raise ValueError("date_from не может быть больше date_to.")

    client = AvitoApiClient(session=session)
    listing_by_avito_id = {
        str(listing.avito_id): listing
        for listing in listings
    }

    total_days = 0
    created_stats = 0
    updated_stats = 0
    unchanged_stats = 0

    listings_batch_size = get_v1_listings_batch_size()

    for listings_chunk in chunked(
            listings,
            listings_batch_size,
    ):
        mark_listing_coverage_attempt(listings_chunk)

        try:
            try:
                item_ids = [
                    int(listing.avito_id)
                    for listing in listings_chunk
                ]
            except (TypeError, ValueError) as exc:
                raise AvitoApiError(
                    "В AvitoListing найден некорректный avito_id."
                ) from exc

            for range_from, range_to in split_date_range(
                    date_from,
                    date_to,
                    max_period_days=AVITO_STATS_MAX_PERIOD_DAYS,
            ):
                payload = client.get_item_stats(
                    token=token,
                    user_id=avito_account.external_account_id,
                    item_ids=item_ids,
                    date_from=range_from,
                    date_to=range_to,
                )

                result = payload.get("result") or {}
                write_result = bulk_upsert_daily_stats(
                    items=result.get("items") or [],
                    listing_by_avito_id=listing_by_avito_id,
                )

                total_days += write_result.total_days
                created_stats += write_result.created_stats
                updated_stats += write_result.updated_stats
                unchanged_stats += write_result.unchanged_stats

        except Exception as exc:
            mark_listing_coverage_error(
                listings=listings_chunk,
                error=str(exc),
            )
            raise

        mark_listing_coverage_success(
            listings=listings_chunk,
            date_from=date_from,
            date_to=date_to,
        )

    return AvitoStatsImportResult(
        total_listings=len(listings),
        total_days=total_days,
        created_stats=created_stats,
        updated_stats=updated_stats,
        unchanged_stats=unchanged_stats,
    )


def import_avito_profile_daily_stats_for_account(
        *,
        avito_account,
        stat_date,
        session=None,
):
    """
    Загружает финальную статистику профиля за один завершённый день.

    Все страницы Avito сначала загружаются в память. Изменения БД
    выполняются только после успешного получения полного ответа.
    """

    if not avito_account.external_account_id:
        raise AvitoApiError(
            "У AvitoAccount не заполнен external_account_id."
        )

    stat_date = normalize_date(stat_date)
    page_size = get_v2_page_size()
    token = get_account_token(avito_account)

    listings = get_listings_for_stats(avito_account)

    if not listings:
        return AvitoProfileDailyStatsImportResult(
            total_received=0,
            matched_listings=0,
            created_stats=0,
            updated_stats=0,
            deleted_zero_stats=0,
            confirmed_listings=0,
        )

    client = AvitoApiClient(session=session)
    groupings = fetch_profile_daily_groupings(
        client=client,
        token=token,
        user_id=avito_account.external_account_id,
        stat_date=stat_date,
        page_size=page_size,
    )

    listing_by_avito_id = {
        str(listing.avito_id): listing
        for listing in listings
    }
    matched_listing_ids = get_matched_profile_listing_ids(
        groupings=groupings,
        listing_by_avito_id=listing_by_avito_id,
    )

    if groupings and not matched_listing_ids:
        raise AvitoApiError(
            "Ни одна группировка Avito stats/v2 не сопоставлена "
            "с локальными объявлениями аккаунта. "
            f"Получено группировок: {len(groupings)}."
        )

    activity_by_listing_id = (
        build_profile_activity_by_listing_id(
            groupings=groupings,
            listing_by_avito_id=listing_by_avito_id,
        )
    )

    write_result = replace_profile_daily_activity(
        workspace=avito_account.workspace,
        listings=listings,
        stat_date=stat_date,
        activity_by_listing_id=activity_by_listing_id,
    )

    return AvitoProfileDailyStatsImportResult(
        total_received=len(groupings),
        matched_listings=len(matched_listing_ids),
        created_stats=write_result["created_stats"],
        updated_stats=write_result["updated_stats"],
        deleted_zero_stats=write_result["deleted_zero_stats"],
        confirmed_listings=len(listings),
    )


def fetch_profile_daily_groupings(
        *,
        client,
        token,
        user_id,
        stat_date,
        page_size,
):
    groupings = []
    offset = 0

    while True:
        payload = client.get_item_analytics(
            token=token,
            user_id=user_id,
            date_from=stat_date,
            date_to=stat_date,
            metrics=["views", "contacts"],
            grouping="item",
            limit=page_size,
            offset=offset,
        )

        result = payload.get("result") or {}
        page_groupings = list(result.get("groupings") or [])
        total_count = int(
            result.get("dataTotalCount")
            or len(page_groupings)
        )

        groupings.extend(page_groupings)
        offset += len(page_groupings)

        if offset >= total_count:
            break

        if not page_groupings:
            raise AvitoApiError(
                "Avito stats/v2 вернул неполную пагинацию: "
                f"получено {offset} из {total_count} строк."
            )

    return groupings


def get_matched_profile_listing_ids(
        *,
        groupings,
        listing_by_avito_id,
):
    matched_listing_ids = set()

    for grouping in groupings:
        if grouping.get("type") != "items":
            continue

        listing = listing_by_avito_id.get(
            str(grouping.get("id"))
        )

        if listing is not None:
            matched_listing_ids.add(listing.id)

    return matched_listing_ids


def build_profile_activity_by_listing_id(
        *,
        groupings,
        listing_by_avito_id,
):
    activity_by_listing_id = {}

    for grouping in groupings:
        if grouping.get("type") != "items":
            continue

        listing = listing_by_avito_id.get(
            str(grouping.get("id"))
        )

        if listing is None:
            continue

        metrics = {
            str(metric.get("slug")): int(
                metric.get("value") or 0
            )
            for metric in grouping.get("metrics") or []
        }

        views = metrics.get("views", 0)
        contacts = metrics.get("contacts", 0)

        # Нулевую строку физически не создаём.
        if views == 0 and contacts == 0:
            continue

        activity_by_listing_id[listing.id] = {
            "views": views,
            "contacts": contacts,
        }

    return activity_by_listing_id


def replace_profile_daily_activity(
        *,
        workspace,
        listings,
        stat_date,
        activity_by_listing_id,
):
    now = timezone.now()
    listing_ids = [listing.id for listing in listings]

    created_stats = []
    updated_stats = []
    delete_stat_ids = []

    with transaction.atomic():
        existing_by_listing_id = {
            stat.listing_id: stat
            for stat in (
                AvitoListingDailyStats.objects
                .select_for_update()
                .filter(
                    workspace=workspace,
                    listing_id__in=listing_ids,
                    date=stat_date,
                )
            )
        }

        for listing in listings:
            values = activity_by_listing_id.get(listing.id)
            existing = existing_by_listing_id.get(listing.id)

            if values is not None:
                raw_metrics = dict(
                    existing.raw_metrics or {}
                    if existing
                    else {}
                )
                raw_metrics["stats_v2"] = {
                    "views": values["views"],
                    "contacts": values["contacts"],
                }

                if existing is None:
                    created_stats.append(
                        AvitoListingDailyStats(
                            workspace=workspace,
                            listing=listing,
                            date=stat_date,
                            views=values["views"],
                            contacts=values["contacts"],
                            raw_metrics=raw_metrics,
                        )
                    )
                else:
                    existing.views = values["views"]
                    existing.contacts = values["contacts"]
                    existing.raw_metrics = raw_metrics
                    existing.updated_at = now
                    updated_stats.append(existing)

                continue

            if existing is None:
                continue

            existing.views = 0
            existing.contacts = 0

            raw_metrics = dict(existing.raw_metrics or {})
            raw_metrics["stats_v2"] = {
                "views": 0,
                "contacts": 0,
            }
            existing.raw_metrics = raw_metrics
            existing.updated_at = now

            if is_zero_only_daily_stat(existing):
                delete_stat_ids.append(existing.id)
            else:
                updated_stats.append(existing)

        if delete_stat_ids:
            AvitoListingDailyStats.objects.filter(
                id__in=delete_stat_ids,
            ).delete()

        if updated_stats:
            AvitoListingDailyStats.objects.bulk_update(
                updated_stats,
                fields=[
                    "views",
                    "contacts",
                    "raw_metrics",
                    "updated_at",
                ],
                batch_size=AVITO_STATS_DB_BATCH_SIZE,
            )

        if created_stats:
            AvitoListingDailyStats.objects.bulk_create(
                created_stats,
                batch_size=AVITO_STATS_DB_BATCH_SIZE,
            )

        update_listing_coverages_for_profile_day(
            workspace=workspace,
            listings=listings,
            stat_date=stat_date,
            now=now,
        )

    return {
        "created_stats": len(created_stats),
        "updated_stats": len(updated_stats),
        "deleted_zero_stats": len(delete_stat_ids),
    }


def update_listing_coverages_for_profile_day(
        *,
        workspace,
        listings,
        stat_date,
        now,
):
    """
    Обновляет coverage одним set-based SQL UPDATE.

    Все условия вычисляются PostgreSQL относительно исходного состояния
    строки. Это исключает построение тысяч Django-объектов и большого
    CASE по каждому primary key.
    """

    listing_ids = [
        listing.id
        for listing in listings
    ]

    coverage_rows = [
        AvitoListingStatsCoverage(
            workspace=workspace,
            listing=listing,
        )
        for listing in listings
    ]

    empty_condition = (
        Q(coverage_from__isnull=True)
        | Q(finalized_through__isnull=True)
    )
    prepend_condition = Q(
        coverage_from=stat_date + timedelta(days=1),
    )
    inside_condition = Q(
        coverage_from__lte=stat_date,
        finalized_through__gte=stat_date,
    )
    append_condition = Q(
        finalized_through=stat_date - timedelta(days=1),
    )

    success_condition = (
        empty_condition
        | prepend_condition
        | inside_condition
        | append_condition
    )

    gap_error = Concat(
        Value(
            "День статистики получен, но не может быть добавлен "
            "к покрытию из-за пропущенного диапазона: "
            f"date={stat_date}, coverage="
        ),
        Cast(
            F("coverage_from"),
            output_field=CharField(),
        ),
        Value(".."),
        Cast(
            F("finalized_through"),
            output_field=CharField(),
        ),
        Value("."),
        output_field=TextField(),
    )

    with transaction.atomic():
        AvitoListingStatsCoverage.objects.bulk_create(
            coverage_rows,
            batch_size=AVITO_STATS_DB_BATCH_SIZE,
            ignore_conflicts=True,
        )

        (
            AvitoListingStatsCoverage.objects
            .filter(
                workspace=workspace,
                listing_id__in=listing_ids,
            )
            .update(
                coverage_from=Case(
                    When(
                        empty_condition,
                        then=Value(stat_date),
                    ),
                    When(
                        prepend_condition,
                        then=Value(stat_date),
                    ),
                    default=F("coverage_from"),
                    output_field=DateField(),
                ),
                finalized_through=Case(
                    When(
                        empty_condition,
                        then=Value(stat_date),
                    ),
                    When(
                        append_condition,
                        then=Value(stat_date),
                    ),
                    default=F("finalized_through"),
                    output_field=DateField(),
                ),
                last_attempted_at=now,
                last_successful_at=Case(
                    When(
                        success_condition,
                        then=Value(now),
                    ),
                    default=F("last_successful_at"),
                    output_field=DateTimeField(),
                ),
                error=Case(
                    When(
                        success_condition,
                        then=Value(""),
                    ),
                    default=gap_error,
                    output_field=TextField(),
                ),
                updated_at=now,
            )
        )


def is_zero_only_daily_stat(stat):
    return (
            stat.views == 0
            and stat.contacts == 0
            and stat.favorites == 0
            and stat.calls == 0
            and stat.messages == 0
            and stat.total_spend is None
    )


def resolve_stats_sync_range(
        *,
        sync_state,
        today,
        date_from=None,
        date_to=None,
):
    """
    Первый запуск: последние 365 дней включительно.
    Повторный запуск: сегодня и предыдущий день.
    """

    today = normalize_date(today)

    if date_from is not None or date_to is not None:
        if date_from is None or date_to is None:
            raise ValueError(
                "date_from и date_to должны передаваться вместе."
            )

        date_from = normalize_date(date_from)
        date_to = normalize_date(date_to)

        if date_from > date_to:
            raise ValueError(
                "date_from не может быть больше date_to."
            )

        return date_from, date_to

    if sync_state.last_successful_at:
        incremental_days = max(
            int(settings.AVITO_STATS_INCREMENTAL_DAYS),
            1,
        )
        return (
            today - timedelta(days=incremental_days - 1),
            today,
        )

    history_days = max(
        int(settings.AVITO_STATS_INITIAL_HISTORY_DAYS),
        1,
    )

    return (
        today - timedelta(days=history_days - 1),
        today,
    )


def build_avito_stats_backfill_plan(
        *,
        avito_account,
        target_date,
):
    """
    Строит сгруппированный план исторического backfill.

    target_date — день, который отдельно загружает stats/v2.
    Поэтому backfill заканчивается предыдущим днём.
    """

    target_date = normalize_date(target_date)
    history_days = get_stats_history_days()

    backfill_to = target_date - timedelta(days=1)
    maximum_history_from = (
            backfill_to - timedelta(days=history_days - 1)
    )

    listings = list(
        AvitoListing.objects
        .filter(
            workspace=avito_account.workspace,
            avito_account=avito_account,
        )
        .exclude(avito_id="")
        .only(
            "id",
            "published_at",
        )
        .order_by("id")
    )

    if not listings:
        return []

    listing_ids = [listing.id for listing in listings]

    coverages_by_listing_id = {
        coverage.listing_id: coverage
        for coverage in (
            AvitoListingStatsCoverage.objects
            .filter(
                workspace=avito_account.workspace,
                listing_id__in=listing_ids,
            )
            .only(
                "listing_id",
                "coverage_from",
                "finalized_through",
            )
        )
    }

    grouped_listing_ids = {}

    for listing in listings:
        published_date = get_listing_published_date(listing)

        desired_from = maximum_history_from

        if published_date is not None:
            desired_from = max(
                desired_from,
                published_date,
            )

        # Объявление ещё не существовало в диапазоне backfill.
        if desired_from > backfill_to:
            continue

        coverage = coverages_by_listing_id.get(listing.id)

        missing_ranges = get_listing_missing_ranges(
            desired_from=desired_from,
            desired_to=backfill_to,
            coverage=coverage,
        )

        for range_from, range_to in missing_ranges:
            grouped_listing_ids.setdefault(
                (range_from, range_to),
                [],
            ).append(listing.id)

    plan = [
        AvitoStatsBackfillRequest(
            date_from=range_from,
            date_to=range_to,
            listing_ids=tuple(sorted(ids)),
        )
        for (range_from, range_to), ids
        in grouped_listing_ids.items()
    ]

    plan.sort(
        key=lambda request: (
            request.date_from,
            request.date_to,
            request.listing_ids,
        )
    )

    return plan


def get_listing_missing_ranges(
        *,
        desired_from,
        desired_to,
        coverage,
):
    if coverage is None:
        return [(desired_from, desired_to)]

    if (
            coverage.coverage_from is None
            or coverage.finalized_through is None
    ):
        return [(desired_from, desired_to)]

    missing_ranges = []

    # Отсутствующая история перед текущим покрытием.
    if desired_from < coverage.coverage_from:
        backward_to = min(
            desired_to,
            coverage.coverage_from - timedelta(days=1),
        )

        if desired_from <= backward_to:
            missing_ranges.append(
                (desired_from, backward_to)
            )

    # Отсутствующие дни после текущего покрытия.
    if desired_to > coverage.finalized_through:
        forward_from = max(
            desired_from,
            coverage.finalized_through + timedelta(days=1),
        )

        if forward_from <= desired_to:
            missing_ranges.append(
                (forward_from, desired_to)
            )

    return missing_ranges


def get_listing_published_date(listing):
    published_at = listing.published_at

    if published_at is None:
        return None

    if timezone.is_aware(published_at):
        return timezone.localtime(published_at).date()

    return published_at.date()


def get_account_token(avito_account):
    try:
        return avito_account.oauth_tokens
    except AvitoOAuthToken.DoesNotExist as exc:
        raise AvitoApiError(
            "У AvitoAccount нет подключенного OAuth-токена."
        ) from exc


def get_listings_for_stats(avito_account, listing_ids=None):
    queryset = (
        AvitoListing.objects
        .filter(
            workspace=avito_account.workspace,
            avito_account=avito_account,
        )
        .exclude(avito_id="")
        .only(
            "id",
            "workspace_id",
            "avito_account_id",
            "avito_id",
            "published_at",
        )
        .order_by("id")
    )

    if listing_ids is not None:
        queryset = queryset.filter(id__in=listing_ids)

    return list(queryset)


def bulk_upsert_daily_stats(
        *,
        items,
        listing_by_avito_id,
):
    """
    Пакетно сохраняет один ответ Avito stats/v1.

    Строки дедуплицируются по (listing_id, date). Если Avito вернул
    один ключ несколько раз, используется последнее значение.
    """

    incoming_by_key = {}

    for item in items:
        listing = listing_by_avito_id.get(
            str(item.get("itemId"))
        )

        if listing is None:
            continue

        for stat in item.get("stats") or []:
            stat_date = date.fromisoformat(stat["date"])
            key = (listing.id, stat_date)

            incoming_by_key[key] = {
                "workspace_id": listing.workspace_id,
                "listing_id": listing.id,
                "date": stat_date,
                "views": int(stat.get("uniqViews") or 0),
                "contacts": int(stat.get("uniqContacts") or 0),
                "favorites": int(stat.get("uniqFavorites") or 0),
                "calls": int(stat.get("calls") or 0),
                "messages": int(stat.get("messages") or 0),
                "raw_metrics": dict(stat),
            }

    if not incoming_by_key:
        return AvitoDailyStatsWriteResult(
            total_days=0,
            created_stats=0,
            updated_stats=0,
            unchanged_stats=0,
        )

    listing_ids = {
        listing_id
        for listing_id, _ in incoming_by_key
    }
    stat_dates = [
        stat_date
        for _, stat_date in incoming_by_key
    ]

    created_rows = []
    changed_rows = []
    unchanged_stats = 0

    with transaction.atomic():
        existing_by_key = {
            (daily_stat.listing_id, daily_stat.date): daily_stat
            for daily_stat in (
                AvitoListingDailyStats.objects
                .select_for_update()
                .filter(
                    listing_id__in=listing_ids,
                    date__range=(
                        min(stat_dates),
                        max(stat_dates),
                    ),
                )
            )
        }

        now = timezone.now()

        for key, values in incoming_by_key.items():
            existing = existing_by_key.get(key)

            if existing is None:
                created_rows.append(
                    AvitoListingDailyStats(
                        workspace_id=values["workspace_id"],
                        listing_id=values["listing_id"],
                        date=values["date"],
                        views=values["views"],
                        contacts=values["contacts"],
                        favorites=values["favorites"],
                        calls=values["calls"],
                        messages=values["messages"],
                        raw_metrics=dict(values["raw_metrics"]),
                    )
                )
                continue

            current_raw_metrics = dict(
                existing.raw_metrics or {}
            )
            merged_raw_metrics = dict(current_raw_metrics)
            merged_raw_metrics.update(values["raw_metrics"])

            is_unchanged = (
                    existing.workspace_id == values["workspace_id"]
                    and existing.views == values["views"]
                    and existing.contacts == values["contacts"]
                    and existing.favorites == values["favorites"]
                    and existing.calls == values["calls"]
                    and existing.messages == values["messages"]
                    and current_raw_metrics == merged_raw_metrics
            )

            if is_unchanged:
                unchanged_stats += 1
                continue

            existing.workspace_id = values["workspace_id"]
            existing.views = values["views"]
            existing.contacts = values["contacts"]
            existing.favorites = values["favorites"]
            existing.calls = values["calls"]
            existing.messages = values["messages"]
            existing.raw_metrics = merged_raw_metrics
            existing.updated_at = now
            changed_rows.append(existing)

        if created_rows:
            AvitoListingDailyStats.objects.bulk_create(
                created_rows,
                batch_size=AVITO_STATS_DB_BATCH_SIZE,
            )

        if changed_rows:
            AvitoListingDailyStats.objects.bulk_update(
                changed_rows,
                fields=[
                    "workspace",
                    "views",
                    "contacts",
                    "favorites",
                    "calls",
                    "messages",
                    "raw_metrics",
                    "updated_at",
                ],
                batch_size=AVITO_STATS_DB_BATCH_SIZE,
            )

    return AvitoDailyStatsWriteResult(
        total_days=len(incoming_by_key),
        created_stats=len(created_rows),
        updated_stats=len(changed_rows),
        unchanged_stats=unchanged_stats,
    )


def validate_listing_coverage_range(
        *,
        listings,
        date_from,
        date_to,
):
    """
    Проверяет, что новый диапазон пересекается с существующим
    покрытием или непосредственно продолжает его.

    Один coverage хранит непрерывный диапазон, поэтому через
    пропущенные даты переступать нельзя.
    """

    listing_ids = [listing.id for listing in listings]

    coverages = (
        AvitoListingStatsCoverage.objects
        .filter(listing_id__in=listing_ids)
        .only(
            "listing_id",
            "coverage_from",
            "finalized_through",
        )
    )

    for coverage in coverages:
        if (
                coverage.coverage_from is None
                or coverage.finalized_through is None
        ):
            continue

        earliest_allowed = (
                coverage.coverage_from - timedelta(days=1)
        )
        latest_allowed = (
                coverage.finalized_through + timedelta(days=1)
        )

        has_gap_before = date_to < earliest_allowed
        has_gap_after = date_from > latest_allowed

        if has_gap_before or has_gap_after:
            raise ValueError(
                "Диапазон статистики должен продолжать "
                "существующее покрытие без пропущенных дат. "
                f"listing_id={coverage.listing_id}, "
                f"coverage={coverage.coverage_from}"
                f"..{coverage.finalized_through}, "
                f"requested={date_from}..{date_to}."
            )


def mark_listing_coverage_attempt(listings):
    now = timezone.now()

    coverage_rows = [
        AvitoListingStatsCoverage(
            workspace_id=listing.workspace_id,
            listing_id=listing.id,
        )
        for listing in listings
    ]
    listing_ids = [listing.id for listing in listings]

    with transaction.atomic():
        AvitoListingStatsCoverage.objects.bulk_create(
            coverage_rows,
            batch_size=AVITO_STATS_DB_BATCH_SIZE,
            ignore_conflicts=True,
        )
        AvitoListingStatsCoverage.objects.filter(
            listing_id__in=listing_ids,
        ).update(
            last_attempted_at=now,
            error="",
            updated_at=now,
        )


def mark_listing_coverage_success(
        *,
        listings,
        date_from,
        date_to,
):
    now = timezone.now()
    listing_ids = [listing.id for listing in listings]

    with transaction.atomic():
        coverages = list(
            AvitoListingStatsCoverage.objects
            .select_for_update()
            .filter(listing_id__in=listing_ids)
        )

        for coverage in coverages:
            coverage.coverage_from = min_not_none(
                coverage.coverage_from,
                date_from,
            )
            coverage.finalized_through = max_not_none(
                coverage.finalized_through,
                date_to,
            )
            coverage.last_successful_at = now
            coverage.error = ""
            coverage.updated_at = now

        AvitoListingStatsCoverage.objects.bulk_update(
            coverages,
            fields=[
                "coverage_from",
                "finalized_through",
                "last_successful_at",
                "error",
                "updated_at",
            ],
            batch_size=AVITO_STATS_DB_BATCH_SIZE,
        )


def mark_listing_coverage_error(*, listings, error):
    now = timezone.now()
    listing_ids = [listing.id for listing in listings]

    AvitoListingStatsCoverage.objects.filter(
        listing_id__in=listing_ids,
    ).update(
        error=error,
        updated_at=now,
    )


def normalize_date(value):
    if isinstance(value, date):
        return value

    return date.fromisoformat(str(value))


def chunked(items, size):
    for index in range(0, len(items), size):
        yield items[index:index + size]


def split_date_range(
        date_from,
        date_to,
        *,
        max_period_days,
):
    """
    Делит период на последовательные непересекающиеся окна.

    Avito stats/v1 допускает не более 270 календарных дней
    в одном запросе, считая обе границы периода включительно.
    """

    current_from = normalize_date(date_from)
    final_to = normalize_date(date_to)

    if current_from > final_to:
        raise ValueError("date_from не может быть больше date_to.")

    if max_period_days < 1:
        raise ValueError("max_period_days должен быть больше нуля.")

    while current_from <= final_to:
        current_to = min(
            current_from + timedelta(days=max_period_days - 1),
            final_to,
        )

        yield current_from, current_to
        current_from = current_to + timedelta(days=1)


def get_stats_history_days():
    history_days = int(settings.AVITO_STATS_HISTORY_DAYS)

    if not 1 <= history_days <= 270:
        raise ValueError(
            "AVITO_STATS_HISTORY_DAYS "
            "должен быть от 1 до 270."
        )

    return history_days


def get_v1_listings_batch_size():
    batch_size = int(settings.AVITO_STATS_LISTINGS_BATCH_SIZE)

    if not 1 <= batch_size <= 200:
        raise ValueError(
            "AVITO_STATS_LISTINGS_BATCH_SIZE "
            "должен быть от 1 до 200."
        )

    return batch_size


def get_v2_page_size():
    page_size = int(settings.AVITO_STATS_V2_PAGE_SIZE)

    if not 1 <= page_size <= 1000:
        raise ValueError(
            "AVITO_STATS_V2_PAGE_SIZE "
            "должен быть от 1 до 1000."
        )

    return page_size


def min_not_none(current, incoming):
    if current is None:
        return incoming

    return min(current, incoming)


def max_not_none(current, incoming):
    if current is None:
        return incoming

    return max(current, incoming)
