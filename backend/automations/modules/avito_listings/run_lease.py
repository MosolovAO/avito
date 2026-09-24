from datetime import datetime, timedelta
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from automations.models import (
    AutomationRun,
    AvitoAutomationAccountState,
    AvitoListingRunResult,
)

LEASE_DURATION = timedelta(minutes=10)


class RunLeaseTargetError(RuntimeError):
    """Run не содержит корректную цель для account lease."""


def acquire_run_lease(
        *,
        run: AutomationRun,
        run_token: UUID,
        acquired_at: datetime,
) -> bool:
    """
    Пытается захватить lease Avito-аккаунта для одного run.

    Активный lease другого token не перезаписывается. Истёкший lease
    разрешено атомарно забрать новому worker.
    """

    workspace_id, avito_account_id = _get_lease_target(run=run)

    with transaction.atomic():
        state, _ = (
            AvitoAutomationAccountState.objects
            .get_or_create(
                workspace_id=workspace_id,
                avito_account_id=avito_account_id,
            )
        )

        updated = (
            AvitoAutomationAccountState.objects
            .filter(id=state.id)
            .filter(
                Q(status=AvitoAutomationAccountState.Status.IDLE)
                | Q(
                    status=(
                        AvitoAutomationAccountState.Status.RUNNING
                    ),
                    lease_expires_at__lte=acquired_at,
                )
                | Q(
                    status=(
                        AvitoAutomationAccountState.Status.RUNNING
                    ),
                    run_token=run_token,
                )
            )
            .update(
                status=AvitoAutomationAccountState.Status.RUNNING,
                run_token=run_token,
                heartbeat_at=acquired_at,
                lease_expires_at=acquired_at + LEASE_DURATION,
                updated_at=acquired_at,
            )
        )

    return updated == 1


def heartbeat_run_lease(
        *,
        run: AutomationRun,
        run_token: UUID,
        heartbeat_at: datetime,
) -> bool:
    """
    Продлевает только действующий lease, принадлежащий переданному token.

    Истёкший lease продлить нельзя: worker должен прекратить выполнение,
    поскольку аккаунт уже может быть захвачен другим run.
    """

    workspace_id, avito_account_id = _get_lease_target(run=run)

    updated = (
        AvitoAutomationAccountState.objects
        .filter(
            workspace_id=workspace_id,
            avito_account_id=avito_account_id,
            status=AvitoAutomationAccountState.Status.RUNNING,
            run_token=run_token,
            lease_expires_at__gt=heartbeat_at,
        )
        .update(
            heartbeat_at=heartbeat_at,
            lease_expires_at=heartbeat_at + LEASE_DURATION,
            updated_at=heartbeat_at,
        )
    )

    return updated == 1


def release_run_lease(
        *,
        run: AutomationRun,
        run_token: UUID,
) -> bool:
    """Освобождает lease, только если worker всё ещё владеет token."""

    workspace_id, avito_account_id = _get_lease_target(run=run)

    updated = (
        AvitoAutomationAccountState.objects
        .filter(
            workspace_id=workspace_id,
            avito_account_id=avito_account_id,
            status=AvitoAutomationAccountState.Status.RUNNING,
            run_token=run_token,
        )
        .update(
            status=AvitoAutomationAccountState.Status.IDLE,
            run_token=None,
            heartbeat_at=None,
            lease_expires_at=None,
            updated_at=timezone.now(),
        )
    )

    return updated == 1


def _get_lease_target(
        *,
        run: AutomationRun,
) -> tuple[int, int]:
    """
    Получает account lease только из типизированного результата run.

    Дополнительная проверка workspace не позволяет ошибочно захватить
    аккаунт из другой рабочей области.
    """

    target = (
        AvitoListingRunResult.objects
        .filter(
            run_id=run.id,
            workspace_id=run.workspace_id,
            avito_account__workspace_id=run.workspace_id,
        )
        .values(
            "workspace_id",
            "avito_account_id",
        )
        .first()
    )
    if target is None:
        raise RunLeaseTargetError(
            "Run не содержит корректную цель Avito account lease.",
        )

    return (
        target["workspace_id"],
        target["avito_account_id"],
    )
