from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User, Workspace, WorkspaceMembership
from analytics.models import AvitoListingDailyStats, AvitoStatsSyncState
from analytics.selectors.avito_stats import build_avito_listing_stats_report
from analytics.services.avito_stats import (
    import_avito_listing_daily_stats_for_account,
    resolve_stats_sync_range,
)
from analytics.tasks import import_avito_account_daily_stats_task
from avitotask.models import AvitoAccount, AvitoListing, AvitoOAuthToken
from avitotask.services.avito_api import AvitoApiClient


class AnalyticsReportTests(TestCase):

    def test_listing_stats_api_requires_view_analytics_permission(self):
        viewer = User.objects.create_user(
            email="analytics-no-access@example.com",
            password="test",
        )
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=viewer,
            role=WorkspaceMembership.Role.VIEWER,
            status=WorkspaceMembership.Status.ACTIVE,
        )

        client = APIClient()
        client.force_authenticate(viewer)

        response = client.get(
            f"/api/analytics/avito-accounts/{self.avito_account.id}/listing-stats/",
            data={
                "date_from": "2026-05-01",
                "date_to": "2026-05-01",
            },
            HTTP_X_WORKSPACE_ID=str(self.workspace.id),
        )

        self.assertEqual(response.status_code, 200)

    def test_listing_stats_api_rejects_listing_from_another_avito_account(self):
        another_account = AvitoAccount.objects.create(
            workspace=self.workspace,
            name="Another analytics account",
            external_account_id="94235312",
        )
        another_listing = AvitoListing.objects.create(
            workspace=self.workspace,
            avito_account=another_account,
            avito_id="99999999",
            status="active",
            title="Another listing",
        )

        client = APIClient()
        client.force_authenticate(self.user)

        response = client.get(
            f"/api/analytics/avito-accounts/{self.avito_account.id}/listing-stats/",
            data={
                "date_from": "2026-05-01",
                "date_to": "2026-05-01",
                "listing_ids": str(another_listing.id),
            },
            HTTP_X_WORKSPACE_ID=str(self.workspace.id),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("listing_ids", response.data)

    def setUp(self):
        self.user = User.objects.create_user(
            email="analytics-owner@example.com",
            password="test",
        )
        self.workspace = Workspace.objects.create(
            name="Analytics workspace",
            slug="analytics-workspace",
            owner=self.user,
        )
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=self.user,
            role=WorkspaceMembership.Role.OWNER,
            status=WorkspaceMembership.Status.ACTIVE,
        )
        self.avito_account = AvitoAccount.objects.create(
            workspace=self.workspace,
            name="Analytics account",
            external_account_id="94235311",
        )
        self.listing = AvitoListing.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            avito_id="24122261",
            status="active",
            title="Analytics listing",
        )

    def test_report_calculates_totals_and_cost_per_contact(self):
        AvitoListingDailyStats.objects.create(
            workspace=self.workspace,
            listing=self.listing,
            date=date(2026, 5, 1),
            views=10,
            contacts=2,
            favorites=1,
            total_spend=Decimal("12.50"),
        )
        AvitoListingDailyStats.objects.create(
            workspace=self.workspace,
            listing=self.listing,
            date=date(2026, 5, 2),
            views=5,
            contacts=0,
            favorites=2,
            total_spend=None,
        )

        report = build_avito_listing_stats_report(
            workspace=self.workspace,
            avito_account=self.avito_account,
            date_from=date(2026, 5, 1),
            date_to=date(2026, 5, 2),
        )

        self.assertEqual(report["totals"]["views"], 15)
        self.assertEqual(report["totals"]["contacts"], 2)
        self.assertEqual(report["totals"]["favorites"], 3)
        self.assertEqual(report["totals"]["total_spend"], "12.50")
        self.assertEqual(report["totals"]["cost_per_contact"], "6.25")

        listing_report = report["listings"][0]
        self.assertEqual(listing_report["listing_id"], self.listing.id)
        self.assertEqual(listing_report["avito_id"], "24122261")
        self.assertEqual(listing_report["totals"]["cost_per_contact"], "6.25")
        self.assertEqual(listing_report["daily"][0]["cost_per_contact"], "6.25")
        self.assertIsNone(listing_report["daily"][1]["total_spend"])
        self.assertIsNone(listing_report["daily"][1]["cost_per_contact"])

    def test_import_daily_stats_api_queues_task(self):
        client = APIClient()
        client.force_authenticate(self.user)

        with patch("analytics.tasks.import_avito_account_daily_stats_task.delay") as delay:
            delay.return_value.id = "analytics-task-id"

            response = client.post(
                f"/api/analytics/avito-accounts/{self.avito_account.id}/import-daily-stats/",
                data={
                    "date_from": "2026-05-01",
                    "date_to": "2026-05-02",
                },
                format="json",
                HTTP_X_WORKSPACE_ID=str(self.workspace.id),
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["status"], "queued")
        self.assertEqual(response.data["task_id"], "analytics-task-id")
        sync_state = AvitoStatsSyncState.objects.get(
            avito_account=self.avito_account,
        )
        self.assertEqual(sync_state.status, AvitoStatsSyncState.Status.QUEUED)
        self.assertEqual(sync_state.requested_date_from, date(2026, 5, 1))
        self.assertEqual(sync_state.requested_date_to, date(2026, 5, 2))
        delay.assert_called_once_with(
            self.avito_account.id,
            "2026-05-01",
            "2026-05-02",
            None,
        )

    def test_import_daily_stats_api_validates_date_range(self):
        client = APIClient()
        client.force_authenticate(self.user)

        response = client.post(
            f"/api/analytics/avito-accounts/{self.avito_account.id}/import-daily-stats/",
            data={
                "date_from": "2026-05-03",
                "date_to": "2026-05-02",
            },
            format="json",
            HTTP_X_WORKSPACE_ID=str(self.workspace.id),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("date_to", response.data)

    def test_listing_stats_api_returns_summary_and_daily_rows(self):
        AvitoListingDailyStats.objects.create(
            workspace=self.workspace,
            listing=self.listing,
            date=date(2026, 5, 1),
            views=10,
            contacts=2,
            favorites=1,
            total_spend=Decimal("12.50"),
        )

        client = APIClient()
        client.force_authenticate(self.user)

        response = client.get(
            f"/api/analytics/avito-accounts/{self.avito_account.id}/listing-stats/",
            data={
                "date_from": "2026-05-01",
                "date_to": "2026-05-01",
            },
            HTTP_X_WORKSPACE_ID=str(self.workspace.id),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["totals"]["views"], 10)
        self.assertEqual(response.data["totals"]["contacts"], 2)
        self.assertEqual(response.data["totals"]["favorites"], 1)
        self.assertEqual(response.data["totals"]["total_spend"], "12.50")
        self.assertEqual(response.data["totals"]["cost_per_contact"], "6.25")
        self.assertEqual(response.data["listings"][0]["avito_id"], "24122261")

    def test_ads_api_returns_accumulated_stats_and_sync_state(self):
        AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.SUCCESS,
            coverage_from=date(2026, 5, 1),
            coverage_to=date(2026, 5, 2),
            last_successful_at=datetime(2026, 5, 3, 8, 0, tzinfo=dt_timezone.utc),
        )
        AvitoListingDailyStats.objects.create(
            workspace=self.workspace,
            listing=self.listing,
            date=date(2026, 5, 1),
            views=10,
            contacts=2,
        )
        AvitoListingDailyStats.objects.create(
            workspace=self.workspace,
            listing=self.listing,
            date=date(2026, 5, 2),
            views=5,
            contacts=1,
        )

        client = APIClient()
        client.force_authenticate(self.user)
        response = client.get(
            f"/api/avito/accounts/{self.avito_account.id}/ads/",
            HTTP_X_WORKSPACE_ID=str(self.workspace.id),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["stats_sync"]["status"], "success")
        self.assertEqual(response.data["stats_sync"]["coverage_from"], "2026-05-01")
        listing_row = next(
            item for item in response.data["results"]
            if item["avito_id"] == self.listing.avito_id
        )
        self.assertEqual(listing_row["avito_listing_id"], self.listing.id)
        self.assertEqual(listing_row["stats"]["status"], "ready")
        self.assertEqual(listing_row["stats"]["views"], 15)
        self.assertEqual(listing_row["stats"]["contacts"], 3)

    def test_ads_api_distinguishes_processing_from_confirmed_zero(self):
        client = APIClient()
        client.force_authenticate(self.user)

        response = client.get(
            f"/api/avito/accounts/{self.avito_account.id}/ads/",
            HTTP_X_WORKSPACE_ID=str(self.workspace.id),
        )
        listing_row = response.data["results"][0]
        self.assertEqual(response.data["stats_sync"]["status"], "not_started")
        self.assertEqual(listing_row["stats"]["status"], "processing")
        self.assertIsNone(listing_row["stats"]["views"])
        self.assertIsNone(listing_row["stats"]["contacts"])

        AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.SUCCESS,
            coverage_from=date(2026, 5, 1),
            coverage_to=date(2026, 5, 2),
            last_successful_at=datetime(2026, 5, 3, 8, 0, tzinfo=dt_timezone.utc),
        )
        response = client.get(
            f"/api/avito/accounts/{self.avito_account.id}/ads/",
            HTTP_X_WORKSPACE_ID=str(self.workspace.id),
        )
        listing_row = response.data["results"][0]
        self.assertEqual(listing_row["stats"]["status"], "ready")
        self.assertEqual(listing_row["stats"]["views"], 0)
        self.assertEqual(listing_row["stats"]["contacts"], 0)


class AvitoAnalyticsImportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="analytics-import-owner@example.com",
            password="test",
        )
        self.workspace = Workspace.objects.create(
            name="Analytics import workspace",
            slug="analytics-import-workspace",
            owner=self.user,
        )
        self.avito_account = AvitoAccount.objects.create(
            workspace=self.workspace,
            name="Analytics import account",
            external_account_id="94235311",
        )
        AvitoOAuthToken.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            access_token="analytics-import-access-token",
            refresh_token="analytics-import-refresh-token",
            scope="stats:read",
        )
        self.listing = AvitoListing.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            avito_id="24122261",
            status="active",
            title="Analytics import listing",
        )

    def test_import_daily_stats_saves_views_and_contacts_without_spending_request(self):
        class FakeResponse:
            status_code = 200
            text = "json"

            def __init__(self, payload):
                self.payload = payload

            def json(self):
                return self.payload

        class FakeSession:
            def __init__(self):
                self.urls = []

            def request(self, method, url, **kwargs):
                self.urls.append(url)
                if url.endswith("/stats/v1/accounts/94235311/items"):
                    return FakeResponse({
                        "result": {
                            "items": [
                                {
                                    "itemId": "24122261",
                                    "stats": [
                                        {
                                            "date": "2026-05-01",
                                            "uniqViews": 10,
                                            "uniqContacts": 2,
                                            "uniqFavorites": 1,
                                        },
                                    ],
                                },
                            ],
                        },
                    })

                return FakeResponse({})

        session = FakeSession()
        result = import_avito_listing_daily_stats_for_account(
            avito_account=self.avito_account,
            date_from=date(2026, 5, 1),
            date_to=date(2026, 5, 1),
            session=session,
        )

        stat = AvitoListingDailyStats.objects.get(
            listing=self.listing,
            date=date(2026, 5, 1),
        )

        self.assertEqual(result.total_days, 1)
        self.assertEqual(stat.views, 10)
        self.assertEqual(stat.contacts, 2)
        self.assertEqual(stat.favorites, 1)
        self.assertIsNone(stat.total_spend)
        self.assertEqual(len(session.urls), 1)
        self.assertTrue(session.urls[0].endswith("/stats/v1/accounts/94235311/items"))

    def test_sync_range_uses_full_backfill_then_two_day_overlap(self):
        sync_state = AvitoStatsSyncState(
            workspace=self.workspace,
            avito_account=self.avito_account,
        )
        self.assertEqual(
            resolve_stats_sync_range(
                sync_state=sync_state,
                today=date(2026, 7, 21),
            ),
            (date(2025, 7, 22), date(2026, 7, 21)),
        )

        sync_state.last_successful_at = datetime(
            2026, 7, 20, 8, 0, tzinfo=dt_timezone.utc,
        )
        self.assertEqual(
            resolve_stats_sync_range(
                sync_state=sync_state,
                today=date(2026, 7, 21),
            ),
            (date(2026, 7, 20), date(2026, 7, 21)),
        )

    def test_task_updates_sync_state_on_success_and_error(self):
        sync_state = AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.QUEUED,
            requested_date_from=date(2026, 5, 1),
            requested_date_to=date(2026, 5, 1),
        )

        with patch(
            "analytics.tasks.import_avito_listing_daily_stats_for_account",
            return_value=SimpleNamespace(
                total_listings=1,
                total_days=1,
                created_stats=1,
                updated_stats=0,
            ),
        ):
            result = import_avito_account_daily_stats_task(
                self.avito_account.id,
                "2026-05-01",
                "2026-05-01",
            )

        sync_state.refresh_from_db()
        self.assertEqual(result["status"], "success")
        self.assertEqual(sync_state.status, AvitoStatsSyncState.Status.SUCCESS)
        self.assertEqual(sync_state.coverage_from, date(2026, 5, 1))
        self.assertEqual(sync_state.coverage_to, date(2026, 5, 1))
        self.assertIsNotNone(sync_state.last_successful_at)

        sync_state.status = AvitoStatsSyncState.Status.QUEUED
        sync_state.save(update_fields=["status", "updated_at"])
        with patch(
            "analytics.tasks.import_avito_listing_daily_stats_for_account",
            side_effect=RuntimeError("Avito unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                import_avito_account_daily_stats_task(
                    self.avito_account.id,
                    "2026-05-01",
                    "2026-05-01",
                )

        sync_state.refresh_from_db()
        self.assertEqual(sync_state.status, AvitoStatsSyncState.Status.ERROR)
        self.assertIn("Avito unavailable", sync_state.error)

    def test_running_task_is_not_started_twice(self):
        AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.RUNNING,
            started_at=datetime.now(tz=dt_timezone.utc),
        )

        with patch(
            "analytics.tasks.import_avito_listing_daily_stats_for_account",
        ) as importer:
            result = import_avito_account_daily_stats_task(
                self.avito_account.id,
                "2026-05-01",
                "2026-05-01",
            )

        self.assertEqual(result["status"], "skipped")
        importer.assert_not_called()


class AvitoApiClientAnalyticsTests(TestCase):
    def test_get_item_analytics_sends_stats_v2_request(self):
        class FakeToken:
            access_token = "stats-access-token"

        class FakeResponse:
            status_code = 200
            text = "json"

            def json(self):
                return {"result": {"items": []}}

        class FakeSession:
            def __init__(self):
                self.calls = []

            def request(self, method, url, **kwargs):
                self.calls.append((method, url, kwargs))
                return FakeResponse()

        session = FakeSession()
        client = AvitoApiClient(session=session)

        payload = client.get_item_analytics(
            token=FakeToken(),
            user_id="94235311",
            item_ids=[24122261],
            date_from=date(2026, 5, 1),
            date_to=date(2026, 5, 2),
            metrics=["spending"],
        )

        self.assertEqual(payload, {"result": {"items": []}})
        self.assertEqual(session.calls[0][0], "POST")
        self.assertEqual(
            session.calls[0][1],
            "https://api.avito.ru/stats/v2/accounts/94235311/items",
        )
        self.assertEqual(
            session.calls[0][2]["json"],
            {
                "itemIds": [24122261],
                "dateFrom": "2026-05-01",
                "dateTo": "2026-05-02",
                "metrics": ["spending"],
                "grouping": "day",
            },
        )
        self.assertEqual(
            session.calls[0][2]["headers"]["Authorization"],
            "Bearer stats-access-token",
        )
