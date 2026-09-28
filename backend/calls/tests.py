"""Contract tests for calls, using redacted Avito response shapes."""

import asyncio
from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

from asgiref.sync import sync_to_async
from django.db import connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone as django_timezone
from requests import Response
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate

from accounts.models import User, Workspace, WorkspaceMembership
from avitotask.models import AvitoAccount, AvitoListing, AvitoOAuthToken
from avitotask.services.avito_api import AvitoApiError
from calls.api_views import CallAudioView
from calls.models import Call, CallSyncState
from calls.services import (
    AudioUnavailable, fetch_call_window, open_call_audio,
    sync_calls_for_account, upsert_call, classify_account_history,
)
from calls.tasks import enqueue_calls_sync_task

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


class CallsMvpTests(TestCase):

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
    def make_response(self):
        body = AudioBody(b'a' * 65536 + b'b' * 65536)
        upstream = Response()
        upstream.status_code = 200
        upstream.headers['Content-Length'] = '131072'
        upstream.raw = body
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

    def test_invalid_row_rolls_back_changes_from_the_same_page(self):
        rows = self.rows(2)
        self.seed(rows)
        rows[0]['talkDuration'] = 75
        rows[1]['talkDuration'] = -1
        with self.assertRaises(AvitoApiError):
            self.fetch(rows)
        self.assertEqual(Call.objects.get(external_id='0').talk_duration, 60)
