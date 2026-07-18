from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User, Workspace, WorkspaceMembership
from analytics.models import AvitoListingDailyStats
from analytics.selectors.avito_stats import build_avito_listing_stats_report
from analytics.services.avito_stats import import_avito_listing_daily_stats_for_account
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

        with patch("analytics.api_views.import_avito_account_daily_stats_task.delay") as delay:
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

    def test_import_daily_stats_saves_spending_as_total_spend_in_rubles(self):
        class FakeResponse:
            status_code = 200
            text = "json"

            def __init__(self, payload):
                self.payload = payload

            def json(self):
                return self.payload

        class FakeSession:
            def request(self, method, url, **kwargs):
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

                if url.endswith("/stats/v2/accounts/94235311/items"):
                    return FakeResponse({
                        "result": {
                            "items": [
                                {
                                    "itemId": "24122261",
                                    "stats": [
                                        {
                                            "date": "2026-05-01",
                                            "spending": 1250,
                                        },
                                    ],
                                },
                            ],
                        },
                    })

                return FakeResponse({})

        result = import_avito_listing_daily_stats_for_account(
            avito_account=self.avito_account,
            date_from=date(2026, 5, 1),
            date_to=date(2026, 5, 1),
            session=FakeSession(),
        )

        stat = AvitoListingDailyStats.objects.get(
            listing=self.listing,
            date=date(2026, 5, 1),
        )

        self.assertEqual(result.total_days, 1)
        self.assertEqual(stat.views, 10)
        self.assertEqual(stat.contacts, 2)
        self.assertEqual(stat.favorites, 1)
        self.assertEqual(stat.total_spend, Decimal("12.50"))
        self.assertEqual(stat.raw_metrics["spending"], 1250)


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
