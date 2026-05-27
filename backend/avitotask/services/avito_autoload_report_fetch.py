from dataclasses import dataclass
from typing import Any

from avitotask.models import AvitoAccount
from avitotask.services.avito_api import AvitoApiClient, AvitoApiError
from avitotask.services.avito_autoload import get_account_token
from avitotask.services.avito_autoload_report_sync import (
    AvitoAutoloadReportSyncResult,
    sync_avito_autoload_report,
)


@dataclass(frozen=True)
class AvitoLastCompletedAutoloadReportSyncResult:
    report_id: str
    report_status: str
    total_items_received: int
    sync_result: AvitoAutoloadReportSyncResult


def sync_last_completed_autoload_report_for_account(
        avito_account: AvitoAccount,
        session=None,
) -> AvitoLastCompletedAutoloadReportSyncResult:
    token = get_account_token(avito_account)
    client = AvitoApiClient(session=session)

    report_payload = client.get_last_completed_autoload_report(token)
    report = extract_report(report_payload)
    report_id = extract_report_id(report)

    if not report_id:
        raise AvitoApiError(
            "Avito API не вернул id последнего завершенного отчета автозагрузки.",
            payload=report_payload,
        )

    report_rows = fetch_report_items(
        client=client,
        token=token,
        report_id=report_id,
    )

    sync_result = sync_avito_autoload_report(
        workspace=avito_account.workspace,
        avito_account=avito_account,
        report_rows=report_rows,
    )

    return AvitoLastCompletedAutoloadReportSyncResult(
        report_id=report_id,
        report_status=str(report.get("status") or report.get("state") or ""),
        total_items_received=len(report_rows),
        sync_result=sync_result,
    )


def fetch_report_items(client, token, report_id: str) -> list[dict[str, Any]]:
    rows = []
    page = 1
    per_page = 100

    while True:
        payload = client.get_autoload_report_items(
            token=token,
            report_id=report_id,
            page=page,
            per_page=per_page,
        )

        items = extract_items(payload)
        rows.extend(items)

        next_page = resolve_next_report_items_page(
            payload=payload,
            current_page=page,
        )

        if next_page is None:
            break

        page = next_page

    return rows


def extract_report(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}

    for key in ("report", "result", "data"):
        value = payload.get(key)

        if isinstance(value, dict):
            return value

    return payload


def extract_report_id(report: dict[str, Any]) -> str:
    for key in ("id", "report_id", "reportId"):
        value = report.get(key)

        if value not in (None, ""):
            return str(value)

    return ""


def extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        return []

    containers = [payload]

    for key in ("result", "data"):
        value = payload.get(key)

        if isinstance(value, dict):
            containers.append(value)

    for container in containers:
        for key in ("items", "resources", "rows", "ads"):
            value = container.get(key)

            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

    return []


def resolve_next_report_items_page(payload: dict[str, Any], current_page: int) -> int | None:
    if not isinstance(payload, dict):
        return None

    meta = (
            payload.get("meta")
            or payload.get("pagination")
            or (payload.get("result") or {}).get("meta")
            or (payload.get("result") or {}).get("pagination")
            or {}
    )

    page = meta.get("page") or meta.get("current_page") or current_page
    pages = meta.get("pages") or meta.get("total_pages") or meta.get("page_count")

    if pages is not None:
        try:
            page_number = int(page)
            pages_number = int(pages)
        except (TypeError, ValueError):
            return None

        if page_number < pages_number:
            return page_number + 1

        return None

    if payload.get("next"):
        return current_page + 1

    return None
