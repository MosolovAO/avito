"""Contract tests for calls, using redacted Avito response shapes."""

import asyncio
import gzip
from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from asgiref.sync import async_to_sync, sync_to_async
from celery.exceptions import Retry, SoftTimeLimitExceeded
from django.conf import settings
from django.db import DataError, connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone as django_timezone
from requests import Response
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate
from urllib3.response import HTTPResponse

from accounts.models import User, Workspace, WorkspaceMembership
from avitotask.models import AvitoAccount, AvitoListing, AvitoOAuthToken
from avitotask.services.avito_api import AvitoApiError
from calls.api_views import CallAudioView
from calls.models import Call, CallSyncState
from calls.services import (
    AudioUnavailable, LEASE, fetch_call_window, open_call_audio,
    sync_calls_for_account, upsert_call, classify_account_history,
)
from calls.tasks import enqueue_calls_sync_task, sync_calls_for_account_task

AVITO_CALL = {
    "buyerPhone": "+70000000001",
    "callId": 123456789,
    "callTime": "2026-04-02T12:34:56Z",
    "sellerPhone": "+70000000002",
    "talkDuration": 74,
    "virtualPhone": "+70000000003",
    "waitingDuration": 12,
}


class FakeCallsClient:
    def __init__(self, rows, *, inclusive_end=False):
        self.rows = rows
        self.inclusive_end = inclusive_end
        self.windows = []

    def request(self, method, path, *, token, json):
        start = datetime.fromisoformat(json["dateTimeFrom"])
        end = datetime.fromisoformat(json["dateTimeTo"])
        self.windows.append((start, end))
        matches = [
            row for row in self.rows
            if start <= (occurred_at := datetime.fromisoformat(row["callTime"].replace("Z", "+00:00")))
               and (occurred_at <= end if self.inclusive_end else occurred_at < end)
        ]
        return {
            "calls": matches[json["offset"]:json["offset"] + json["limit"]],
            "error": {"code": 0, "message": ""},
        }


def isolate_calls_audio_cache(test_case):
    cache_settings = test_case.settings(CACHES={
        **settings.CACHES,
        "calls_audio": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": test_case.id(),
        },
    })
    cache_settings.enable()
    test_case.addCleanup(cache_settings.disable)


class CallsMvpTests(TestCase):
    def setUp(self):
        isolate_calls_audio_cache(self)

    def test_report_rejects_empty_content(self):
        call = self.make_call(
            "empty-report",
            datetime(2026, 9, 29, tzinfo=timezone.utc),
        )
        call.report_text = "Существующий отчет"
        call.save(update_fields=["report_text"])
        client = self.api_as(self.owner, self.workspace)

        for content in ("", "   ", "\n\t", "\u00a0"):
            with self.subTest(content=content):
                response = client.put(
                    f"/api/calls/{call.pk}/report/",
                    {"report_text": content},
                    format="json",
                )

                self.assertEqual(response.status_code, 400)
                self.assertIn("report_text", response.data)
                call.refresh_from_db()
                self.assertEqual(call.report_text, "Существующий отчет")

    def test_report_cannot_update_call_from_another_workspace(self):
        call = upsert_call(self.other_account, AVITO_CALL)
        response = self.api_as(self.owner, self.workspace).put(
            f"/api/calls/{call.pk}/report/",
            {"report_text": "Чужой отчет"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        call.refresh_from_db()
        self.assertEqual(call.report_text, "")

    def test_report_save_returns_saved_content_in_call_list(self):
        call = self.make_call(
            "report-api",
            datetime(2026, 9, 29, 12, tzinfo=timezone.utc),
        )
        client = self.api_as(self.owner, self.workspace)
        report = (
            "Виктория\n"
            "ГСБ 40 кубов / Москва / Перезвонит клиенту"
        )

        response = client.put(
            f"/api/calls/{call.pk}/report/",
            {"report_text": report},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["report_text"], report)

        call.refresh_from_db()
        self.assertEqual(call.report_text, report)

        response = client.get(
            "/api/calls/",
            {
                "avito_account_id": self.account.pk,
                "date": "2026-09-29",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["id"], call.pk)
        self.assertEqual(response.data["results"][0]["report_text"], report)

    def test_repeat_import_preserves_call_report(self):
        call = upsert_call(self.account, AVITO_CALL)
        report = (
            "Виктория\n"
            "ГСБ 40 кубов / Москва / Перезвонит клиенту"
        )
        call.report_text = report
        call.save(update_fields=["report_text"])

        upsert_call(self.account, {**AVITO_CALL, "talkDuration": 90})

        call.refresh_from_db()
        self.assertEqual(call.report_text, report)
        self.assertEqual(call.talk_duration, 90)

    def test_report_edit_updates_the_same_call_without_changing_call_data(self):
        call = upsert_call(self.account, AVITO_CALL)
        client = self.api_as(self.owner, self.workspace)
        url = f"/api/calls/{call.pk}/report/"

        for report in ("Клиент перезвонит", "Заказ подтвержден\n40 кубов"):
            with self.subTest(report=report):
                response = client.put(
                    url, {"report_text": report}, format="json",
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["report_text"], report)
                call.refresh_from_db()
                self.assertEqual(call.report_text, report)
                self.assertEqual(call.buyer_phone, "+70000000001")
                self.assertEqual(call.talk_duration, 74)
                self.assertEqual(
                    Call.objects.filter(avito_account=self.account).count(), 1,
                )

    def test_report_is_allowed_for_every_role_with_call_access(self):
        call = self.make_call(
            "report-roles", datetime(2026, 9, 29, tzinfo=timezone.utc),
        )
        for role, user in (
            (WorkspaceMembership.Role.OWNER, self.owner),
            (WorkspaceMembership.Role.ADMIN, self.viewer),
            (WorkspaceMembership.Role.MANAGER, self.viewer),
            (WorkspaceMembership.Role.ANALYST, self.viewer),
        ):
            with self.subTest(role=role):
                membership = WorkspaceMembership.objects.get(
                    user=user, workspace=self.workspace,
                )
                membership.role = role
                membership.save(update_fields=["role"])
                report = f"Отчет участника {role}"
                response = self.api_as(user, self.workspace).put(
                    f"/api/calls/{call.pk}/report/",
                    {"report_text": report},
                    format="json",
                )
                self.assertEqual(response.status_code, 200)
                call.refresh_from_db()
                self.assertEqual(call.report_text, report)

    def test_report_is_forbidden_without_call_access(self):
        call = self.make_call(
            "report-forbidden", datetime(2026, 9, 29, tzinfo=timezone.utc),
        )
        response = self.api_as(self.viewer, self.workspace).put(
            f"/api/calls/{call.pk}/report/",
            {"report_text": "Недоступный отчет"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        call.refresh_from_db()
        self.assertEqual(call.report_text, "")

    def test_report_rejects_missing_invalid_or_oversized_text(self):
        call = self.make_call(
            "invalid-report", datetime(2026, 9, 29, tzinfo=timezone.utc),
        )
        call.report_text = "Существующий отчет"
        call.save(update_fields=["report_text"])
        client = self.api_as(self.owner, self.workspace)
        cases = (
            ("missing", {}),
            ("null", {"report_text": None}),
            ("number", {"report_text": 123}),
            ("list", {"report_text": []}),
            ("object", {"report_text": {}}),
            ("oversized", {"report_text": "а" * 20_001}),
        )
        for name, payload in cases:
            with self.subTest(case=name):
                response = client.put(
                    f"/api/calls/{call.pk}/report/", payload, format="json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("report_text", response.data)
                call.refresh_from_db()
                self.assertEqual(call.report_text, "Существующий отчет")

    def test_sync_exposes_each_phase_and_clears_it_on_completion(self):
        occurred_at = datetime(2026, 4, 2, 12, tzinfo=timezone.utc)
        self.make_call("1", occurred_at)
        state = CallSyncState.objects.create(
            avito_account=self.account,
            last_synced_at=occurred_at,
            backfill_complete=True,
        )
        observed = []

        class ObservingClient(FakeCallsClient):
            def request(inner_self, *args, **kwargs):
                observed.append(CallSyncState.objects.get(pk=state.pk).phase)
                return super().request(*args, **kwargs)

        def observe_classification(*args):
            observed.append(CallSyncState.objects.get(pk=state.pk).phase)
            return classify_account_history(*args)

        with patch(
                "calls.services.classify_account_history",
                side_effect=observe_classification,
        ):
            sync_calls_for_account(
                self.account.pk,
                client=ObservingClient([]),
                now=datetime(2026, 4, 3, tzinfo=timezone.utc),
            )

        state.refresh_from_db()
        self.assertEqual(observed, [
            CallSyncState.Phase.SYNCING,
            CallSyncState.Phase.CLASSIFYING,
        ])
        self.assertTrue(state.classification_complete)
        self.assertIsNone(state.phase)

    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("calls-owner@example.com")
        cls.viewer = User.objects.create_user("calls-viewer@example.com")
        cls.other_owner = User.objects.create_user("calls-other@example.com")
        cls.workspace = Workspace.objects.create(
            name="Calls", slug="calls-mvp", owner=cls.owner,
        )
        cls.other_workspace = Workspace.objects.create(
            name="Other", slug="calls-other", owner=cls.other_owner,
        )
        WorkspaceMembership.objects.create(
            user=cls.owner, workspace=cls.workspace,
            role=WorkspaceMembership.Role.OWNER,
        )
        WorkspaceMembership.objects.create(
            user=cls.viewer, workspace=cls.workspace,
            role=WorkspaceMembership.Role.VIEWER,
        )
        WorkspaceMembership.objects.create(
            user=cls.other_owner, workspace=cls.other_workspace,
            role=WorkspaceMembership.Role.OWNER,
        )
        cls.account = AvitoAccount.objects.create(
            workspace=cls.workspace, name="Main",
        )
        cls.other_account = AvitoAccount.objects.create(
            workspace=cls.other_workspace, name="Foreign",
        )
        AvitoOAuthToken.objects.create(
            workspace=cls.workspace, avito_account=cls.account,
            access_token="test-token",
        )

    def api_as(self, user, workspace):
        client = APIClient()
        client.force_authenticate(user=user)
        client.defaults["HTTP_X_WORKSPACE_ID"] = str(workspace.pk)
        return client

    def make_call(self, external_id, occurred_at):
        return Call.objects.create(
            workspace=self.workspace,
            avito_account=self.account,
            external_id=external_id,
            occurred_at=occurred_at,
            buyer_phone="+70000000001",
            talk_duration=74,
            waiting_duration=12,
        )

    def test_repeat_import_updates_existing_call_without_duplicate(self):
        upsert_call(self.account, {**AVITO_CALL, "callType": "repeat"})
        upsert_call(self.account, {**AVITO_CALL, "talkDuration": 75, "callType": "new"})

        self.assertEqual(Call.objects.filter(avito_account=self.account).count(), 1)
        call = Call.objects.get(avito_account=self.account)
        self.assertEqual(call.external_id, "123456789")
        self.assertEqual(call.talk_duration, 75)
        self.assertIsNone(call.is_missed)
        self.assertIsNone(call.call_type)
        self.assertIsNone(call.listing_id)

        call.call_type = Call.Type.NEW
        call.save(update_fields=["call_type"])
        upsert_call(self.account, {**AVITO_CALL, "callType": "repeat"})
        call.refresh_from_db()
        self.assertEqual(call.call_type, Call.Type.NEW)

    def test_list_resolves_listing_imported_after_call_without_crossing_accounts(self):
        call = upsert_call(self.account, {**AVITO_CALL, "itemId": "777"})
        self.assertIsNone(call.listing_id)
        AvitoListing.objects.create(
            workspace=self.other_workspace,
            avito_account=self.other_account,
            avito_id="777",
            title="Чужое объявление",
        )
        url = f"/api/calls/?avito_account_id={self.account.pk}"

        before = self.api_as(self.owner, self.workspace).get(url)
        self.assertEqual(before.status_code, 200)
        self.assertEqual(before.data["results"][0]["listing"], {
            "id": None, "avito_id": "777", "title": None, "url": None,
        })

        listing = AvitoListing.objects.create(
            workspace=self.workspace,
            avito_account=self.account,
            avito_id="777",
            title="Позднее объявление",
            url="https://www.avito.ru/item/777",
        )
        after = self.api_as(self.owner, self.workspace).get(url)
        self.assertEqual(after.status_code, 200)
        self.assertEqual(after.data["results"][0]["listing"], {
            "id": listing.pk,
            "avito_id": "777",
            "title": "Позднее объявление",
            "url": "https://www.avito.ru/item/777",
        })

    def test_list_search_filters_before_pagination(self):
        at = datetime(2026, 9, 28, 9, tzinfo=timezone.utc)
        matching = self.make_call("matching", at)
        matching.buyer_phone = "+7 (999) 123-45-67"
        matching.normalized_phone = "79991234567"
        matching.save(update_fields=["buyer_phone", "normalized_phone"])
        self.make_call("other", at + timedelta(minutes=1))

        response = self.api_as(self.owner, self.workspace).get(
            "/api/calls/", {
                "avito_account_id": self.account.pk,
                "date": "2026-09-28",
                "search": "+7 (999) 123-45-67",
                "page_size": 1,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], matching.pk)
        self.assertIsNone(response.data["next"])

    def test_list_search_normalizes_full_phone_before_pagination(self):
        matching = upsert_call(self.account, {
            **AVITO_CALL,
            "buyerPhone": "+7 (999) 123-45-67",
        })
        self.make_call("other", matching.occurred_at + timedelta(minutes=1))
        upsert_call(self.other_account, {
            **AVITO_CALL,
            "buyerPhone": "+7 (999) 123-45-67",
        })
        client = self.api_as(self.owner, self.workspace)

        for search in (
                "89991234567", "8 (999) 123-45-67",
                "79991234567", "+7 (999) 123-45-67",
                "9991234567", "999 123-45-67",
        ):
            with self.subTest(search=search):
                response = client.get("/api/calls/", {
                    "avito_account_id": self.account.pk,
                    "search": search,
                    "page_size": 1,
                })
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["count"], 1)
                self.assertEqual(
                    [row["id"] for row in response.data["results"]],
                    [matching.pk],
                )
                self.assertIsNone(response.data["next"])

    def test_list_search_keeps_partial_phone_matching(self):
        matching = upsert_call(self.account, {
            **AVITO_CALL,
            "buyerPhone": "+7 (999) 812-34-56",
        })
        self.make_call("other", matching.occurred_at + timedelta(minutes=1))
        client = self.api_as(self.owner, self.workspace)

        for search in ("8", "81234", "812-34", "999 812"):
            with self.subTest(search=search):
                response = client.get("/api/calls/", {
                    "avito_account_id": self.account.pk,
                    "search": search,
                })
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    [row["id"] for row in response.data["results"]],
                    [matching.pk],
                )

    def test_list_search_keeps_item_id_starting_with_eight(self):
        matching = upsert_call(self.account, {
            **AVITO_CALL,
            "itemId": "89991234567",
        })
        client = self.api_as(self.owner, self.workspace)

        for search in ("89991234567", "8999123"):
            with self.subTest(search=search):
                response = client.get("/api/calls/", {
                    "avito_account_id": self.account.pk,
                    "search": search,
                })
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    [row["id"] for row in response.data["results"]],
                    [matching.pk],
                )

    def test_list_search_finds_late_listing_title_and_id_in_current_account(self):
        at = datetime(2026, 9, 28, 9, tzinfo=timezone.utc)
        title_call = self.make_call("title", at)
        title_call.avito_item_id = "777"
        title_call.save(update_fields=["avito_item_id"])
        id_call = self.make_call("id", at + timedelta(minutes=1))
        id_call.avito_item_id = "998877"
        id_call.save(update_fields=["avito_item_id"])
        AvitoListing.objects.create(
            workspace=self.workspace, avito_account=self.account,
            avito_id="777", title="Велосипед Stels",
        )
        AvitoListing.objects.create(
            workspace=self.other_workspace, avito_account=self.other_account,
            avito_id="998877", title="Чужое объявление",
        )
        client = self.api_as(self.owner, self.workspace)

        by_title = client.get("/api/calls/", {
            "avito_account_id": self.account.pk, "search": "велосипед",
        })
        by_id = client.get("/api/calls/", {
            "avito_account_id": self.account.pk, "search": "998877",
        })
        foreign_title = client.get("/api/calls/", {
            "avito_account_id": self.account.pk, "search": "Чужое",
        })

        self.assertEqual([row["id"] for row in by_title.data["results"]], [title_call.pk])
        self.assertEqual([row["id"] for row in by_id.data["results"]], [id_call.pk])
        self.assertEqual(foreign_title.data["count"], 0)

    def test_window_fetches_all_pages_without_skipping_boundary(self):
        rows = [
            {**AVITO_CALL, "callId": index}
            for index in range(101)
        ]

        class FakeClient:
            def request(self, method, path, *, token, json):
                self_call = json["offset"]
                return {
                    "calls": rows[self_call:self_call + json["limit"]],
                    "error": {"code": 0, "message": ""},
                }

        fetch_call_window(
            self.account,
            self.account.oauth_tokens,
            datetime(2026, 4, 1, tzinfo=timezone.utc),
            datetime(2026, 4, 3, tzinfo=timezone.utc),
            FakeClient(),
        )

        self.assertEqual(Call.objects.filter(avito_account=self.account).count(), 101)

    @patch("calls.services.PAGE_SIZE", 2)
    @patch("calls.services.MAX_PAGES_PER_WINDOW", 2)
    def test_full_window_splits_recursively_without_losing_calls(self):
        start = datetime(2026, 4, 1, tzinfo=timezone.utc)
        end = start + timedelta(hours=16)
        for count, inclusive_end in ((4, False), (5, False), (9, False), (9, True)):
            with self.subTest(count=count, inclusive_end=inclusive_end):
                Call.objects.filter(avito_account=self.account).delete()
                rows = [
                    {**AVITO_CALL, "callId": index,
                     "callTime": (start + timedelta(hours=index)).isoformat()}
                    for index in range(count)
                ]
                client = FakeCallsClient(rows, inclusive_end=inclusive_end)
                heartbeat = Mock()

                fetch_call_window(
                    self.account, self.account.oauth_tokens, start, end,
                    client, heartbeat, classify=True,
                )

                calls = Call.objects.filter(avito_account=self.account).order_by("occurred_at")
                self.assertEqual(list(calls.values_list("external_id", flat=True)),
                                 [str(index) for index in range(count)])
                self.assertEqual(list(calls.values_list("call_type", flat=True)),
                                 [Call.Type.NEW] + [Call.Type.REPEAT] * (count - 1))
                self.assertEqual(heartbeat.call_count, len(client.windows))
                self.assertTrue(any(right - left < end - start for left, right in client.windows))

    @patch("calls.services.PAGE_SIZE", 2)
    @patch("calls.services.MAX_PAGES_PER_WINDOW", 2)
    @patch("calls.services.WINDOW", timedelta(days=8))
    @patch("calls.services.HISTORY_START", datetime(2026, 1, 1, tzinfo=timezone.utc))
    def test_full_recent_and_backfill_windows_advance_cursors_between_runs(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        now = datetime(2026, 1, 17, tzinfo=timezone.utc)
        rows = [
            {**AVITO_CALL, "callId": index,
             "callTime": (start + timedelta(days=index)).isoformat()}
            for index in range(14)
        ]
        for recent in (True, False):
            with self.subTest(recent=recent):
                Call.objects.filter(avito_account=self.account).delete()
                state, _ = CallSyncState.objects.update_or_create(
                    avito_account=self.account,
                    defaults={
                        "last_synced_at": None if recent else now,
                        "backfill_before": start + timedelta(days=1) if recent else now,
                        "backfill_complete": False,
                        "classification_complete": False,
                    },
                )
                client = FakeCallsClient(rows)

                self.assertFalse(sync_calls_for_account(self.account.pk, client=client, now=now))

                state.refresh_from_db()
                self.assertEqual(state.last_synced_at, now)
                self.assertEqual(state.backfill_before, start)
                self.assertTrue(state.backfill_complete)
                self.assertTrue(state.classification_complete)
                self.assertEqual(Call.objects.filter(avito_account=self.account).count(), 14)
                self.assertFalse(Call.objects.filter(call_type__isnull=True).exists())

                client.windows.clear()
                self.assertFalse(sync_calls_for_account(self.account.pk, client=client, now=now))
                self.assertEqual(client.windows, [(now - timedelta(days=2), now)])

    @patch("calls.services.PAGE_SIZE", 2)
    @patch("calls.services.MAX_PAGES_PER_WINDOW", 2)
    def test_error_in_split_window_does_not_advance_cursor(self):
        start = datetime(2026, 4, 1, tzinfo=timezone.utc)
        now = start + timedelta(days=2)
        middle = start + timedelta(days=1)
        state = CallSyncState.objects.create(avito_account=self.account, backfill_before=start)
        rows = [
            {**AVITO_CALL, "callId": index,
             "callTime": (start + timedelta(hours=12 * index)).isoformat()}
            for index in range(4)
        ]

        class FailingClient(FakeCallsClient):
            def request(inner_self, *args, **kwargs):
                if datetime.fromisoformat(kwargs["json"]["dateTimeFrom"]) == middle:
                    raise AvitoApiError("Temporary API failure", status_code=503)
                return super().request(*args, **kwargs)

        with self.assertRaises(AvitoApiError) as raised:
            sync_calls_for_account(self.account.pk, client=FailingClient(rows), now=now)

        self.assertEqual(raised.exception.status_code, 503)
        state.refresh_from_db()
        self.assertIsNone(state.last_synced_at)
        self.assertEqual(state.backfill_before, start)
        self.assertFalse(state.backfill_complete)
        self.assertFalse(state.classification_complete)
        self.assertEqual(state.lease_token, "")
        self.assertIsNone(state.lease_until)

    @patch("calls.services.PAGE_SIZE", 2)
    @patch("calls.services.MAX_PAGES_PER_WINDOW", 2)
    def test_full_one_second_window_fails_without_further_splitting(self):
        start = datetime(2026, 4, 1, tzinfo=timezone.utc)
        client = FakeCallsClient([
            {**AVITO_CALL, "callId": index, "callTime": start.isoformat()}
            for index in range(5)
        ])

        with self.assertRaisesMessage(AvitoApiError, "минимальном"):
            fetch_call_window(
                self.account, self.account.oauth_tokens,
                start, start + timedelta(seconds=1), client,
            )

        self.assertEqual(len(client.windows), 2)

    def test_history_is_classified_only_after_backfill_including_missed_calls(self):
        rows = [
            {**AVITO_CALL, "callId": 1, "callTime": "2025-01-02T10:00:00Z",
             "isMissed": True},
            {**AVITO_CALL, "callId": 2, "callTime": "2025-05-01T10:00:00Z",
             "buyerPhone": "8 (000) 000-00-01"},
            {**AVITO_CALL, "callId": 3, "callTime": "2026-04-02T10:00:00Z"},
        ]

        client = FakeCallsClient(rows)
        now = datetime(2026, 4, 3, tzinfo=timezone.utc)
        with patch("calls.services.HISTORY_START", datetime(2025, 1, 1, tzinfo=timezone.utc)):
            self.assertTrue(sync_calls_for_account(self.account.pk, client=client, now=now))
            self.assertIsNone(Call.objects.get(external_id="3").call_type)
            self.assertFalse(CallSyncState.objects.get(avito_account=self.account).backfill_complete)

            self.assertFalse(sync_calls_for_account(self.account.pk, client=client, now=now))

        self.assertEqual(
            list(Call.objects.filter(avito_account=self.account)
                 .order_by("occurred_at").values_list("call_type", flat=True)),
            [Call.Type.NEW, Call.Type.REPEAT, Call.Type.REPEAT],
        )
        self.assertTrue(Call.objects.get(external_id="1").is_missed)

    def test_incremental_sync_reclassifies_number_when_earlier_call_arrives(self):
        old_first = self.make_call("existing", datetime(2026, 4, 2, 12, tzinfo=timezone.utc))
        old_first.call_type = Call.Type.NEW
        old_first.normalized_phone = "70000000001"
        old_first.save(update_fields=["call_type", "normalized_phone"])
        other_account_call = Call.objects.create(
            workspace=self.other_workspace, avito_account=self.other_account,
            external_id="foreign", occurred_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
            buyer_phone="+70000000001", normalized_phone="70000000001",
            call_type=Call.Type.NEW,
        )
        CallSyncState.objects.create(
            avito_account=self.account,
            last_synced_at=datetime(2026, 4, 2, tzinfo=timezone.utc),
            backfill_complete=True, classification_complete=True,
        )
        client = FakeCallsClient([
            {**AVITO_CALL, "callId": 10, "callTime": "2026-04-01T10:00:00Z",
             "isMissed": True},
            {**AVITO_CALL, "callId": 11, "callTime": "2026-04-03T09:00:00Z",
             "buyerPhone": "8 (000) 000-00-01"},
        ])

        self.assertFalse(sync_calls_for_account(
            self.account.pk, client=client,
            now=datetime(2026, 4, 3, 12, tzinfo=timezone.utc),
        ))

        self.assertEqual(Call.objects.get(external_id="10").call_type, Call.Type.NEW)
        self.assertEqual(Call.objects.get(external_id="11").call_type, Call.Type.REPEAT)
        old_first.refresh_from_db()
        self.assertEqual(old_first.call_type, Call.Type.REPEAT)
        other_account_call.refresh_from_db()
        self.assertEqual(other_account_call.call_type, Call.Type.NEW)
        self.assertEqual(len(client.windows), 1)
        self.assertGreaterEqual(client.windows[0][0], datetime(2026, 3, 31, tzinfo=timezone.utc))

    def test_incremental_sync_keeps_missing_number_unclassified(self):
        CallSyncState.objects.create(
            avito_account=self.account,
            last_synced_at=datetime(2026, 4, 2, tzinfo=timezone.utc),
            backfill_complete=True, classification_complete=True,
        )
        client = FakeCallsClient([
            {**AVITO_CALL, "callId": 20, "callTime": "2026-04-03T09:00:00Z",
             "buyerPhone": ""},
            {**AVITO_CALL, "callId": 21, "callTime": "2026-04-03T10:00:00Z",
             "buyerPhone": "***1234"},
        ])

        sync_calls_for_account(
            self.account.pk, client=client,
            now=datetime(2026, 4, 3, 12, tzinfo=timezone.utc),
        )

        self.assertEqual(
            list(Call.objects.filter(avito_account=self.account)
                 .order_by("external_id").values_list("call_type", flat=True)),
            [None, None],
        )

    def test_completed_existing_history_uses_external_id_to_break_time_ties(self):
        occurred_at = datetime(2026, 4, 2, 12, tzinfo=timezone.utc)
        self.make_call("2", occurred_at)
        self.make_call("1", occurred_at)
        CallSyncState.objects.create(
            avito_account=self.account,
            last_synced_at=occurred_at,
            backfill_complete=True,
        )

        sync_calls_for_account(
            self.account.pk, client=FakeCallsClient([]),
            now=datetime(2026, 4, 3, tzinfo=timezone.utc),
        )

        self.assertEqual(
            list(Call.objects.filter(avito_account=self.account)
                 .order_by("external_id").values_list("call_type", flat=True)),
            [Call.Type.NEW, Call.Type.REPEAT],
        )
        self.assertTrue(CallSyncState.objects.get(avito_account=self.account).classification_complete)

    def test_retry_of_first_window_uses_saved_lower_bound(self):
        CallSyncState.objects.create(
            avito_account=self.account,
            backfill_before=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        client = FakeCallsClient([
            {**AVITO_CALL, "callId": 30, "callTime": "2026-01-02T10:00:00Z"},
        ])

        with patch("calls.services.HISTORY_START", datetime(2026, 1, 1, tzinfo=timezone.utc)):
            sync_calls_for_account(
                self.account.pk, client=client,
                now=datetime(2026, 4, 3, tzinfo=timezone.utc),
            )

        self.assertTrue(Call.objects.filter(external_id="30").exists())
        self.assertEqual(Call.objects.get(external_id="30").call_type, Call.Type.NEW)
        self.assertEqual(client.windows[0][0], datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertTrue(all(
            end - start <= timedelta(days=89) for start, end in client.windows
        ))

    def test_missing_backfill_cursor_does_not_finish_partial_history(self):
        CallSyncState.objects.create(
            avito_account=self.account,
            last_synced_at=datetime(2026, 4, 2, tzinfo=timezone.utc),
        )
        client = FakeCallsClient([
            {**AVITO_CALL, "callId": 40, "callTime": "2025-01-02T10:00:00Z"},
            {**AVITO_CALL, "callId": 41, "callTime": "2026-04-02T10:00:00Z"},
        ])

        with patch("calls.services.HISTORY_START", datetime(2025, 1, 1, tzinfo=timezone.utc)):
            remaining = sync_calls_for_account(
                self.account.pk, client=client,
                now=datetime(2026, 4, 3, tzinfo=timezone.utc),
            )

        state = CallSyncState.objects.get(avito_account=self.account)
        self.assertTrue(remaining)
        self.assertFalse(state.backfill_complete)
        self.assertFalse(state.classification_complete)
        self.assertIsNone(Call.objects.get(external_id="41").call_type)

    def test_allowed_roles_can_view_calls(self):
        self.make_call("1", datetime(2026, 4, 2, 12, tzinfo=timezone.utc))
        url = f"/api/calls/?avito_account_id={self.account.pk}"

        for role in (
                WorkspaceMembership.Role.ADMIN,
                WorkspaceMembership.Role.MANAGER,
                WorkspaceMembership.Role.ANALYST,
        ):
            with self.subTest(role=role):
                user = User.objects.create_user(f"calls-{role}@example.com")
                WorkspaceMembership.objects.create(
                    user=user, workspace=self.workspace, role=role,
                )
                response = self.api_as(user, self.workspace).get(url)
                self.assertEqual(response.status_code, 200)

    def test_list_scopes_account_to_workspace_and_excludes_viewer(self):
        self.make_call("1", datetime(2026, 4, 2, 12, tzinfo=timezone.utc))
        url = f"/api/calls/?avito_account_id={self.account.pk}"

        owner_response = self.api_as(self.owner, self.workspace).get(url)
        self.assertEqual(owner_response.status_code, 200)
        self.assertEqual(owner_response.data["count"], 1)

        viewer_response = self.api_as(self.viewer, self.workspace).get(url)
        self.assertEqual(viewer_response.status_code, 403)

        foreign_response = self.api_as(self.owner, self.workspace).get(
            f"/api/calls/?avito_account_id={self.other_account.pk}"
        )
        self.assertEqual(foreign_response.status_code, 404)

    def test_sync_status_shows_account_error_without_leaking_other_workspace(self):
        checked_at = datetime(2026, 4, 2, 12, tzinfo=timezone.utc)
        CallSyncState.objects.create(
            avito_account=self.account,
            last_synced_at=checked_at,
            backfill_complete=False,
            last_error="Ошибка Avito API (HTTP неизвестен).",
            lease_until=django_timezone.now() + timedelta(minutes=5),
        )
        url = f"/api/calls/sync-status/?avito_account_id={self.account.pk}"

        response = self.api_as(self.owner, self.workspace).get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["last_synced_at"], checked_at.isoformat())
        self.assertFalse(response.data["backfill_complete"])
        self.assertTrue(response.data["is_syncing"])
        self.assertEqual(
            response.data["last_error"],
            "Ошибка Avito API (HTTP неизвестен).",
        )
        self.assertEqual(
            self.api_as(self.viewer, self.workspace).get(url).status_code, 403,
        )
        self.assertEqual(
            self.api_as(self.owner, self.workspace).get(
                f"/api/calls/sync-status/?avito_account_id={self.other_account.pk}"
            ).status_code,
            404,
        )

    def test_sync_status_handles_never_started_and_expired_lease(self):
        url = f"/api/calls/sync-status/?avito_account_id={self.account.pk}"
        client = self.api_as(self.owner, self.workspace)

        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["last_synced_at"])
        self.assertFalse(response.data["backfill_complete"])
        self.assertFalse(response.data["is_syncing"])
        self.assertEqual(response.data["last_error"], "")

        CallSyncState.objects.create(
            avito_account=self.account,
            lease_until=django_timezone.now() - timedelta(minutes=1),
        )
        self.assertFalse(client.get(url).data["is_syncing"])
        self.assertEqual(
            client.get("/api/calls/sync-status/").status_code, 400,
        )

    def test_date_filter_uses_moscow_midnight_and_half_open_interval(self):
        self.make_call("before", datetime(2026, 4, 1, 20, 59, tzinfo=timezone.utc))
        self.make_call("inside", datetime(2026, 4, 1, 21, tzinfo=timezone.utc))
        self.make_call("after", datetime(2026, 4, 2, 21, tzinfo=timezone.utc))

        response = self.api_as(self.owner, self.workspace).get(
            f"/api/calls/?avito_account_id={self.account.pk}&date=2026-04-02"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["external_id"], "inside")

    def test_list_paginates_and_rejects_invalid_date(self):
        for index in range(31):
            self.make_call(
                str(index), datetime(2026, 4, 2, 12, tzinfo=timezone.utc),
            )
        client = self.api_as(self.owner, self.workspace)
        url = f"/api/calls/?avito_account_id={self.account.pk}"

        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 31)
        self.assertEqual(len(response.data["results"]), 30)
        self.assertEqual(client.get(url + "&date=2026-02-30").status_code, 400)

    def test_multiple_memberships_require_workspace_header(self):
        WorkspaceMembership.objects.create(
            user=self.owner, workspace=self.other_workspace,
            role=WorkspaceMembership.Role.MANAGER,
        )
        client = APIClient()
        client.force_authenticate(user=self.owner)

        response = client.get(f"/api/calls/?avito_account_id={self.account.pk}")

        self.assertEqual(response.status_code, 400)

    def make_audio_upstream(self, *args):
        upstream = Response()
        upstream.status_code = 200
        upstream.headers["Content-Type"] = "audio/mpeg"
        upstream.headers["Content-Length"] = "5"
        upstream.raw = BytesIO(b"audio")
        return upstream

    def finish_audio_response(self, response):
        if response.streaming:
            async def read_audio():
                return b"".join([chunk async for chunk in response])

            self.assertEqual(async_to_sync(read_audio)(), b"audio")

    @patch("rest_framework.throttling.SimpleRateThrottle.timer", return_value=1000)
    def test_audio_limit_blocks_avito_and_resets_at_window_boundary(self, timer):
        call = self.make_call("audio-limit", self.now_for_audio())
        client = self.api_as(self.owner, self.workspace)
        url = f"/api/calls/{call.pk}/audio/"
        with (
            self.settings(AVITO_CALLS_AUDIO_THROTTLE_RATE="2/min"),
            patch("calls.api_views.open_call_audio", side_effect=self.make_audio_upstream) as audio,
        ):
            for _ in range(2):
                response = client.get(url)
                try:
                    self.assertEqual(response.status_code, 200)
                finally:
                    self.finish_audio_response(response)

            blocked = client.get(url)
            self.assertEqual(blocked.status_code, 429)
            self.assertEqual(blocked["Retry-After"], "60")
            self.assertEqual(audio.call_count, 2)

            timer.return_value = 1059
            blocked = client.get(url)
            self.assertEqual(blocked.status_code, 429)
            self.assertEqual(blocked["Retry-After"], "1")
            self.assertEqual(audio.call_count, 2)

            timer.return_value = 1060
            response = client.get(url)
            try:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(audio.call_count, 3)
            finally:
                self.finish_audio_response(response)

    def now_for_audio(self):
        return datetime(2026, 4, 2, 12, tzinfo=timezone.utc)

    @patch("rest_framework.throttling.SimpleRateThrottle.timer", return_value=1000)
    def test_audio_limit_is_shared_across_workspaces_for_one_user(self, timer):
        WorkspaceMembership.objects.create(
            user=self.owner, workspace=self.other_workspace,
            role=WorkspaceMembership.Role.MANAGER,
        )
        AvitoOAuthToken.objects.create(
            workspace=self.other_workspace, avito_account=self.other_account,
            access_token="test-other-token",
        )
        first = self.make_call("first-audio", self.now_for_audio())
        second = Call.objects.create(
            workspace=self.other_workspace, avito_account=self.other_account,
            external_id="second-audio", occurred_at=self.now_for_audio(),
        )
        with (
            self.settings(AVITO_CALLS_AUDIO_THROTTLE_RATE="1/min"),
            patch("calls.api_views.open_call_audio", side_effect=self.make_audio_upstream) as audio,
        ):
            response = self.api_as(self.owner, self.workspace).get(
                f"/api/calls/{first.pk}/audio/",
            )
            try:
                self.assertEqual(response.status_code, 200)
            finally:
                self.finish_audio_response(response)
            blocked = self.api_as(self.owner, self.other_workspace).get(
                f"/api/calls/{second.pk}/audio/",
            )
            self.assertEqual(blocked.status_code, 429)
            self.assertEqual(audio.call_count, 1)

    @patch("rest_framework.throttling.SimpleRateThrottle.timer", return_value=1000)
    def test_audio_limit_does_not_block_another_user(self, timer):
        WorkspaceMembership.objects.create(
            user=self.other_owner, workspace=self.workspace,
            role=WorkspaceMembership.Role.MANAGER,
        )
        call = self.make_call("separate-user-limit", self.now_for_audio())
        url = f"/api/calls/{call.pk}/audio/"
        with (
            self.settings(AVITO_CALLS_AUDIO_THROTTLE_RATE="1/min"),
            patch("calls.api_views.open_call_audio", side_effect=self.make_audio_upstream) as audio,
        ):
            owner_client = self.api_as(self.owner, self.workspace)
            response = owner_client.get(url)
            try:
                self.assertEqual(response.status_code, 200)
            finally:
                self.finish_audio_response(response)
            self.assertEqual(owner_client.get(url).status_code, 429)

            response = self.api_as(self.other_owner, self.workspace).get(url)
            try:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(audio.call_count, 2)
            finally:
                self.finish_audio_response(response)

    @patch("rest_framework.throttling.SimpleRateThrottle.timer", return_value=1000)
    def test_audio_limit_does_not_block_call_list_or_sync_status(self, timer):
        call = self.make_call("audio-only-limit", self.now_for_audio())
        client = self.api_as(self.owner, self.workspace)
        audio_url = f"/api/calls/{call.pk}/audio/"
        with (
            self.settings(AVITO_CALLS_AUDIO_THROTTLE_RATE="1/min"),
            patch("calls.api_views.open_call_audio", side_effect=self.make_audio_upstream) as audio,
        ):
            response = client.get(audio_url)
            try:
                self.assertEqual(response.status_code, 200)
            finally:
                self.finish_audio_response(response)
            self.assertEqual(client.get(audio_url).status_code, 429)
            for url in ("/api/calls/", "/api/calls/sync-status/"):
                with self.subTest(url=url):
                    response = client.get(url, {"avito_account_id": self.account.pk})
                    self.assertEqual(response.status_code, 200)
            self.assertEqual(audio.call_count, 1)

    def test_audio_unavailable_preserves_card(self):
        call = self.make_call(
            "recording-later",
            datetime(2026, 4, 2, 12, tzinfo=timezone.utc),
        )
        with patch("calls.api_views.open_call_audio", side_effect=AudioUnavailable):
            response = self.api_as(self.owner, self.workspace).get(
                f"/api/calls/{call.pk}/audio/"
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["code"], "audio_unavailable")
        self.assertTrue(Call.objects.filter(pk=call.pk).exists())

    def test_audio_falls_back_when_calltracking_record_is_forbidden(self):
        primary = Mock(status_code=403, headers={"Content-Type": "application/json"})
        legacy = Mock(
            status_code=206,
            headers={
                "Content-Type": "audio/mpeg",
                "Content-Length": "469413",
                "Content-Range": "bytes 0-469412/469413",
            },
        )
        with patch("calls.services.AvitoApiClient") as client_class:
            client_class.return_value.base_url = "https://api.avito.ru"
            client_class.return_value._send_request.side_effect = [primary, legacy]

            response = open_call_audio(self.account.oauth_tokens, "123456789")

        self.assertIs(response, legacy)
        primary.close.assert_called_once()
        self.assertEqual(client_class.return_value._send_request.call_count, 2)
        self.assertEqual(
            client_class.return_value._send_request.call_args.args[:2],
            ("GET", "https://api.avito.ru/cpa/v1/call/123456789"),
        )

    def test_audio_checks_workspace_before_contacting_avito(self):
        foreign_call = Call.objects.create(
            workspace=self.other_workspace,
            avito_account=self.other_account,
            external_id="foreign",
            occurred_at=datetime(2026, 4, 2, 12, tzinfo=timezone.utc),
        )
        with patch("calls.api_views.open_call_audio") as audio_request:
            response = self.api_as(self.owner, self.workspace).get(
                f"/api/calls/{foreign_call.pk}/audio/"
            )

        self.assertEqual(response.status_code, 404)
        audio_request.assert_not_called()

    def test_dispatch_failure_for_one_account_does_not_skip_next(self):
        AvitoOAuthToken.objects.create(
            workspace=self.other_workspace,
            avito_account=self.other_account,
            access_token="another-test-token",
        )
        with patch(
                "calls.tasks.sync_calls_for_account_task.delay",
                side_effect=[RuntimeError("broker issue"), object()],
        ):
            result = enqueue_calls_sync_task()

        self.assertEqual(result, {"queued": 1, "failed": 1})

    def test_invalid_workspace_header_returns_400_on_each_calls_endpoint(self):
        call = self.make_call("header-test", datetime(2026, 4, 2, tzinfo=timezone.utc))
        urls = (
            f"/api/calls/?avito_account_id={self.account.pk}",
            f"/api/calls/sync-status/?avito_account_id={self.account.pk}",
            f"/api/calls/{call.pk}/audio/",
        )
        client = self.api_as(self.owner, self.workspace)
        client.raise_request_exception = False
        with patch("calls.api_views.open_call_audio", side_effect=AudioUnavailable) as audio:
            for url in urls:
                with self.subTest(url=url):
                    with self.assertNumQueries(0):
                        response = client.get(url, HTTP_X_WORKSPACE_ID="abc")
                    self.assertEqual(response.status_code, 400)
                    self.assertIn("workspace", response.data)
            audio.assert_not_called()

    def test_workspace_header_rejects_empty_noninteger_and_out_of_range_ids(self):
        client = self.api_as(self.owner, self.workspace)
        client.raise_request_exception = False
        for value in ("", " ", "1.5", "0", "-1", "9223372036854775808", "9" * 200):
            with self.subTest(value=value):
                response = client.get(
                    f"/api/calls/?avito_account_id={self.account.pk}",
                    HTTP_X_WORKSPACE_ID=value,
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("workspace", response.data)

    def test_valid_workspace_header_keeps_access_to_the_selected_workspace(self):
        call = self.make_call("header-test", datetime(2026, 4, 2, tzinfo=timezone.utc))
        client = self.api_as(self.owner, self.workspace)
        for value in (str(self.workspace.pk), f"0{self.workspace.pk}", f" {self.workspace.pk} "):
            with self.subTest(value=value):
                response = client.get(
                    f"/api/calls/?avito_account_id={self.account.pk}",
                    HTTP_X_WORKSPACE_ID=value,
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual([row["id"] for row in response.data["results"]], [call.pk])

    def test_foreign_workspace_header_stays_forbidden_before_audio_request(self):
        call = self.make_call("header-test", datetime(2026, 4, 2, tzinfo=timezone.utc))
        client = self.api_as(self.owner, self.workspace)
        urls = (
            f"/api/calls/?avito_account_id={self.account.pk}",
            f"/api/calls/sync-status/?avito_account_id={self.account.pk}",
            f"/api/calls/{call.pk}/audio/",
        )
        with patch("calls.api_views.open_call_audio", side_effect=AudioUnavailable) as audio:
            for url in urls:
                with self.subTest(url=url):
                    response = client.get(url, HTTP_X_WORKSPACE_ID=str(self.other_workspace.pk))
                    self.assertEqual(response.status_code, 403)
            audio.assert_not_called()

    def test_largest_valid_workspace_id_is_forbidden_instead_of_invalid(self):
        client = self.api_as(self.owner, self.workspace)
        response = client.get(
            f"/api/calls/?avito_account_id={self.account.pk}",
            HTTP_X_WORKSPACE_ID="9223372036854775807",
        )
        self.assertEqual(response.status_code, 403)

    def test_missing_workspace_header_keeps_single_membership_fallback(self):
        call = self.make_call("header-test", datetime(2026, 4, 2, tzinfo=timezone.utc))
        client = APIClient()
        client.force_authenticate(user=self.owner)
        response = client.get(f"/api/calls/?avito_account_id={self.account.pk}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.data["results"]], [call.pk])


class AudioBody(BytesIO):
    def __init__(self, content):
        super().__init__(content)
        self.bytes_read = 0
        self.read_in_event_loop = False

    def read(self, size=-1):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            self.read_in_event_loop = True
        chunk = super().read(size)
        self.bytes_read += len(chunk)
        return chunk

    def release_conn(self):
        self.close()


class CallAudioStreamingTests(SimpleTestCase):
    def setUp(self):
        isolate_calls_audio_cache(self)

    def make_response(self, upstream=None):
        if upstream is None:
            upstream = Response()
            upstream.status_code = 200
            upstream.headers['Content-Type'] = 'audio/mpeg'
            upstream.headers['Content-Length'] = '131072'
            upstream.raw = AudioBody(b'a' * 65536 + b'b' * 65536)
        body = upstream.raw
        call = SimpleNamespace(
            external_id='123',
            avito_account=SimpleNamespace(oauth_tokens=object()),
        )
        request = APIRequestFactory().get('/api/calls/1/audio/')
        force_authenticate(request, user=User(pk=1))
        with (
            patch('calls.api_views.get_request_workspace', return_value=object()),
            patch('calls.api_views.get_object_or_404', return_value=call),
            patch('calls.api_views.open_call_audio', return_value=upstream),
        ):
            response = CallAudioView.as_view()(request, pk=1)
        self.addCleanup(upstream.close)
        return response, body

    def test_audio_response_preserves_upstream_content_type(self):
        for content_type in (
                'audio/mpeg', 'audio/ogg', 'audio/ogg; codecs=opus',
                'audio/wav', 'audio/mp4',
        ):
            with self.subTest(content_type=content_type):
                upstream = Response()
                upstream.status_code = 200
                upstream.headers.update({
                    'Content-Type': content_type,
                    'Content-Length': '5',
                })
                upstream.raw = AudioBody(b'audio')
                response, body = self.make_response(upstream)
                try:
                    self.assertEqual(response['Content-Type'], content_type)
                    self.assertEqual(response['Content-Length'], '5')
                    self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
                    self.assertEqual(response['Cache-Control'], 'private, no-store')
                finally:
                    response.close()
                self.assertTrue(body.closed)

    def test_open_audio_rejects_missing_or_non_audio_content_type(self):
        for content_type in (None, 'application/json', 'text/html'):
            with self.subTest(content_type=content_type):
                upstream = Response()
                upstream.status_code = 200
                if content_type is not None:
                    upstream.headers['Content-Type'] = content_type
                body = AudioBody(b'not audio')
                upstream.raw = body
                self.addCleanup(upstream.close)
                with patch('calls.services.AvitoApiClient') as client_class:
                    client_class.return_value.base_url = 'https://api.avito.ru'
                    client_class.return_value._send_request.return_value = upstream
                    with self.assertRaisesMessage(AvitoApiError, 'не аудиофайл'):
                        open_call_audio(SimpleNamespace(access_token='test-token'), '123')
                self.assertTrue(body.closed)

    async def test_gzip_audio_omits_compressed_length_and_delivers_decoded_body(self):
        audio = b'a' * 65536 + b'b' * 65536
        compressed = gzip.compress(audio)
        upstream = Response()
        upstream.status_code = 200
        upstream.headers.update({
            'Content-Type': 'audio/mpeg',
            'Content-Encoding': 'gzip',
            'Content-Length': str(len(compressed)),
        })
        upstream.raw = HTTPResponse(
            body=AudioBody(compressed),
            headers=upstream.headers,
            preload_content=False,
        )
        response, body = self.make_response(upstream)
        try:
            delivered = b''.join([chunk async for chunk in response])
            self.assertEqual(delivered, audio)
            self.assertNotEqual(len(delivered), len(compressed))
            self.assertNotIn('Content-Length', response.headers)
            self.assertNotIn('Content-Encoding', response.headers)
        finally:
            await sync_to_async(response.close)()
        self.assertTrue(body.closed)

    def test_identity_encoding_preserves_original_length(self):
        for encoding in ('identity', 'Identity', ' identity '):
            with self.subTest(encoding=encoding):
                upstream = Response()
                upstream.status_code = 200
                upstream.headers.update({
                    'Content-Type': 'audio/mpeg',
                    'Content-Encoding': encoding,
                    'Content-Length': '131072',
                })
                upstream.raw = AudioBody(b'a' * 131072)
                response, _ = self.make_response(upstream)
                try:
                    self.assertEqual(response['Content-Length'], '131072')
                finally:
                    response.close()

    def test_missing_or_invalid_audio_length_is_not_forwarded(self):
        for length in (None, '', 'invalid', '-1'):
            with self.subTest(length=length):
                upstream = Response()
                upstream.status_code = 200
                upstream.headers['Content-Type'] = 'audio/mpeg'
                if length is not None:
                    upstream.headers['Content-Length'] = length
                upstream.raw = AudioBody(b'a')
                response, _ = self.make_response(upstream)
                try:
                    self.assertNotIn('Content-Length', response.headers)
                finally:
                    response.close()

    async def test_asgi_delivers_first_chunk_before_reading_remaining_audio(self):
        response, body = self.make_response()
        stream = aiter(response)
        try:
            first = await anext(stream)
            self.assertEqual(first, b'a' * 65536)
            self.assertEqual(body.bytes_read, 65536)
            self.assertFalse(body.read_in_event_loop)
        finally:
            await stream.aclose()
            await sync_to_async(response.close)()

    def test_close_before_iteration_releases_upstream(self):
        response, body = self.make_response()
        response.close()
        self.assertTrue(body.closed)
        self.assertEqual(body.bytes_read, 0)

    async def test_asgi_delivers_complete_audio_and_closes_upstream(self):
        response, body = self.make_response()
        try:
            chunks = [chunk async for chunk in response]
            self.assertEqual(b''.join(chunks), b'a' * 65536 + b'b' * 65536)
            self.assertTrue(body.closed)
            self.assertEqual(response['Content-Length'], '131072')
            self.assertEqual(response['Cache-Control'], 'private, no-store')
        finally:
            await sync_to_async(response.close)()

    async def test_close_after_first_chunk_does_not_read_remaining_audio(self):
        response, body = self.make_response()
        stream = aiter(response)
        try:
            await anext(stream)
        finally:
            await stream.aclose()
            await sync_to_async(response.close)()
        self.assertTrue(body.closed)
        self.assertEqual(body.bytes_read, 65536)


class HistoryClassificationTransactionTests(TransactionTestCase):
    def test_failed_batch_keeps_prior_batch_and_retry_finishes_history(self):
        owner = User.objects.create_user("calls-history@example.com")
        workspace = Workspace.objects.create(
            name="Calls history", slug="calls-history", owner=owner,
        )
        account = AvitoAccount.objects.create(workspace=workspace, name="Main")
        state = CallSyncState.objects.create(
            avito_account=account, backfill_complete=True, lease_token="lease",
        )
        start = datetime(2026, 4, 1, tzinfo=timezone.utc)
        calls = [
            Call(
                workspace=workspace,
                avito_account=account,
                external_id=str(index),
                occurred_at=start + timedelta(seconds=index),
                buyer_phone=f"+{79990000000 + index}",
            )
            for index in range(1002)
        ]
        calls[500].buyer_phone = calls[0].buyer_phone
        calls[-1].buyer_phone = "invalid"
        Call.objects.bulk_create(calls)

        heartbeats = 0

        def interrupt_after_first_batch():
            nonlocal heartbeats
            heartbeats += 1
            if heartbeats == 2:
                raise RuntimeError("interrupted")

        with self.assertRaisesMessage(RuntimeError, "interrupted"):
            classify_account_history(account, state, "lease", interrupt_after_first_batch)

        completed = Call.objects.filter(avito_account=account).exclude(normalized_phone="")
        self.assertGreater(completed.count(), 0)
        self.assertLess(completed.count(), len(calls))
        self.assertFalse(
            CallSyncState.objects.get(pk=state.pk).classification_complete,
        )

        classify_account_history(account, state, "lease", lambda: None)

        self.assertEqual(
            Call.objects.get(avito_account=account, external_id="0").call_type,
            Call.Type.NEW,
        )
        self.assertEqual(
            Call.objects.get(avito_account=account, external_id="500").call_type,
            Call.Type.REPEAT,
        )
        invalid = Call.objects.get(avito_account=account, external_id="1001")
        self.assertEqual(invalid.normalized_phone, "")
        self.assertIsNone(invalid.call_type)
        self.assertTrue(
            CallSyncState.objects.get(pk=state.pk).classification_complete,
        )


class IncrementalClassificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        owner = User.objects.create_user("calls-incremental@example.com")
        cls.workspace = Workspace.objects.create(
            name="Calls incremental", slug="calls-incremental", owner=owner,
        )
        cls.account = AvitoAccount.objects.create(
            workspace=cls.workspace, name="Main",
        )

    def make_call(self, external_id, when, phone, call_type):
        return Call.objects.create(
            workspace=self.workspace,
            avito_account=self.account,
            external_id=str(external_id),
            occurred_at=when,
            buyer_phone=f"+{phone}",
            normalized_phone=phone,
            call_type=call_type,
        )

    def row(self, external_id, when, phone):
        return {
            "callId": external_id,
            "callTime": when.isoformat(),
            "buyerPhone": f"+{phone}",
            "talkDuration": 60,
            "waitingDuration": 5,
        }

    def fetch(self, rows):
        fetch_call_window(
            self.account,
            None,
            datetime(2026, 4, 1, tzinfo=timezone.utc),
            datetime(2026, 4, 4, tzinfo=timezone.utc),
            FakeCallsClient(rows),
            classify=True,
        )

    @patch("calls.services.PAGE_SIZE", 2)
    def test_new_calls_across_pages_do_not_read_entire_phone_history(self):
        first_at = datetime(2026, 4, 2, tzinfo=timezone.utc)
        phone = "70000000001"
        Call.objects.bulk_create([
            Call(
                workspace=self.workspace,
                avito_account=self.account,
                external_id=str(index),
                occurred_at=first_at + timedelta(minutes=index),
                buyer_phone=f"+{phone}",
                normalized_phone=phone,
                call_type=Call.Type.NEW if index == 0 else Call.Type.REPEAT,
            )
            for index in range(30)
        ])
        rows = [
            self.row(100 + index, first_at + timedelta(hours=1, minutes=index), phone)
            for index in range(3)
        ]

        with CaptureQueriesContext(connection) as captured:
            self.fetch(rows)

        self.assertEqual(
            list(Call.objects.filter(external_id__in=["100", "101", "102"])
                 .order_by("external_id").values_list("call_type", flat=True)),
            [Call.Type.REPEAT] * 3,
        )
        phone_reads = [
            query["sql"] for query in captured
            if query["sql"].startswith(("SELECT ", "DECLARE "))
               and (
                       '"calls_call"."normalized_phone" IN ' in query["sql"]
                       or '"calls_call"."normalized_phone" = ' in query["sql"]
               )
        ]
        self.assertTrue(phone_reads, "Ожидалось чтение первой записи номера")
        self.assertTrue(
            all(" LIMIT " in sql for sql in phone_reads),
            f"Найдены неограниченные чтения истории номера: {phone_reads}",
        )

    def test_new_earlier_call_demotes_previous_first_with_equal_time(self):
        at = datetime(2026, 4, 2, 12, tzinfo=timezone.utc)
        phone = "70000000001"
        previous_first = self.make_call("20", at, phone, Call.Type.NEW)
        self.make_call("30", at + timedelta(minutes=1), phone, Call.Type.REPEAT)

        self.fetch([self.row(10, at, phone)])

        previous_first.refresh_from_db()
        self.assertEqual(previous_first.call_type, Call.Type.REPEAT)
        self.assertEqual(Call.objects.get(external_id="10").call_type, Call.Type.NEW)
        self.assertEqual(Call.objects.get(external_id="30").call_type, Call.Type.REPEAT)

    def test_corrected_first_call_reclassifies_old_and_new_phones(self):
        at = datetime(2026, 4, 2, 12, tzinfo=timezone.utc)
        old_phone = "70000000001"
        new_phone = "70000000002"
        moved = self.make_call("10", at, old_phone, Call.Type.NEW)
        old_second = self.make_call(
            "11", at + timedelta(minutes=1), old_phone, Call.Type.REPEAT,
        )
        new_phone_first = self.make_call(
            "20", at + timedelta(minutes=2), new_phone, Call.Type.NEW,
        )

        self.fetch([self.row(10, at, new_phone)])

        moved.refresh_from_db()
        old_second.refresh_from_db()
        new_phone_first.refresh_from_db()
        self.assertEqual(moved.normalized_phone, new_phone)
        self.assertEqual(moved.call_type, Call.Type.NEW)
        self.assertEqual(old_second.call_type, Call.Type.NEW)
        self.assertEqual(new_phone_first.call_type, Call.Type.REPEAT)


class CallSyncQueryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        owner = User.objects.create_user('calls-query-tests@example.com')
        cls.workspace = Workspace.objects.create(
            name='Calls query tests', slug='calls-query-tests', owner=owner,
        )
        cls.account = AvitoAccount.objects.create(
            workspace=cls.workspace, name='Main',
        )
        cls.listing = AvitoListing.objects.create(
            workspace=cls.workspace, avito_account=cls.account,
            avito_id='777', title='Main listing',
        )

    def rows(self, count):
        return [
            {
                'callId': index,
                'callTime': '2026-04-02T12:00:00Z',
                'buyerPhone': f'+{79990000000 + index}',
                'talkDuration': 60,
                'waitingDuration': 5,
                'isMissed': False,
                'itemId': '777',
            }
            for index in range(count)
        ]

    def seed(self, rows):
        Call.objects.bulk_create([
            Call(
                workspace=self.workspace, avito_account=self.account,
                external_id=str(row['callId']),
                occurred_at=datetime(2026, 4, 2, 12, tzinfo=timezone.utc),
                buyer_phone=row['buyerPhone'],
                normalized_phone=row['buyerPhone'][1:],
                talk_duration=60, waiting_duration=5, is_missed=False,
                avito_item_id='777', listing=self.listing, call_type=Call.Type.NEW,
            )
            for row in rows
        ])

    def fetch(self, rows, *, classify=True):
        fetch_call_window(
            self.account, None,
            datetime(2026, 4, 1, tzinfo=timezone.utc),
            datetime(2026, 4, 3, tzinfo=timezone.utc),
            FakeCallsClient(rows), classify=classify,
        )

    def test_unchanged_page_does_not_write_or_change_updated_at(self):
        rows = self.rows(100)
        self.seed(rows)
        before = dict(Call.objects.values_list('pk', 'updated_at'))
        for classify in (False, True):
            with self.subTest(classify=classify):
                with CaptureQueriesContext(connection) as captured:
                    self.fetch(rows, classify=classify)
                writes = [
                    query['sql'] for query in captured
                    if query['sql'].startswith(('UPDATE ', 'INSERT ', 'DELETE '))
                ]
                self.assertEqual(len(writes), 0)
                self.assertEqual(
                    dict(Call.objects.values_list('pk', 'updated_at')), before,
                )

    def test_page_reads_calls_and_listings_in_batches(self):
        rows = self.rows(100)
        self.seed(rows)
        with CaptureQueriesContext(connection) as captured:
            self.fetch(rows)
        selects = [query for query in captured if query['sql'].startswith('SELECT ')]
        self.assertLessEqual(len(selects), 2)

    def test_mixed_page_only_writes_changed_and_new_calls(self):
        rows = self.rows(3)
        self.seed(rows[:2])
        before = Call.objects.get(external_id='1').updated_at
        rows[0]['talkDuration'] = 75
        with CaptureQueriesContext(connection) as captured:
            self.fetch(rows, classify=False)
        updates = [query for query in captured if query['sql'].startswith('UPDATE ')]
        inserts = [query for query in captured if query['sql'].startswith('INSERT ')]
        self.assertEqual(len(updates), 1)
        self.assertEqual(len(inserts), 1)
        changed = Call.objects.get(external_id='0')
        self.assertEqual(changed.talk_duration, 75)
        self.assertEqual(changed.call_type, Call.Type.NEW)
        self.assertEqual(Call.objects.get(external_id='1').updated_at, before)
        self.assertEqual(Call.objects.get(external_id='2').listing_id, self.listing.pk)

    def test_missing_optional_fields_preserve_saved_values_without_writes(self):
        rows = self.rows(1)
        self.seed(rows)
        rows[0].pop('itemId')
        rows[0].pop('isMissed')
        with CaptureQueriesContext(connection) as captured:
            self.fetch(rows)
        call = Call.objects.get(external_id='0')
        self.assertEqual(call.listing_id, self.listing.pk)
        self.assertEqual(call.avito_item_id, '777')
        self.assertIs(call.is_missed, False)
        self.assertFalse(any(query['sql'].startswith('UPDATE ') for query in captured))

    def test_late_listing_is_attached_only_from_the_same_workspace_and_account(self):
        rows = self.rows(1)
        self.seed(rows)
        Call.objects.update(avito_item_id='888', listing=None)
        rows[0]['itemId'] = '888'
        other_account = AvitoAccount.objects.create(
            workspace=self.workspace, name='Other account',
        )
        AvitoListing.objects.create(
            workspace=self.workspace, avito_account=other_account, avito_id='888',
        )
        other_workspace = Workspace.objects.create(
            name='Other workspace', slug='calls-query-other', owner=self.workspace.owner,
        )
        AvitoListing.objects.create(
            workspace=other_workspace, avito_account=self.account, avito_id='888',
        )
        self.fetch(rows)
        self.assertIsNone(Call.objects.get(external_id='0').listing_id)

        listing = AvitoListing.objects.create(
            workspace=self.workspace, avito_account=self.account, avito_id='888',
        )
        self.fetch(rows)
        self.assertEqual(Call.objects.get(external_id='0').listing_id, listing.pk)

    def test_duplicate_call_in_page_uses_the_last_values(self):
        row = self.rows(1)[0]
        self.seed([row])
        self.fetch([{**row, 'talkDuration': 90}, row], classify=False)
        self.assertEqual(Call.objects.count(), 1)
        self.assertEqual(Call.objects.get(external_id='0').talk_duration, 60)

    def test_invalid_row_preserves_valid_changes_from_the_same_page(self):
        rows = self.rows(2)
        self.seed(rows)
        rows[0]['talkDuration'] = 75
        rows[1]['talkDuration'] = -1
        self.fetch(rows)
        self.assertEqual(Call.objects.get(external_id='0').talk_duration, 75)
        self.assertEqual(Call.objects.get(external_id='1').talk_duration, 60)


class InvalidCallRowsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        owner = User.objects.create_user("invalid-calls@example.com")
        workspace = Workspace.objects.create(
            name="Invalid calls", slug="invalid-calls", owner=owner,
        )
        cls.account = AvitoAccount.objects.create(workspace=workspace, name="Main")
        AvitoOAuthToken.objects.create(
            workspace=workspace, avito_account=cls.account,
            auth_type=AvitoOAuthToken.AuthType.CLIENT_CREDENTIALS,
            access_token="test-token",
        )
        cls.now = datetime(2026, 4, 3, tzinfo=timezone.utc)

    def row(self, call_id, **changes):
        return {
            "callId": call_id,
            "callTime": "2026-04-02T12:00:00Z",
            "buyerPhone": "+79991234567",
            "talkDuration": 60,
            "waitingDuration": 5,
            **changes,
        }

    def fetch(self, rows):
        client = Mock()
        client.request.return_value = {"calls": rows}
        return fetch_call_window(
            self.account, self.account.oauth_tokens,
            self.now - timedelta(days=2), self.now, client,
        )

    def state(self):
        return CallSyncState.objects.create(
            avito_account=self.account,
            last_synced_at=self.now - timedelta(hours=1),
            backfill_complete=True,
            classification_complete=True,
        )

    def test_invalid_row_does_not_discard_valid_neighbors(self):
        missing_time = self.row(99)
        missing_time.pop("callTime")
        invalid_rows = [
            None,
            self.row(None),
            self.row(True),
            self.row("invalid"),
            self.row("1" * 101),
            missing_time,
            self.row(99, callTime="2026-04-02T12:00:00"),
            self.row(99, buyerPhone="9" * 65),
            self.row(99, buyerPhone=79991234567),
            self.row(99, itemId="1" * 101),
            self.row(99, talkDuration=-1),
            self.row(99, waitingDuration=2 ** 31),
        ]
        for invalid in invalid_rows:
            with self.subTest(invalid=invalid):
                with self.assertLogs("calls.services", level="WARNING") as logs:
                    skipped = self.fetch([self.row(1), invalid, self.row(2)])
                self.assertEqual(skipped, 1)
                self.assertEqual(
                    set(Call.objects.values_list("external_id", flat=True)),
                    {"1", "2"},
                )
                self.assertNotIn("+79991234567", "\n".join(logs.output))

    def test_non_ascii_call_ids_are_rejected(self):
        for call_id in ("²", "١٢٣", "１２３", "123²", "123١"):
            with self.subTest(call_id=call_id):
                with self.assertRaisesMessage(AvitoApiError, "Некорректный callId."):
                    upsert_call(self.account, self.row(call_id))

    def test_non_ascii_call_ids_are_skipped_without_losing_valid_neighbors(self):
        invalid_ids = ("²", "١٢٣", "１２３", "123²", "123١")
        rows = [
            self.row(1),
            *(self.row(call_id) for call_id in invalid_ids),
            self.row(2),
        ]
        with self.assertLogs("calls.services", level="WARNING") as logs:
            skipped = self.fetch(rows)
        self.assertEqual(skipped, len(invalid_ids))
        self.assertEqual(len(logs.records), len(invalid_ids))
        self.assertEqual(
            set(Call.objects.values_list("external_id", flat=True)),
            {"1", "2"},
        )

    def test_ascii_call_ids_keep_their_original_representation(self):
        for call_id in (0, "0", 123, "123", "000123", "9" * 100):
            with self.subTest(call_id=call_id):
                call = upsert_call(self.account, self.row(call_id))
                self.assertEqual(call.external_id, str(call_id))
                self.assertTrue(Call.objects.filter(
                    avito_account=self.account,
                    external_id=str(call_id),
                ).exists())

    def test_invalid_full_page_does_not_stop_pagination(self):
        client = Mock()
        client.request.side_effect = [
            {"calls": [self.row(98, talkDuration=-1), self.row(99, talkDuration=-1)]},
            {"calls": [self.row(1)]},
        ]
        with patch("calls.services.PAGE_SIZE", 2):
            skipped = fetch_call_window(
                self.account, self.account.oauth_tokens,
                self.now - timedelta(days=2), self.now, client,
            )
        self.assertEqual(skipped, 2)
        self.assertEqual(client.request.call_count, 2)
        self.assertTrue(Call.objects.filter(external_id="1").exists())

    def test_database_failure_still_rolls_back_the_page(self):
        upsert_call(self.account, self.row(1))
        upsert_call(self.account, self.row(2))
        save = Call.objects.update_or_create

        def fail_second(**kwargs):
            if kwargs["external_id"] == "2":
                raise DataError("simulated database failure")
            return save(**kwargs)

        with patch("calls.services.Call.objects.update_or_create", side_effect=fail_second):
            with self.assertRaises(DataError):
                self.fetch([
                    self.row(1, talkDuration=75),
                    self.row(2, talkDuration=76),
                ])
        self.assertEqual(Call.objects.get(external_id="1").talk_duration, 60)

    def test_invalid_envelope_does_not_advance_cursor(self):
        state = self.state()
        original_cursor = state.last_synced_at
        client = Mock()
        client.request.return_value = {"calls": None}
        with self.assertRaises(AvitoApiError):
            sync_calls_for_account(self.account.pk, client=client, now=self.now)
        state.refresh_from_db()
        self.assertEqual(state.last_synced_at, original_cursor)
        self.assertIsNone(state.lease_until)

    def test_incomplete_history_warning_survives_a_successful_next_sync(self):
        state = self.state()
        client = Mock()
        client.request.return_value = {"calls": [
            self.row(1), self.row(99, buyerPhone="9" * 65),
        ]}
        sync_calls_for_account(self.account.pk, client=client, now=self.now)
        state.refresh_from_db()
        self.assertEqual(state.last_synced_at, self.now)
        self.assertTrue(state.has_invalid_calls)
        self.assertIn("неполной", state.last_error)

        client.request.return_value = {"calls": [self.row(1)]}
        next_now = self.now + timedelta(hours=1)
        sync_calls_for_account(self.account.pk, client=client, now=next_now)
        state.refresh_from_db()
        self.assertEqual(state.last_synced_at, next_now)
        self.assertTrue(state.has_invalid_calls)
        self.assertIn("неполной", state.last_error)

    def test_oversized_values_are_validation_errors_before_database_writes(self):
        for row in (
                self.row("1" * 101),
                self.row(1, buyerPhone="9" * 65),
                self.row(1, itemId="1" * 101),
                self.row(1, talkDuration=2 ** 31),
        ):
            with self.subTest(row=row), self.assertNumQueries(0):
                with self.assertRaises(AvitoApiError):
                    upsert_call(self.account, row)

    def test_values_at_database_boundaries_are_preserved(self):
        call = upsert_call(self.account, self.row(
            "1" * 100, buyerPhone="9" * 64,
            itemId="2" * 100, talkDuration=2 ** 31 - 1,
        ))
        self.assertEqual(call.external_id, "1" * 100)
        self.assertEqual(call.buyer_phone, "9" * 64)
        self.assertEqual(call.avito_item_id, "2" * 100)
        self.assertEqual(call.talk_duration, 2 ** 31 - 1)


class CallsApiAuthorizationTests(SimpleTestCase):
    def make_api_client(self, statuses):
        from avitotask.services.avito_api import AvitoApiClient

        responses = []
        for status in statuses:
            response = Response()
            response.status_code = status
            response._content = b'{"result":"ok"}'
            responses.append(response)
        session = Mock()
        session.request.side_effect = responses
        with self.settings(
                AVITO_API_MIN_REQUEST_INTERVAL_SECONDS=0,
                AVITO_API_MAX_RETRIES=0,
        ):
            return AvitoApiClient(session=session)

    def test_forbidden_response_does_not_refresh_token_or_repeat_request(self):
        client = self.make_api_client([403, 403])
        token = SimpleNamespace(access_token="test-token")
        with patch.object(client, "refresh_access_token") as refresh:
            with self.assertRaises(AvitoApiError) as caught:
                client.request("POST", "/calltracking/v1/getCalls/", token=token)
        self.assertEqual(caught.exception.status_code, 403)
        refresh.assert_not_called()
        self.assertEqual(client.session.request.call_count, 1)

    def test_unauthorized_response_refreshes_token_once_and_uses_new_token(self):
        client = self.make_api_client([401, 200])
        token = SimpleNamespace(access_token="old-test-token")

        def update_token(current_token):
            current_token.access_token = "new-test-token"

        with patch.object(client, "refresh_access_token", side_effect=update_token) as refresh:
            result = client.request("POST", "/calltracking/v1/getCalls/", token=token)
        self.assertEqual(result, {"result": "ok"})
        refresh.assert_called_once_with(token)
        self.assertEqual(client.session.request.call_count, 2)
        sent_headers = [
            call.kwargs["headers"]["Authorization"]
            for call in client.session.request.call_args_list
        ]
        self.assertEqual(sent_headers, [
            "Bearer old-test-token", "Bearer new-test-token",
        ])

    def test_second_unauthorized_response_stops_without_another_refresh(self):
        client = self.make_api_client([401, 401])
        token = SimpleNamespace(access_token="test-token")
        with patch.object(client, "refresh_access_token") as refresh:
            with self.assertRaises(AvitoApiError) as caught:
                client.request("POST", "/calltracking/v1/getCalls/", token=token)
        self.assertEqual(caught.exception.status_code, 401)
        refresh.assert_called_once_with(token)
        self.assertEqual(client.session.request.call_count, 2)

    def test_forbidden_after_token_refresh_is_returned_without_another_refresh(self):
        client = self.make_api_client([401, 403])
        token = SimpleNamespace(access_token="test-token")
        with patch.object(client, "refresh_access_token") as refresh:
            with self.assertRaises(AvitoApiError) as caught:
                client.request("POST", "/calltracking/v1/getCalls/", token=token)
        self.assertEqual(caught.exception.status_code, 403)
        refresh.assert_called_once_with(token)
        self.assertEqual(client.session.request.call_count, 2)


class CallsRetryAfterTests(SimpleTestCase):
    def response(self, status, retry_after=None):
        response = Response()
        response.status_code = status
        response._content = b'{"access_token":"test-token","expires_in":3600,"token_type":"Bearer"}'
        if retry_after is not None:
            response.headers["Retry-After"] = retry_after
        return response

    def request(self, client, endpoint):
        if endpoint == "token":
            return client.request_token({"grant_type": "client_credentials"})
        return client.request("GET", "/calltracking/test")

    def make_api_client(self, responses, *, default_delay=60):
        from avitotask.services.avito_api import AvitoApiClient

        session = Mock()
        session.request.side_effect = responses
        with self.settings(
                AVITO_API_MIN_REQUEST_INTERVAL_SECONDS=0,
                AVITO_API_MAX_RETRIES=1,
                AVITO_API_DEFAULT_RETRY_AFTER_SECONDS=default_delay,
                AVITO_API_MAX_RETRY_AFTER_SECONDS=60,
        ):
            return AvitoApiClient(session=session)

    def test_long_retry_after_fails_without_sleeping_or_sending_again(self):
        for endpoint in ("api", "token"):
            with self.subTest(endpoint=endpoint):
                client = self.make_api_client([self.response(429, "61"), self.response(200)])
                with patch("avitotask.services.avito_api.time.sleep") as sleep:
                    with self.assertRaises(AvitoApiError) as caught:
                        self.request(client, endpoint)
                self.assertEqual(caught.exception.status_code, 429)
                sleep.assert_not_called()
                self.assertEqual(client.session.request.call_count, 1)

    def test_retry_after_at_limit_is_honored(self):
        for endpoint in ("api", "token"):
            with self.subTest(endpoint=endpoint):
                client = self.make_api_client([self.response(429, "60"), self.response(200)])
                with patch("avitotask.services.avito_api.time.sleep") as sleep:
                    result = self.request(client, endpoint)
                self.assertEqual(result["access_token"], "test-token")
                sleep.assert_called_once_with(60)

    def test_missing_or_invalid_retry_after_uses_bounded_default(self):
        for endpoint in ("api", "token"):
            for value in (None, "invalid"):
                with self.subTest(endpoint=endpoint, value=value):
                    client = self.make_api_client(
                        [self.response(429, value), self.response(200)],
                        default_delay=30,
                    )
                    with patch("avitotask.services.avito_api.time.sleep") as sleep:
                        result = self.request(client, endpoint)
                    self.assertEqual(result["access_token"], "test-token")
                    sleep.assert_called_once_with(30)

    def test_default_delay_cannot_bypass_the_wait_limit(self):
        client = self.make_api_client([self.response(429), self.response(200)], default_delay=61)
        with patch("avitotask.services.avito_api.time.sleep") as sleep:
            with self.assertRaises(AvitoApiError) as caught:
                self.request(client, "api")
        self.assertEqual(caught.exception.status_code, 429)
        sleep.assert_not_called()


class CallsTaskResilienceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        owner = User.objects.create_user("calls-task-retries@example.com")
        workspace = Workspace.objects.create(
            name="Calls task retries", slug="calls-task-retries", owner=owner,
        )
        cls.account = AvitoAccount.objects.create(workspace=workspace, name="Main")
        AvitoOAuthToken.objects.create(
            workspace=workspace, avito_account=cls.account,
            access_token="test-token",
        )

    def run_task(self, retries=0):
        task = sync_calls_for_account_task
        task.push_request(
            id="calls-retry-test", args=(self.account.pk,), kwargs={},
            retries=retries, called_directly=False, is_eager=True,
        )
        try:
            return task.run(self.account.pk)
        finally:
            task.pop_request()

    def forbid_calls(self, now, status=403):
        state = CallSyncState.objects.create(
            avito_account=self.account,
            last_synced_at=now - timedelta(hours=1),
            backfill_complete=True,
            classification_complete=True,
        )
        client = Mock()
        client.request.side_effect = AvitoApiError(
            "upstream private details", status_code=status,
        )
        with (
            self.settings(AVITO_CALLS_FORBIDDEN_RETRY_HOURS=6),
            patch("calls.services.timezone.now", return_value=now),
            patch("calls.services.AvitoApiClient", return_value=client),
        ):
            with self.assertRaises(AvitoApiError) as caught:
                self.run_task()
        self.assertEqual(caught.exception.status_code, status)
        state.refresh_from_db()
        return state

    def test_forbidden_sync_records_pause_without_advancing_cursor(self):
        now = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)
        state = self.forbid_calls(now)
        self.assertEqual(
            getattr(state, "access_retry_at", None),
            now + timedelta(hours=6),
        )
        self.assertEqual(state.last_synced_at, now - timedelta(hours=1))
        self.assertIsNone(state.lease_until)
        self.assertEqual(state.lease_token, "")
        self.assertIsNone(state.phase)
        self.assertIn("403", state.last_error)
        self.assertNotIn("private details", state.last_error)

    def test_paused_sync_does_not_contact_avito_or_advance_cursor(self):
        now = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)
        state = self.forbid_calls(now)
        client = Mock()
        client.request.return_value = {"calls": []}
        for attempted_at in (
                now + timedelta(hours=1),
                now + timedelta(hours=6) - timedelta(seconds=1),
        ):
            with self.subTest(attempted_at=attempted_at):
                self.assertFalse(sync_calls_for_account(
                    self.account.pk, client=client, now=attempted_at,
                ))
                client.request.assert_not_called()
                state.refresh_from_db()
                self.assertEqual(state.last_synced_at, now - timedelta(hours=1))
                self.assertIn("403", state.last_error)
                self.assertIsNone(state.lease_until)

    def test_dispatch_skips_paused_account_and_keeps_account_without_state(self):
        now = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)
        self.forbid_calls(now)
        eligible = AvitoAccount.objects.create(
            workspace=self.account.workspace, name="Without sync state",
        )
        AvitoOAuthToken.objects.create(
            workspace=self.account.workspace, avito_account=eligible,
            access_token="test-eligible-token",
        )
        with (
            patch("django.utils.timezone.now", return_value=now + timedelta(hours=1)),
            patch("calls.tasks.sync_calls_for_account_task.delay") as enqueue,
        ):
            result = enqueue_calls_sync_task()
        enqueue.assert_called_once_with(eligible.pk)
        self.assertEqual(result, {"queued": 1, "failed": 0})

    def test_sync_resumes_and_clears_pause_at_exact_expiry(self):
        now = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)
        state = self.forbid_calls(now)
        retry_at = now + timedelta(hours=6)
        client = Mock()
        client.request.return_value = {"calls": []}
        self.assertFalse(sync_calls_for_account(
            self.account.pk, client=client, now=retry_at,
        ))
        self.assertEqual(client.request.call_count, 1)
        state.refresh_from_db()
        self.assertIsNone(getattr(state, "access_retry_at", None))
        self.assertEqual(state.last_synced_at, retry_at)
        self.assertEqual(state.last_error, "")

    def test_dispatch_resumes_paused_account_at_exact_expiry(self):
        now = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)
        self.forbid_calls(now)
        with (
            patch("django.utils.timezone.now", return_value=now + timedelta(hours=6)),
            patch("calls.tasks.sync_calls_for_account_task.delay") as enqueue,
        ):
            result = enqueue_calls_sync_task()
        enqueue.assert_called_once_with(self.account.pk)
        self.assertEqual(result, {"queued": 1, "failed": 0})

    def test_unauthorized_error_does_not_create_forbidden_pause(self):
        now = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)
        state = self.forbid_calls(now, status=401)
        self.assertIsNone(getattr(state, "access_retry_at", None))
        client = Mock()
        client.request.return_value = {"calls": []}
        sync_calls_for_account(
            self.account.pk, client=client, now=now + timedelta(hours=1),
        )
        self.assertEqual(client.request.call_count, 1)

    def test_time_limits_allow_cleanup_before_lease_expires(self):
        task = sync_calls_for_account_task
        self.assertIsInstance(task.soft_time_limit, int)
        self.assertIsInstance(task.time_limit, int)
        self.assertGreater(task.soft_time_limit, 0)
        self.assertGreater(task.time_limit, task.soft_time_limit)
        self.assertLess(task.time_limit, LEASE.total_seconds())

    def test_server_error_retries_with_increasing_delay(self):
        state = CallSyncState.objects.create(avito_account=self.account)
        for attempt, expected_delay in ((0, 60), (1, 120), (2, 240)):
            with self.subTest(attempt=attempt):
                error = AvitoApiError("upstream failure", status_code=503)
                with patch("calls.tasks.sync_calls_for_account", side_effect=error):
                    with self.assertRaises(Retry) as caught:
                        self.run_task(attempt)
                self.assertEqual(caught.exception.when, expected_delay)
                self.assertIs(caught.exception.exc, error)
                state.refresh_from_db()
                self.assertIn("503", state.last_error)

    def test_network_timeout_and_connection_error_are_retried(self):
        for cause in (requests.Timeout("timeout"), requests.ConnectionError("connection")):
            with self.subTest(cause=type(cause).__name__):
                error = AvitoApiError("network failure")
                error.__cause__ = cause
                with patch("calls.tasks.sync_calls_for_account", side_effect=error):
                    with self.assertRaises(Retry) as caught:
                        self.run_task()
                self.assertEqual(caught.exception.when, 60)
                self.assertIs(caught.exception.exc, error)

    def test_fourth_failure_stops_retrying(self):
        error = AvitoApiError("upstream failure", status_code=503)
        with patch("calls.tasks.sync_calls_for_account", side_effect=error):
            with self.assertRaises(AvitoApiError) as caught:
                self.run_task(retries=3)
        self.assertIs(caught.exception, error)

    def test_client_errors_and_invalid_payload_are_not_retried_by_celery(self):
        for status in (None, 400, 401, 403, 404, 429):
            with self.subTest(status=status):
                error = AvitoApiError("permanent failure", status_code=status)
                with patch("calls.tasks.sync_calls_for_account", side_effect=error):
                    with self.assertRaises(AvitoApiError) as caught:
                        self.run_task()
                self.assertIs(caught.exception, error)

    def test_soft_timeout_releases_lease_and_records_timeout(self):
        state = CallSyncState.objects.create(avito_account=self.account)
        with patch("calls.services.fetch_call_window", side_effect=SoftTimeLimitExceeded):
            with self.assertRaises(SoftTimeLimitExceeded):
                self.run_task()
        state.refresh_from_db()
        self.assertIsNone(state.lease_until)
        self.assertEqual(state.lease_token, "")
        self.assertIsNone(state.phase)
        self.assertIn("время", state.last_error.lower())
