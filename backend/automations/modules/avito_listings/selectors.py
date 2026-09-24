from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

from django.db.models import Count, Exists, Max, OuterRef, Q, QuerySet
from django.utils import timezone

from accounts.models import Workspace
from analytics.models import (
    AvitoListingStatsCoverage,
    AvitoStatsSyncState,
)
from automations.models import AvitoListingDecision
from avitotask.models import AvitoAccount, AvitoListing

from . import catalog
from .evaluator import CompiledConditionPlan, MetricWindow


@dataclass(frozen=True, slots=True)
class AccountStatsReadiness:
    """Готовность статистики аккаунта для всех окон запуска."""

    is_ready: bool
    reason: str | None
    required_from: date
    required_to: date
    sync_status: str | None


@dataclass(frozen=True, slots=True)
class ListingCoveragePartition:
    """Разделение объявлений по наличию полного coverage."""

    covered_listing_ids: tuple[int, ...]
    insufficient_listing_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ListingSelectionSnapshot:
    """Границы и исходный размер выборки одного evaluator."""

    target_max_id_snapshot: int
    checked: int


@dataclass(frozen=True, slots=True)
class _CoverageRequirement:
    """Поля coverage и диапазон одного статистического окна."""

    coverage_from_field: str
    coverage_through_field: str
    date_from: date
    date_to: date


def get_account_stats_readiness(
        *,
        workspace: Workspace,
        avito_account: AvitoAccount,
        plan: CompiledConditionPlan,
) -> AccountStatsReadiness:
    """
    Проверяет готовность подтверждённого диапазона всего аккаунта.

    Текущий статус синхронизации не отменяет ранее подтверждённый
    coverage. Статус возвращается только для диагностики.
    """

    required_from, required_to = _required_date_range(plan)

    sync_state = (
        AvitoStatsSyncState.objects
        .filter(
            workspace=workspace,
            avito_account=avito_account,
        )
        .values(
            "status",
            "coverage_from",
            "coverage_to",
        )
        .first()
    )

    if sync_state is None:
        return AccountStatsReadiness(
            is_ready=False,
            reason="missing_sync_state",
            required_from=required_from,
            required_to=required_to,
            sync_status=None,
        )

    coverage_from = sync_state["coverage_from"]
    coverage_to = sync_state["coverage_to"]

    has_complete_coverage = (
            coverage_from is not None
            and coverage_to is not None
            and coverage_from <= required_from
            and coverage_to >= required_to
    )

    return AccountStatsReadiness(
        is_ready=has_complete_coverage,
        reason=(
            None
            if has_complete_coverage
            else "insufficient_account_coverage"
        ),
        required_from=required_from,
        required_to=required_to,
        sync_status=sync_state["status"],
    )


def get_listing_selection_snapshot(
        *,
        workspace: Workspace,
        avito_account: AvitoAccount,
) -> ListingSelectionSnapshot:
    """
    Одним запросом фиксирует верхнюю границу и число managed-объявлений.

    Верхняя граница учитывает все объявления аккаунта, включая observed.
    Поэтому объявление, существовавшее на старте и позднее переведённое
    под управление, не считается новым объектом.
    """

    snapshot = (
        AvitoListing.objects
        .filter(
            workspace=workspace,
            avito_account=avito_account,
        )
        .aggregate(
            target_max_id_snapshot=Max("id"),
            checked=Count(
                "id",
                filter=Q(
                    management_status=(
                        AvitoListing.ManagementStatus.MANAGED
                    ),
                ),
            ),
        )
    )

    return ListingSelectionSnapshot(
        target_max_id_snapshot=(
                snapshot["target_max_id_snapshot"] or 0
        ),
        checked=snapshot["checked"],
    )


def select_eligible_listing_rows(
        *,
        workspace: Workspace,
        avito_account: AvitoAccount,
        plan: CompiledConditionPlan,
        target_max_id_snapshot: int,
) -> QuerySet:
    """
    Возвращает лёгкий queryset потенциально eligible объявлений.

    День установки active_since считается неполным. Поэтому active_since
    должен находиться строго раньше начала самого длинного окна.
    """

    required_from, _ = _required_date_range(plan)
    active_before = timezone.make_aware(
        datetime.combine(required_from, time.min),
        timezone.get_current_timezone(),
    )

    unfinished_effects = (
        AvitoListingDecision.objects
        .filter(
            workspace=workspace,
            avito_account=avito_account,
            listing_id=OuterRef("pk"),
            status__in=(
                AvitoListingDecision.Status.APPLYING,
                AvitoListingDecision.Status.EFFECT_PENDING,
            ),
        )
    )

    return (
        AvitoListing.objects
        .filter(
            workspace=workspace,
            avito_account=avito_account,
            management_status=(
                AvitoListing.ManagementStatus.MANAGED
            ),
            desired_status=AvitoListing.DesiredStatus.PUBLISH,
            active_since__isnull=False,
            active_since__lt=active_before,
            id__lte=target_max_id_snapshot,
        )
        .alias(
            has_unfinished_automation_effect=Exists(
                unfinished_effects,
            ),
        )
        .filter(has_unfinished_automation_effect=False)
        .values(
            "id",
            "active_since",
        )
        .order_by(
            "active_since",
            "id",
        )
    )


def partition_listing_ids_by_coverage(
        *,
        workspace: Workspace,
        avito_account: AvitoAccount,
        listing_ids: Iterable[int],
        plan: CompiledConditionPlan,
) -> ListingCoveragePartition:
    """
    Одним запросом проверяет coverage переданного chunk объявлений.

    Порядок идентификаторов сохраняется. Повторяющиеся идентификаторы
    проверяются только один раз.
    """

    ordered_listing_ids = tuple(dict.fromkeys(listing_ids))

    if not ordered_listing_ids:
        return ListingCoveragePartition(
            covered_listing_ids=(),
            insufficient_listing_ids=(),
        )

    requirements = _build_coverage_requirements(plan)
    coverage_fields = tuple(sorted({
        field_name
        for requirement in requirements
        for field_name in (
            requirement.coverage_from_field,
            requirement.coverage_through_field,
        )
    }))

    coverage_rows = (
        AvitoListingStatsCoverage.objects
        .filter(
            workspace=workspace,
            listing_id__in=ordered_listing_ids,
            listing__workspace=workspace,
            listing__avito_account=avito_account,
        )
        .values(
            "listing_id",
            *coverage_fields,
        )
    )
    coverage_by_listing_id = {
        row["listing_id"]: row
        for row in coverage_rows
    }

    covered_listing_ids: list[int] = []
    insufficient_listing_ids: list[int] = []

    for listing_id in ordered_listing_ids:
        coverage = coverage_by_listing_id.get(listing_id)

        if (
                coverage is not None
                and _has_complete_listing_coverage(
            coverage=coverage,
            requirements=requirements,
        )
        ):
            covered_listing_ids.append(listing_id)
        else:
            insufficient_listing_ids.append(listing_id)

    return ListingCoveragePartition(
        covered_listing_ids=tuple(covered_listing_ids),
        insufficient_listing_ids=tuple(
            insufficient_listing_ids,
        ),
    )


def _required_date_range(
        plan: CompiledConditionPlan,
) -> tuple[date, date]:
    return (
        min(window.date_from for window in plan.windows),
        max(window.date_to for window in plan.windows),
    )


def _build_coverage_requirements(
        plan: CompiledConditionPlan,
) -> tuple[_CoverageRequirement, ...]:
    return tuple(
        _build_window_coverage_requirement(window)
        for window in plan.windows
    )


def _build_window_coverage_requirement(
        window: MetricWindow,
) -> _CoverageRequirement:
    metric_definition = catalog.METRICS_BY_CODE[window.metric]

    return _CoverageRequirement(
        coverage_from_field=(
            metric_definition.coverage_from_field
        ),
        coverage_through_field=(
            metric_definition.coverage_through_field
        ),
        date_from=window.date_from,
        date_to=window.date_to,
    )


def _has_complete_listing_coverage(
        *,
        coverage: dict[str, Any],
        requirements: tuple[_CoverageRequirement, ...],
) -> bool:
    for requirement in requirements:
        coverage_from = coverage[
            requirement.coverage_from_field
        ]
        coverage_through = coverage[
            requirement.coverage_through_field
        ]

        if (
                coverage_from is None
                or coverage_through is None
                or coverage_from > requirement.date_from
                or coverage_through < requirement.date_to
        ):
            return False

    return True
