from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.utils.formats import date_format
from django.utils.translation import override

from calls.models import Call
from calls.services import normalize_phone

MOSCOW = ZoneInfo("Europe/Moscow")


def format_report_phone(value):
    phone = value.strip()
    digits = normalize_phone(phone)

    if len(digits) == 11 and digits.startswith("7"):
        return f"+7 ({digits[1:4]}) " f"{digits[4:7]}-{digits[7:9]}-{digits[9:11]}"

    return phone or "Номер неизвестен"


def build_daily_call_report(account, day):
    start = datetime.combine(day, time.min, tzinfo=MOSCOW)
    end = datetime.combine(
        day + timedelta(days=1),
        time.min,
        tzinfo=MOSCOW,
    )

    rows = (
        Call.objects.filter(
            workspace_id=account.workspace_id,
            avito_account=account,
            occurred_at__gte=start,
            occurred_at__lt=end,
        )
        .exclude(report_text="")
        .order_by("occurred_at", "id")
        .values_list("buyer_phone", "report_text")
    )
    reports = [
        f"{format_report_phone(phone)}\n{text}" for phone, text in rows if text.strip()
    ]

    with override("ru"):
        day_label = date_format(day, "l, j E")

    return {
        "avito_account_id": account.pk,
        "account_name": account.name,
        "date": day.isoformat(),
        "report_count": len(reports),
        "report_text": (
            f"{day_label}\n{account.name}\n\n" + "\n\n".join(reports) if reports else ""
        ),
    }
