import re
from datetime import datetime, timedelta, timezone as dt_timezone
from uuid import uuid4

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from avitotask.models import AvitoAccount, AvitoListing, AvitoOAuthToken
from avitotask.services.avito_api import AvitoApiClient, AvitoApiError
from calls.models import Call, CallSyncState

HISTORY_START = datetime(2007, 1, 1, tzinfo=dt_timezone.utc)
WINDOW = timedelta(days=89)
PAGE_SIZE = 100
MAX_PAGES_PER_WINDOW = 1000
LEASE = timedelta(minutes=30)


class AudioUnavailable(Exception):
    pass


def _duration(value):
    if isinstance(value, bool):
        raise AvitoApiError("Avito вернул некорректную длительность.")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise AvitoApiError("Avito вернул некорректную длительность.") from exc
    if result < 0:
        raise AvitoApiError("Avito вернул отрицательную длительность.")
    return result


def normalize_phone(value):
    if not isinstance(value, str) or not re.fullmatch(r"\+?[\d\s()\-]+", value):
        return ""
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10 and digits.startswith("9"):
        digits = "7" + digits
    return digits if 11 <= len(digits) <= 15 and not digits.startswith("0") else ""


def upsert_call(account, item, *, existing_call=None, listing_ids=None):
    call_id = item.get("callId")
    if isinstance(call_id, bool) or not str(call_id).isdigit():
        raise AvitoApiError("Avito вернул звонок без корректного callId.")

    try:
        occurred_at = datetime.fromisoformat(
            item["callTime"].replace("Z", "+00:00")
        )
    except (KeyError, AttributeError, ValueError) as exc:
        raise AvitoApiError("Avito вернул некорректное время звонка.") from exc
    if timezone.is_naive(occurred_at):
        raise AvitoApiError("Avito вернул время звонка без часового пояса.")

    defaults = {
        "workspace_id": account.workspace_id,
        "occurred_at": occurred_at,
        "buyer_phone": item.get("buyerPhone") or "",
        "normalized_phone": normalize_phone(item.get("buyerPhone")),
        "talk_duration": _duration(item.get("talkDuration", 0)),
        "waiting_duration": _duration(item.get("waitingDuration", 0)),
    }

    if isinstance(item.get("isMissed"), bool):
        defaults["is_missed"] = item["isMissed"]

    item_id = item.get("itemId")
    if item_id not in (None, ""):
        item_id = str(item_id)
        defaults["avito_item_id"] = item_id
        defaults["listing_id"] = (
            listing_ids.get(item_id)
            if listing_ids is not None
            else AvitoListing.objects.filter(
                workspace_id=account.workspace_id,
                avito_account=account,
                avito_id=item_id,
            ).values_list("pk", flat=True).first()
        )

    if existing_call is not None:
        defaults = {
            field: value
            for field, value in defaults.items()
            if getattr(existing_call, field) != value
        }
        if not defaults:
            return existing_call

    call, _ = Call.objects.update_or_create(
        avito_account=account,
        external_id=str(call_id),
        defaults=defaults,
    )
    return call


def classify_account_history(account, state, lease_token, heartbeat):
    batch_size = 500
    last_id = 0

    # Сначала нормализуем номера, читая и записывая по одному пакету.
    while True:
        calls = list(
            Call.objects.filter(avito_account=account, id__gt=last_id)
            .order_by("id")
            .only("id", "buyer_phone", "normalized_phone", "call_type")[:batch_size]
        )
        if not calls:
            break

        last_id = calls[-1].id
        pending = []
        for call in calls:
            phone = normalize_phone(call.buyer_phone)
            call_type = (
                call.call_type
                if phone and phone == call.normalized_phone
                else None
            )
            if call.normalized_phone != phone or call.call_type != call_type:
                call.normalized_phone = phone
                call.call_type = call_type
                pending.append(call)

        with transaction.atomic():
            heartbeat()
            if pending:
                Call.objects.bulk_update(
                    pending, ["normalized_phone", "call_type"],
                )

    # В порядке номеров достаточно помнить только предыдущий номер.
    previous_phone = None
    cursor = None
    while True:
        queryset = Call.objects.filter(
            avito_account=account,
        ).exclude(normalized_phone="")
        if cursor is not None:
            phone, occurred_at, external_id = cursor
            queryset = queryset.filter(
                Q(normalized_phone__gt=phone)
                | Q(normalized_phone=phone, occurred_at__gt=occurred_at)
                | Q(
                    normalized_phone=phone,
                    occurred_at=occurred_at,
                    external_id__gt=external_id,
                )
            )

        calls = list(
            queryset.order_by(
                "normalized_phone", "occurred_at", "external_id",
            ).only(
                "id", "normalized_phone", "occurred_at",
                "external_id", "call_type",
            )[:batch_size]
        )
        if not calls:
            break

        cursor = (
            calls[-1].normalized_phone,
            calls[-1].occurred_at,
            calls[-1].external_id,
        )
        pending = []
        for call in calls:
            call_type = (
                Call.Type.NEW
                if call.normalized_phone != previous_phone
                else Call.Type.REPEAT
            )
            previous_phone = call.normalized_phone
            if call.call_type != call_type:
                call.call_type = call_type
                pending.append(call)

        with transaction.atomic():
            heartbeat()
            if pending:
                Call.objects.bulk_update(pending, ["call_type"])

    with transaction.atomic():
        heartbeat()
        updated = CallSyncState.objects.filter(
            pk=state.pk, lease_token=lease_token,
        ).update(classification_complete=True)
        if not updated:
            raise RuntimeError("Блокировка синхронизации звонков потеряна.")


def classify_changed_phones(account, phones):
    if not phones:
        return
    previous_phone = None
    pending = []
    calls = Call.objects.filter(
        avito_account=account, normalized_phone__in=phones,
    ).order_by("normalized_phone", "occurred_at", "external_id")
    for call in calls.iterator(chunk_size=500):
        call_type = Call.Type.NEW if call.normalized_phone != previous_phone else Call.Type.REPEAT
        previous_phone = call.normalized_phone
        if call.call_type != call_type:
            call.call_type = call_type
            pending.append(call)
        if len(pending) >= 500:
            Call.objects.bulk_update(pending, ["call_type"])
            pending.clear()
    if pending:
        Call.objects.bulk_update(pending, ["call_type"])


def fetch_call_window(account, token, start, end, client, heartbeat=None, *, classify=False):
    for page in range(MAX_PAGES_PER_WINDOW):
        if heartbeat:
            heartbeat()

        payload = client.request(
            "POST",
            "/calltracking/v1/getCalls/",
            token=token,
            json={
                "dateTimeFrom": start.isoformat(),
                "dateTimeTo": end.isoformat(),
                "limit": PAGE_SIZE,
                "offset": page * PAGE_SIZE,
            },
        )
        if not isinstance(payload, dict):
            raise AvitoApiError("Avito вернул некорректный ответ со звонками.")

        error = payload.get("error")
        if isinstance(error, dict) and error.get("code") not in (0, "0", None):
            raise AvitoApiError("Avito вернул ошибку при получении звонков.")

        rows = payload.get("calls")
        if not isinstance(rows, list):
            raise AvitoApiError("Avito не вернул список звонков.")
        if not rows:
            return
        if not all(isinstance(row, dict) for row in rows):
            raise AvitoApiError("Avito вернул некорректную карточку звонка.")

        with transaction.atomic():
            existing_calls = {
                call.external_id: call
                for call in Call.objects.select_for_update().filter(
                    workspace_id=account.workspace_id,
                    avito_account=account,
                    external_id__in=[str(row.get("callId")) for row in rows],
                )
            }

            item_ids = {
                str(row["itemId"])
                for row in rows
                if row.get("itemId") not in (None, "")
            }
            listing_ids = dict(
                AvitoListing.objects.filter(
                    workspace_id=account.workspace_id,
                    avito_account=account,
                    avito_id__in=item_ids,
                ).values_list("avito_id", "pk")
            )

            affected_phones = set()
            for row in rows:
                old = existing_calls.get(str(row.get("callId")))
                call = upsert_call(
                    account,
                    row,
                    existing_call=old,
                    listing_ids=listing_ids,
                )
                existing_calls[call.external_id] = call

                if classify:
                    if old is None:
                        if call.normalized_phone:
                            first_two = list(
                                Call.objects.filter(
                                    avito_account=account,
                                    normalized_phone=call.normalized_phone,
                                )
                                .order_by("occurred_at", "external_id")
                                .values_list("pk", "call_type")[:2]
                            )
                            is_first = first_two[0][0] == call.pk
                            call_type = (
                                Call.Type.NEW if is_first else Call.Type.REPEAT
                            )
                            Call.objects.filter(pk=call.pk).update(call_type=call_type)
                            call.call_type = call_type

                            if is_first and len(first_two) == 2:
                                previous_pk, previous_type = first_two[1]
                                if previous_type != Call.Type.REPEAT:
                                    Call.objects.filter(pk=previous_pk).update(
                                        call_type=Call.Type.REPEAT,
                                    )
                    elif (
                            (old.normalized_phone, old.occurred_at)
                            != (call.normalized_phone, call.occurred_at)
                            or old.call_type is None
                    ):
                        if old.normalized_phone:
                            affected_phones.add(old.normalized_phone)
                        if call.normalized_phone:
                            affected_phones.add(call.normalized_phone)
                        elif call.call_type is not None:
                            Call.objects.filter(pk=call.pk).update(call_type=None)
                            call.call_type = None

            if classify:
                classify_changed_phones(account, affected_phones)

        if len(rows) < PAGE_SIZE:
            return

    if end - start <= timedelta(seconds=1):
        raise AvitoApiError("Превышен предел страниц в минимальном периоде звонков.")

    middle = start + (end - start) / 2
    # Общая граница не оставляет пропусков; повторные звонки обработает upsert.
    fetch_call_window(
        account, token, start, middle, client, heartbeat, classify=classify,
    )
    fetch_call_window(
        account, token, middle, end, client, heartbeat, classify=classify,
    )


def sync_calls_for_account(account_id, *, client=None, now=None):
    account = AvitoAccount.objects.filter(
        pk=account_id, is_active=True,
    ).select_related("workspace").first()
    if account is None:
        return False

    try:
        token = account.oauth_tokens
    except AvitoOAuthToken.DoesNotExist:
        return False

    now = now or timezone.now()
    client = client or AvitoApiClient()
    state, _ = CallSyncState.objects.get_or_create(
        avito_account=account,
        defaults={"backfill_before": now - WINDOW},
    )

    lease_token = uuid4().hex
    claimed = CallSyncState.objects.filter(pk=state.pk).filter(
        Q(lease_until__isnull=True) | Q(lease_until__lte=timezone.now())
    ).update(
        lease_token=lease_token,
        lease_until=timezone.now() + LEASE,
        phase=CallSyncState.Phase.SYNCING,
    )
    if not claimed:
        return False

    state.refresh_from_db()

    def heartbeat():
        updated = CallSyncState.objects.filter(
            pk=state.pk, lease_token=lease_token,
        ).update(lease_until=timezone.now() + LEASE)
        if not updated:
            raise RuntimeError("Блокировка синхронизации звонков потеряна.")

    try:
        recent_from = (
            max(HISTORY_START, state.last_synced_at - timedelta(days=2))
            if state.last_synced_at
            else max(HISTORY_START, state.backfill_before or now - WINDOW)
        )
        backfill_upper_bound = recent_from
        while recent_from < now:
            recent_until = min(now, recent_from + WINDOW)
            fetch_call_window(
                account, token, recent_from, recent_until, client, heartbeat,
                classify=state.classification_complete,
            )
            CallSyncState.objects.filter(
                pk=state.pk, lease_token=lease_token,
            ).update(last_synced_at=recent_until, last_error="")
            recent_from = recent_until

        before = state.backfill_before
        complete = state.backfill_complete
        if not complete and before is None:
            before = backfill_upper_bound
            CallSyncState.objects.filter(
                pk=state.pk, lease_token=lease_token,
            ).update(backfill_before=before)
        for _ in range(4):
            if complete or before <= HISTORY_START:
                complete = True
                break

            start = max(HISTORY_START, before - WINDOW)
            fetch_call_window(
                account, token, start, before, client, heartbeat,
            )
            before = start
            complete = before <= HISTORY_START
            CallSyncState.objects.filter(
                pk=state.pk, lease_token=lease_token,
            ).update(
                backfill_before=before,
                backfill_complete=complete,
                last_error="",
            )

        if complete and not state.classification_complete:
            updated = CallSyncState.objects.filter(
                pk=state.pk, lease_token=lease_token,
            ).update(phase=CallSyncState.Phase.CLASSIFYING)
            if not updated:
                raise RuntimeError("Блокировка синхронизации звонков потеряна.")
            classify_account_history(account, state, lease_token, heartbeat)

        return not complete
    finally:
        CallSyncState.objects.filter(
            pk=state.pk, lease_token=lease_token,
        ).update(lease_token="", lease_until=None, phase=None)


def open_call_audio(token, external_id):
    client = AvitoApiClient()
    current_url = f"{client.base_url}/calltracking/v1/getRecordByCallId/"
    legacy_url = f"{client.base_url}/cpa/v1/call/{external_id}"

    def request(url, *, params=None):
        return client._send_request(
            "GET",
            url,
            params=params,
            headers={
                "Authorization": f"Bearer {token.access_token}",
                "Accept": "audio/mpeg",
            },
            stream=True,
        )

    response = request(current_url, params={"callId": external_id})
    if response.status_code == 401:
        response.close()
        client.refresh_access_token(token)
        response = request(current_url, params={"callId": external_id})

    if response.status_code == 403:
        response.close()
        response = request(legacy_url)

    if response.status_code in (404, 425):
        response.close()
        raise AudioUnavailable()

    # Прежний метод Avito возвращает 206 даже для полного файла.
    if response.status_code not in (200, 206):
        status_code = response.status_code
        response.close()
        raise AvitoApiError(
            "Не удалось получить запись звонка.", status_code=status_code,
        )

    if not response.headers.get("Content-Type", "").startswith("audio/"):
        response.close()
        raise AvitoApiError("Avito вернул не аудиофайл.")

    return response
