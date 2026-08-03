from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from celery.exceptions import Retry
from django.apps import apps
from django.db import connection
from django.db.models.query import QuerySet
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from accounts.models import User, Workspace, WorkspaceMembership
from analytics.models import (
    AvitoListingDailyStats,
    AvitoListingStatsCoverage,
    AvitoStatsSyncState,
)
from analytics.selectors.avito_stats import (
    build_avito_ads_stats_payload,
    build_avito_listing_stats_report,
)
from analytics.services.avito_stats import (
    get_listings_for_stats,
    import_avito_listing_daily_stats_for_account,
    resolve_stats_sync_range,
)
from analytics.tasks import import_avito_account_daily_stats_task
from avitotask.models import AvitoAccount, AvitoListing, AvitoOAuthToken
from avitotask.services.avito_api import AvitoApiClient, AvitoApiError


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

    @patch(
        "django.utils.timezone.localdate",
        return_value=date(2026, 7, 30),
    )
    def test_listing_stats_api_accepts_only_bounded_completed_period(
            self,
            localdate,
    ):
        client = APIClient()
        client.force_authenticate(self.user)
        url = (
            "/api/analytics/avito-accounts/"
            f"{self.avito_account.id}/listing-stats/"
        )

        invalid_periods = (
            {
                "date_from": "2026-07-29",
                "date_to": "2026-07-30",
            },
            {
                "date_from": "2025-11-01",
                "date_to": "2026-07-29",
            },
        )

        for params in invalid_periods:
            with self.subTest(params=params):
                response = client.get(
                    url,
                    data=params,
                    HTTP_X_WORKSPACE_ID=str(self.workspace.id),
                )
                self.assertEqual(response.status_code, 400)

        response = client.get(
            url,
            data={
                "date_from": "2025-11-02",
                "date_to": "2026-07-29",
            },
            HTTP_X_WORKSPACE_ID=str(self.workspace.id),
        )

        self.assertEqual(response.status_code, 200)

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
            total_spend=Decimal("0.00"),
        )
        AvitoListingStatsCoverage.objects.create(
            workspace=self.workspace,
            listing=self.listing,
            coverage_from=date(2026, 5, 1),
            finalized_through=date(2026, 5, 2),
            spending_coverage_from=date(2026, 5, 1),
            spending_finalized_through=date(2026, 5, 2),
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
        self.assertIs(report["stats_complete"], True)
        self.assertIs(report["spend_complete"], True)
        self.assertEqual(
            report["totals"]["views_to_contacts_conversion"],
            "13.33",
        )

        listing_report = report["listings"][0]
        self.assertEqual(listing_report["listing_id"], self.listing.id)
        self.assertEqual(listing_report["avito_id"], "24122261")
        self.assertIs(listing_report["stats_complete"], True)
        self.assertIs(listing_report["spend_complete"], True)
        self.assertEqual(listing_report["totals"]["cost_per_contact"], "6.25")
        self.assertEqual(
            listing_report["totals"]["views_to_contacts_conversion"],
            "13.33",
        )
        self.assertEqual(listing_report["daily"][0]["cost_per_contact"], "6.25")
        self.assertEqual(
            listing_report["daily"][0]["views_to_contacts_conversion"],
            "20.00",
        )
        self.assertEqual(
            listing_report["daily"][1]["total_spend"],
            "0.00",
        )
        self.assertIsNone(listing_report["daily"][1]["cost_per_contact"])
        self.assertEqual(
            listing_report["daily"][1]["views_to_contacts_conversion"],
            "0.00",
        )

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
        delay.assert_called_once()
        task_args = delay.call_args.args
        self.assertEqual(len(task_args), 5)
        self.assertEqual(
            task_args[:4],
            (
                self.avito_account.id,
                "2026-05-01",
                "2026-05-02",
                None,
            ),
        )
        run_id = UUID(task_args[4])
        self.assertEqual(sync_state.run_id, run_id)
        self.assertIsNone(sync_state.heartbeat_at)

    @patch(
        "analytics.api_views.enqueue_avito_profile_daily_sync",
    )
    def test_import_daily_stats_api_allows_only_owner_and_admin(
            self,
            enqueue_profile_sync,
    ):
        enqueue_profile_sync.return_value = {
            "sync_state": SimpleNamespace(
                status=AvitoStatsSyncState.Status.QUEUED,
            ),
            "task_id": "profile-stats-task-id",
            "queued": True,
            "date_from": date(2026, 7, 28),
            "date_to": date(2026, 7, 28),
        }
        url = (
            "/api/analytics/avito-accounts/"
            f"{self.avito_account.id}/import-daily-stats/"
        )

        for role in (
                WorkspaceMembership.Role.MANAGER,
                WorkspaceMembership.Role.ANALYST,
                WorkspaceMembership.Role.VIEWER,
        ):
            user = User.objects.create_user(
                email=f"analytics-sync-{role}@example.com",
                password="test",
            )
            WorkspaceMembership.objects.create(
                workspace=self.workspace,
                user=user,
                role=role,
                status=WorkspaceMembership.Status.ACTIVE,
            )
            client = APIClient()
            client.force_authenticate(user)

            with self.subTest(role=role):
                response = client.post(
                    url,
                    data={},
                    format="json",
                    HTTP_X_WORKSPACE_ID=str(self.workspace.id),
                )
                self.assertEqual(response.status_code, 403)

        enqueue_profile_sync.assert_not_called()

        admin = User.objects.create_user(
            email="analytics-sync-admin@example.com",
            password="test",
        )
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=admin,
            role=WorkspaceMembership.Role.ADMIN,
            status=WorkspaceMembership.Status.ACTIVE,
        )
        client = APIClient()
        client.force_authenticate(admin)

        response = client.post(
            url,
            data={},
            format="json",
            HTTP_X_WORKSPACE_ID=str(self.workspace.id),
        )

        self.assertEqual(response.status_code, 202)
        enqueue_profile_sync.assert_called_once()

    @patch(
        "analytics.api_views.enqueue_avito_profile_daily_sync",
    )
    @patch(
        "analytics.api_views.timezone.localdate",
        return_value=date(2026, 7, 29),
    )
    def test_import_daily_stats_api_without_range_queues_profile_chain(
            self,
            localdate,
            enqueue_profile_sync,
    ):
        client = APIClient()
        client.force_authenticate(self.user)

        enqueue_profile_sync.return_value = {
            "sync_state": SimpleNamespace(
                status=AvitoStatsSyncState.Status.QUEUED,
            ),
            "task_id": "profile-stats-task-id",
            "queued": True,
            "date_from": date(2026, 7, 28),
            "date_to": date(2026, 7, 28),
        }

        response = client.post(
            (
                "/api/analytics/avito-accounts/"
                f"{self.avito_account.id}/import-daily-stats/"
            ),
            data={},
            format="json",
            HTTP_X_WORKSPACE_ID=str(self.workspace.id),
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["status"], "queued")
        self.assertEqual(
            response.data["task_id"],
            "profile-stats-task-id",
        )
        self.assertEqual(
            response.data["date_from"],
            "2026-07-28",
        )
        self.assertEqual(
            response.data["date_to"],
            "2026-07-28",
        )
        enqueue_profile_sync.assert_called_once_with(
            avito_account=self.avito_account,
            stat_date=date(2026, 7, 28),
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

    @patch(
        "analytics.serializers.timezone.localdate",
        return_value=date(2026, 7, 30),
    )
    def test_import_daily_stats_api_rejects_uncompleted_dates(
            self,
            localdate,
    ):
        client = APIClient()
        client.force_authenticate(self.user)

        with patch(
                "analytics.tasks.import_avito_account_daily_stats_task.delay",
        ) as delay:
            delay.return_value.id = "unexpected-task-id"
            response = client.post(
                (
                    "/api/analytics/avito-accounts/"
                    f"{self.avito_account.id}/import-daily-stats/"
                ),
                data={
                    "date_from": "2026-07-29",
                    "date_to": "2026-07-30",
                },
                format="json",
                HTTP_X_WORKSPACE_ID=str(self.workspace.id),
            )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            AvitoStatsSyncState.objects.filter(
                avito_account=self.avito_account,
            ).exists()
        )

    @patch(
        "analytics.serializers.timezone.localdate",
        return_value=date(2026, 7, 30),
    )
    def test_import_daily_stats_api_accepts_at_most_270_days(
            self,
            localdate,
    ):
        client = APIClient()
        client.force_authenticate(self.user)
        url = (
            "/api/analytics/avito-accounts/"
            f"{self.avito_account.id}/import-daily-stats/"
        )

        with patch(
                "analytics.tasks.import_avito_account_daily_stats_task.delay",
        ) as delay:
            delay.return_value.id = "analytics-task-id"

            response = client.post(
                url,
                data={
                    "date_from": "2025-11-01",
                    "date_to": "2026-07-29",
                },
                format="json",
                HTTP_X_WORKSPACE_ID=str(self.workspace.id),
            )

            self.assertEqual(response.status_code, 400)
            self.assertFalse(
                AvitoStatsSyncState.objects.filter(
                    avito_account=self.avito_account,
                ).exists()
            )

            response = client.post(
                url,
                data={
                    "date_from": "2025-11-02",
                    "date_to": "2026-07-29",
                },
                format="json",
                HTTP_X_WORKSPACE_ID=str(self.workspace.id),
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["date_from"], "2025-11-02")
        self.assertEqual(response.data["date_to"], "2026-07-29")

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
        AvitoListingStatsCoverage.objects.create(
            workspace=self.workspace,
            listing=self.listing,
            coverage_from=date(2026, 5, 1),
            finalized_through=date(2026, 5, 1),
            spending_coverage_from=date(2026, 5, 1),
            spending_finalized_through=date(2026, 5, 1),
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
        self.assertIs(response.data["stats_complete"], True)
        self.assertIs(response.data["spend_complete"], True)
        self.assertEqual(
            response.data["totals"]["views_to_contacts_conversion"],
            "20.00",
        )
        self.assertEqual(response.data["listings"][0]["avito_id"], "24122261")

    def test_listing_stats_api_includes_confirmed_zero_without_daily_row(self):
        requested_day = date(2026, 5, 1)
        AvitoListingStatsCoverage.objects.create(
            workspace=self.workspace,
            listing=self.listing,
            coverage_from=requested_day,
            finalized_through=requested_day,
            spending_coverage_from=requested_day,
            spending_finalized_through=requested_day,
        )

        client = APIClient()
        client.force_authenticate(self.user)

        response = client.get(
            (
                "/api/analytics/avito-accounts/"
                f"{self.avito_account.id}/listing-stats/"
            ),
            data={
                "date_from": requested_day.isoformat(),
                "date_to": requested_day.isoformat(),
            },
            HTTP_X_WORKSPACE_ID=str(self.workspace.id),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["listings"]), 1)
        self.assertIs(response.data["stats_complete"], True)
        self.assertIs(response.data["spend_complete"], True)
        self.assertEqual(response.data["totals"]["views"], 0)
        self.assertEqual(response.data["totals"]["contacts"], 0)
        self.assertEqual(response.data["totals"]["favorites"], 0)
        self.assertEqual(
            response.data["totals"]["total_spend"],
            "0.00",
        )

        listing_report = response.data["listings"][0]
        self.assertEqual(
            listing_report["listing_id"],
            self.listing.id,
        )
        self.assertIs(listing_report["stats_complete"], True)
        self.assertIs(listing_report["spend_complete"], True)
        self.assertEqual(listing_report["totals"]["views"], 0)
        self.assertEqual(listing_report["totals"]["contacts"], 0)
        self.assertEqual(listing_report["totals"]["favorites"], 0)
        self.assertEqual(
            listing_report["totals"]["total_spend"],
            "0.00",
        )
        self.assertEqual(listing_report["daily"], [])

    def test_listing_stats_api_paginates_listings_but_keeps_full_totals(self):
        requested_day = date(2026, 5, 1)
        listings = [self.listing]

        for index in range(2):
            listings.append(
                AvitoListing.objects.create(
                    workspace=self.workspace,
                    avito_account=self.avito_account,
                    avito_id=f"2412227{index}",
                    status="active",
                    title=f"Paginated analytics listing {index}",
                )
            )

        for listing, views in zip(
                listings,
                (10, 20, 30),
                strict=True,
        ):
            AvitoListingStatsCoverage.objects.create(
                workspace=self.workspace,
                listing=listing,
                coverage_from=requested_day,
                finalized_through=requested_day,
                spending_coverage_from=requested_day,
                spending_finalized_through=requested_day,
            )
            AvitoListingDailyStats.objects.create(
                workspace=self.workspace,
                listing=listing,
                date=requested_day,
                views=views,
                contacts=1,
                total_spend=Decimal("1.00"),
            )

        client = APIClient()
        client.force_authenticate(self.user)

        response = client.get(
            (
                "/api/analytics/avito-accounts/"
                f"{self.avito_account.id}/listing-stats/"
            ),
            data={
                "date_from": requested_day.isoformat(),
                "date_to": requested_day.isoformat(),
                "page": 2,
                "page_size": 1,
            },
            HTTP_X_WORKSPACE_ID=str(self.workspace.id),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["listings"]), 1)
        self.assertEqual(
            response.data["listings"][0]["listing_id"],
            listings[1].id,
        )
        self.assertEqual(response.data["count"], 3)
        self.assertEqual(response.data["page"], 2)
        self.assertEqual(response.data["page_size"], 1)
        self.assertEqual(response.data["total_pages"], 3)
        self.assertEqual(response.data["totals"]["views"], 60)

    def test_ads_api_treats_period_before_publication_as_confirmed_zero(self):
        self.listing.published_at = datetime(
            2026,
            5,
            3,
            8,
            0,
            tzinfo=dt_timezone.utc,
        )
        self.listing.save(
            update_fields=[
                "published_at",
                "updated_at",
            ],
        )

        client = APIClient()
        client.force_authenticate(self.user)

        response = client.get(
            f"/api/avito/accounts/{self.avito_account.id}/ads/",
            data={
                "stats_date_from": "2026-05-01",
                "stats_date_to": "2026-05-02",
            },
            HTTP_X_WORKSPACE_ID=str(self.workspace.id),
        )

        self.assertEqual(response.status_code, 200)

        listing_row = next(
            item
            for item in response.data["results"]
            if item["avito_id"] == self.listing.avito_id
        )

        self.assertEqual(listing_row["stats"]["status"], "ready")
        self.assertEqual(listing_row["stats"]["views"], 0)
        self.assertEqual(listing_row["stats"]["contacts"], 0)
        self.assertEqual(listing_row["stats"]["favorites"], 0)
        self.assertEqual(listing_row["stats"]["total_spend"], "0.00")
        self.assertIs(listing_row["stats"]["spend_complete"], True)
        self.assertIsNone(
            listing_row["stats"]["views_to_contacts_conversion"]
        )
        
    def test_ads_api_returns_accumulated_stats_and_sync_state(self):
        AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.SUCCESS,
            coverage_from=date(2026, 5, 1),
            coverage_to=date(2026, 5, 2),
            last_successful_at=datetime(2026, 5, 3, 8, 0, tzinfo=dt_timezone.utc),
        )
        coverage_model = apps.get_model(
            "analytics",
            "AvitoListingStatsCoverage",
        )
        coverage_model.objects.create(
            workspace=self.workspace,
            listing=self.listing,
            coverage_from=date(2026, 5, 1),
            finalized_through=date(2026, 5, 2),
            spending_coverage_from=date(2026, 5, 1),
            spending_finalized_through=date(2026, 5, 2),
            last_successful_at=datetime(
                2026,
                5,
                3,
                8,
                0,
                tzinfo=dt_timezone.utc,
            ),
        )
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
            contacts=1,
            favorites=2,
            total_spend=Decimal("3.00"),
        )

        client = APIClient()
        client.force_authenticate(self.user)
        response = client.get(
            f"/api/avito/accounts/{self.avito_account.id}/ads/",
            data={
                "stats_date_from": "2026-05-01",
                "stats_date_to": "2026-05-02",
            },
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
        self.assertEqual(listing_row["stats"]["favorites"], 3)
        self.assertEqual(listing_row["stats"]["total_spend"], "15.50")
        self.assertIs(listing_row["stats"]["spend_complete"], True)
        self.assertEqual(
            listing_row["stats"]["views_to_contacts_conversion"],
            "20.00",
        )

    def test_ads_api_accepts_coverage_starting_on_publication_date(self):
        published_day = date(2026, 5, 2)

        self.listing.published_at = datetime(
            2026,
            5,
            2,
            8,
            0,
            tzinfo=dt_timezone.utc,
        )
        self.listing.save(
            update_fields=[
                "published_at",
                "updated_at",
            ],
        )

        AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.SUCCESS,
            coverage_from=published_day,
            coverage_to=published_day,
            last_successful_at=datetime(
                2026,
                5,
                3,
                8,
                0,
                tzinfo=dt_timezone.utc,
            ),
        )

        AvitoListingStatsCoverage.objects.create(
            workspace=self.workspace,
            listing=self.listing,
            coverage_from=published_day,
            finalized_through=published_day,
            spending_coverage_from=published_day,
            spending_finalized_through=published_day,
            last_successful_at=datetime(
                2026,
                5,
                3,
                8,
                0,
                tzinfo=dt_timezone.utc,
            ),
        )

        AvitoListingDailyStats.objects.create(
            workspace=self.workspace,
            listing=self.listing,
            date=published_day,
            views=7,
            contacts=1,
            favorites=2,
            total_spend=Decimal("5.00"),
        )

        client = APIClient()
        client.force_authenticate(self.user)

        response = client.get(
            f"/api/avito/accounts/{self.avito_account.id}/ads/",
            data={
                "stats_date_from": "2026-05-01",
                "stats_date_to": "2026-05-02",
            },
            HTTP_X_WORKSPACE_ID=str(self.workspace.id),
        )

        self.assertEqual(response.status_code, 200)

        listing_row = next(
            item
            for item in response.data["results"]
            if item["avito_id"] == self.listing.avito_id
        )

        self.assertEqual(listing_row["stats"]["status"], "ready")
        self.assertEqual(listing_row["stats"]["views"], 7)
        self.assertEqual(listing_row["stats"]["contacts"], 1)
        self.assertEqual(listing_row["stats"]["favorites"], 2)
        self.assertEqual(listing_row["stats"]["total_spend"], "5.00")
        self.assertIs(listing_row["stats"]["spend_complete"], True)

    def test_ads_api_distinguishes_processing_from_confirmed_zero(self):
        client = APIClient()
        client.force_authenticate(self.user)

        response = client.get(
            f"/api/avito/accounts/{self.avito_account.id}/ads/",
            data={
                "stats_date_from": "2026-05-01",
                "stats_date_to": "2026-05-02",
            },
            HTTP_X_WORKSPACE_ID=str(self.workspace.id),
        )
        listing_row = response.data["results"][0]
        self.assertEqual(response.data["stats_sync"]["status"], "not_started")
        self.assertEqual(listing_row["stats"]["status"], "processing")
        self.assertIsNone(listing_row["stats"]["views"])
        self.assertIsNone(listing_row["stats"]["contacts"])
        self.assertIsNone(listing_row["stats"]["favorites"])
        self.assertIsNone(listing_row["stats"]["total_spend"])
        self.assertIsNone(
            listing_row["stats"]["views_to_contacts_conversion"]
        )

        AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.SUCCESS,
            coverage_from=date(2026, 5, 1),
            coverage_to=date(2026, 5, 2),
            last_successful_at=datetime(2026, 5, 3, 8, 0, tzinfo=dt_timezone.utc),
        )
        coverage_model = apps.get_model(
            "analytics",
            "AvitoListingStatsCoverage",
        )
        coverage_model.objects.create(
            workspace=self.workspace,
            listing=self.listing,
            coverage_from=date(2026, 5, 1),
            finalized_through=date(2026, 5, 2),
            spending_coverage_from=date(2026, 5, 1),
            spending_finalized_through=date(2026, 5, 2),
            last_successful_at=datetime(
                2026,
                5,
                3,
                8,
                0,
                tzinfo=dt_timezone.utc,
            ),
        )
        response = client.get(
            f"/api/avito/accounts/{self.avito_account.id}/ads/",
            data={
                "stats_date_from": "2026-05-01",
                "stats_date_to": "2026-05-02",
            },
            HTTP_X_WORKSPACE_ID=str(self.workspace.id),
        )
        listing_row = response.data["results"][0]
        self.assertEqual(listing_row["stats"]["status"], "ready")
        self.assertEqual(listing_row["stats"]["views"], 0)
        self.assertEqual(listing_row["stats"]["contacts"], 0)
        self.assertEqual(listing_row["stats"]["favorites"], 0)
        self.assertEqual(listing_row["stats"]["total_spend"], "0.00")
        self.assertIs(listing_row["stats"]["spend_complete"], True)
        self.assertIsNone(
            listing_row["stats"]["views_to_contacts_conversion"]
        )

    def test_ads_api_orders_by_views_and_contacts_in_both_directions(self):
        high_views = self.create_listing_with_stats(
            avito_id="STATS-HIGH-VIEWS",
            views=30,
            contacts=1,
        )
        high_contacts = self.create_listing_with_stats(
            avito_id="STATS-HIGH-CONTACTS",
            views=10,
            contacts=5,
        )
        middle = self.create_listing_with_stats(
            avito_id="STATS-MIDDLE",
            views=20,
            contacts=3,
        )

        expected_orders = {
            "views": [
                high_contacts.avito_id,
                middle.avito_id,
                high_views.avito_id,
                self.listing.avito_id,
            ],
            "-views": [
                high_views.avito_id,
                middle.avito_id,
                high_contacts.avito_id,
                self.listing.avito_id,
            ],
            "contacts": [
                high_views.avito_id,
                middle.avito_id,
                high_contacts.avito_id,
                self.listing.avito_id,
            ],
            "-contacts": [
                high_contacts.avito_id,
                middle.avito_id,
                high_views.avito_id,
                self.listing.avito_id,
            ],
        }

        client = APIClient()
        client.force_authenticate(self.user)

        for ordering, expected_avito_ids in expected_orders.items():
            with self.subTest(ordering=ordering):
                response = client.get(
                    f"/api/avito/accounts/{self.avito_account.id}/ads/",
                    data={
                        "entity_type": "avito_listing",
                        "ordering": ordering,
                        "stats_date_from": "2026-05-01",
                        "stats_date_to": "2026-05-01",
                        "page_size": 20,
                    },
                    HTTP_X_WORKSPACE_ID=str(self.workspace.id),
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    [
                        item["avito_id"]
                        for item in response.data["results"]
                    ],
                    expected_avito_ids,
                )

    def test_ads_stats_ordering_is_stable_across_pages(self):
        listings = [
            self.create_listing_with_stats(
                avito_id=f"STATS-PAGE-{index}",
                views=views,
                contacts=index,
            )
            for index, views in enumerate((40, 30, 20), start=1)
        ]

        client = APIClient()
        client.force_authenticate(self.user)
        pages = []

        for page in (1, 2):
            response = client.get(
                f"/api/avito/accounts/{self.avito_account.id}/ads/",
                data={
                    "entity_type": "avito_listing",
                    "ordering": "-views",
                    "stats_date_from": "2026-05-01",
                    "stats_date_to": "2026-05-01",
                    "page": page,
                    "page_size": 2,
                },
                HTTP_X_WORKSPACE_ID=str(self.workspace.id),
            )

            self.assertEqual(response.status_code, 200)
            pages.extend(response.data["results"])

        self.assertEqual(
            [item["avito_id"] for item in pages],
            [
                listings[0].avito_id,
                listings[1].avito_id,
                listings[2].avito_id,
                self.listing.avito_id,
            ],
        )

    def test_ads_api_filters_stats_and_orders_by_conversion(self):
        low_views = self.create_listing_with_stats(
            avito_id="STATS-LOW-VIEWS",
            views=10,
            contacts=5,
        )
        self.create_listing_with_stats(
            avito_id="STATS-VIEWS-BOUNDARY",
            views=20,
            contacts=4,
        )
        low_conversion = self.create_listing_with_stats(
            avito_id="STATS-LOW-CONVERSION",
            views=30,
            contacts=3,
        )
        high_conversion = self.create_listing_with_stats(
            avito_id="STATS-HIGH-CONVERSION",
            views=40,
            contacts=8,
        )

        client = APIClient()
        client.force_authenticate(self.user)
        url = f"/api/avito/accounts/{self.avito_account.id}/ads/"

        by_views = client.get(
            url,
            data={
                "entity_type": "avito_listing",
                "min_views": 20,
                "ordering": "views_to_contacts_conversion",
                "stats_date_from": "2026-05-01",
                "stats_date_to": "2026-05-01",
                "page_size": 20,
            },
            HTTP_X_WORKSPACE_ID=str(self.workspace.id),
        )

        self.assertEqual(by_views.status_code, 200)
        self.assertEqual(
            [item["avito_id"] for item in by_views.data["results"]],
            [
                low_conversion.avito_id,
                "STATS-VIEWS-BOUNDARY",
                high_conversion.avito_id,
            ],
        )

        by_contacts = client.get(
            url,
            data={
                "entity_type": "avito_listing",
                "min_contacts": 3,
                "ordering": "views_to_contacts_conversion",
                "stats_date_from": "2026-05-01",
                "stats_date_to": "2026-05-01",
                "page_size": 20,
            },
            HTTP_X_WORKSPACE_ID=str(self.workspace.id),
        )

        self.assertEqual(by_contacts.status_code, 200)
        self.assertEqual(
            [item["avito_id"] for item in by_contacts.data["results"]],
            [
                low_conversion.avito_id,
                "STATS-VIEWS-BOUNDARY",
                high_conversion.avito_id,
                low_views.avito_id,
            ],
        )

    def test_ads_api_combines_views_and_contacts_thresholds(self):
        self.create_listing_with_stats(
            avito_id="STATS-VIEWS-ONLY",
            views=30,
            contacts=2,
        )
        self.create_listing_with_stats(
            avito_id="STATS-CONTACTS-ONLY",
            views=10,
            contacts=8,
        )
        matched = self.create_listing_with_stats(
            avito_id="STATS-BOTH-FILTERS",
            views=40,
            contacts=6,
        )

        client = APIClient()
        client.force_authenticate(self.user)

        response = client.get(
            f"/api/avito/accounts/{self.avito_account.id}/ads/",
            data={
                "entity_type": "avito_listing",
                "min_views": 20,
                "min_contacts": 3,
                "ordering": "views_to_contacts_conversion",
                "stats_date_from": "2026-05-01",
                "stats_date_to": "2026-05-01",
                "page_size": 20,
            },
            HTTP_X_WORKSPACE_ID=str(self.workspace.id),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["avito_id"] for item in response.data["results"]],
            [matched.avito_id],
        )

    def test_ads_api_rejects_negative_stats_thresholds(self):
        client = APIClient()
        client.force_authenticate(self.user)

        response = client.get(
            f"/api/avito/accounts/{self.avito_account.id}/ads/",
            data={
                "min_views": -1,
                "min_contacts": -1,
            },
            HTTP_X_WORKSPACE_ID=str(self.workspace.id),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("min_views", response.data)
        self.assertIn("min_contacts", response.data)

    @override_settings(AVITO_STATS_HISTORY_DAYS=270)
    @patch(
        "avitotask.avito_api_views.timezone.localdate",
        return_value=date(2026, 7, 25),
    )
    def test_ads_api_defaults_to_last_thirty_completed_days(
            self,
            localdate,
    ):
        AvitoListingStatsCoverage.objects.create(
            workspace=self.workspace,
            listing=self.listing,
            coverage_from=date(2026, 6, 25),
            finalized_through=date(2026, 7, 24),
        )
        for stat_date, views, contacts, favorites in (
                (date(2026, 6, 24), 100, 10, 10),
                (date(2026, 6, 25), 10, 1, 2),
                (date(2026, 7, 24), 20, 3, 4),
                (date(2026, 7, 25), 200, 20, 20),
        ):
            AvitoListingDailyStats.objects.create(
                workspace=self.workspace,
                listing=self.listing,
                date=stat_date,
                views=views,
                contacts=contacts,
                favorites=favorites,
            )

        client = APIClient()
        client.force_authenticate(self.user)
        response = client.get(
            f"/api/avito/accounts/{self.avito_account.id}/ads/",
            data={
                "entity_type": "avito_listing",
                "page_size": 20,
            },
            HTTP_X_WORKSPACE_ID=str(self.workspace.id),
        )

        self.assertEqual(response.status_code, 200)
        stats = response.data["results"][0]["stats"]
        self.assertEqual(stats["status"], "ready")
        self.assertEqual(stats["views"], 30)
        self.assertEqual(stats["contacts"], 4)
        self.assertEqual(stats["favorites"], 6)
        self.assertEqual(
            stats["views_to_contacts_conversion"],
            "13.33",
        )

    def test_ads_stats_period_applies_to_totals_and_thresholds(self):
        period_start = date(2026, 5, 2)
        period_end = date(2026, 5, 3)
        AvitoListingStatsCoverage.objects.create(
            workspace=self.workspace,
            listing=self.listing,
            coverage_from=date(2026, 5, 1),
            finalized_through=period_end,
        )
        for stat_date, views, contacts in (
                (date(2026, 5, 1), 100, 10),
                (period_start, 10, 2),
                (period_end, 5, 1),
        ):
            AvitoListingDailyStats.objects.create(
                workspace=self.workspace,
                listing=self.listing,
                date=stat_date,
                views=views,
                contacts=contacts,
            )

        outside_only = AvitoListing.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            avito_id="STATS-OUTSIDE-PERIOD",
            status="active",
            title="Outside period",
        )
        AvitoListingStatsCoverage.objects.create(
            workspace=self.workspace,
            listing=outside_only,
            coverage_from=date(2026, 5, 1),
            finalized_through=period_end,
        )
        AvitoListingDailyStats.objects.create(
            workspace=self.workspace,
            listing=outside_only,
            date=date(2026, 5, 1),
            views=200,
            contacts=20,
        )
        AvitoListingDailyStats.objects.create(
            workspace=self.workspace,
            listing=outside_only,
            date=period_start,
            views=5,
            contacts=1,
        )

        client = APIClient()
        client.force_authenticate(self.user)
        response = client.get(
            f"/api/avito/accounts/{self.avito_account.id}/ads/",
            data={
                "entity_type": "avito_listing",
                "stats_date_from": period_start.isoformat(),
                "stats_date_to": period_end.isoformat(),
                "min_views": 10,
                "ordering": "-views",
                "page_size": 20,
            },
            HTTP_X_WORKSPACE_ID=str(self.workspace.id),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["avito_id"] for item in response.data["results"]],
            [self.listing.avito_id],
        )
        stats = response.data["results"][0]["stats"]
        self.assertEqual(stats["views"], 15)
        self.assertEqual(stats["contacts"], 3)
        self.assertEqual(
            stats["views_to_contacts_conversion"],
            "20.00",
        )

    def test_default_date_ordering_uses_title_as_tie_breaker(self):
        self.listing.title = "Zulu"
        self.listing.published_end = date(2099, 6, 30)
        self.listing.save(update_fields=["title", "published_end"])
        for avito_id, title in (
                ("DATE-TITLE-ALPHA", "alpha"),
                ("DATE-TITLE-BETA", "Beta"),
        ):
            AvitoListing.objects.create(
                workspace=self.workspace,
                avito_account=self.avito_account,
                avito_id=avito_id,
                status="active",
                title=title,
                published_end=date(2099, 6, 30),
            )
        AvitoListing.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            avito_id="DATE-EARLIER",
            status="active",
            title="Aardvark",
            published_end=date(2099, 5, 1),
        )

        client = APIClient()
        client.force_authenticate(self.user)
        response = client.get(
            f"/api/avito/accounts/{self.avito_account.id}/ads/",
            data={
                "entity_type": "avito_listing",
                "page_size": 20,
            },
            HTTP_X_WORKSPACE_ID=str(self.workspace.id),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["title"] for item in response.data["results"]],
            [
                "alpha",
                "Beta",
                "Zulu",
                "Aardvark",
            ],
        )

    @patch(
        "avitotask.avito_api_views.timezone.localdate",
        return_value=date(2026, 7, 25),
    )
    def test_ads_api_validates_completed_stats_period(
            self,
            localdate,
    ):
        client = APIClient()
        client.force_authenticate(self.user)
        url = f"/api/avito/accounts/{self.avito_account.id}/ads/"
        last_completed_date = date(2026, 7, 24)
        earliest_available_date = last_completed_date - timedelta(days=269)
        date_before_available_history = earliest_available_date - timedelta(days=1)

        invalid_params = (
            {
                "stats_date_from": "2026-07-01",
            },
            {
                "stats_date_from": "2026-07-10",
                "stats_date_to": "2026-07-01",
            },
            {
                "stats_date_from": "2026-07-01",
                "stats_date_to": "2026-07-25",
            },
            {
                "stats_date_from": date_before_available_history.isoformat(),
                "stats_date_to": last_completed_date.isoformat(),
            },
        )

        for params in invalid_params:
            with self.subTest(params=params):
                response = client.get(
                    url,
                    data=params,
                    HTTP_X_WORKSPACE_ID=str(self.workspace.id),
                )
                self.assertEqual(response.status_code, 400)

        response = client.get(
            url,
            data={
                "stats_date_from": earliest_available_date.isoformat(),
                "stats_date_to": last_completed_date.isoformat(),
            },
            HTTP_X_WORKSPACE_ID=str(self.workspace.id),
        )

        self.assertEqual(response.status_code, 200)

    def create_listing_with_stats(
            self,
            *,
            avito_id,
            views,
            contacts,
    ):
        listing = AvitoListing.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            avito_id=avito_id,
            status="active",
            title=avito_id,
        )
        AvitoListingStatsCoverage.objects.create(
            workspace=self.workspace,
            listing=listing,
            coverage_from=date(2026, 5, 1),
            finalized_through=date(2026, 5, 1),
        )
        AvitoListingDailyStats.objects.create(
            workspace=self.workspace,
            listing=listing,
            date=date(2026, 5, 1),
            views=views,
            contacts=contacts,
        )
        return listing


class AvitoAnalyticsImportTests(TestCase):

    @patch(
        "analytics.services.avito_stats.AvitoApiClient.get_item_stats",
        return_value={"result": {"items": []}},
    )
    def test_import_splits_long_period_into_avito_supported_ranges(
            self,
            get_item_stats,
    ):
        result = import_avito_listing_daily_stats_for_account(
            avito_account=self.avito_account,
            date_from=date(2025, 7, 23),
            date_to=date(2026, 7, 22),
        )

        requested_ranges = [
            (
                call.kwargs["date_from"],
                call.kwargs["date_to"],
            )
            for call in get_item_stats.call_args_list
        ]

        self.assertEqual(
            requested_ranges,
            [
                (date(2025, 7, 23), date(2026, 4, 18)),
                (date(2026, 4, 19), date(2026, 7, 22)),
            ],
        )

        for range_from, range_to in requested_ranges:
            period_days = (range_to - range_from).days + 1
            self.assertLessEqual(period_days, 270)

        self.assertEqual(result.total_listings, 1)

    @override_settings(AVITO_STATS_LISTINGS_BATCH_SIZE=150)
    @patch(
        "analytics.services.avito_stats.AvitoApiClient.get_item_stats",
        return_value={"result": {"items": []}},
    )
    def test_v1_import_uses_configurable_listings_batch_size(
            self,
            get_item_stats,
    ):
        AvitoListing.objects.bulk_create([
            AvitoListing(
                workspace=self.workspace,
                avito_account=self.avito_account,
                avito_id=str(30_000_000 + index),
                status="active",
                title=f"Analytics import listing {index}",
            )
            for index in range(150)
        ])

        import_avito_listing_daily_stats_for_account(
            avito_account=self.avito_account,
            date_from=date(2026, 5, 1),
            date_to=date(2026, 5, 1),
        )

        requested_batch_sizes = [
            len(call.kwargs["item_ids"])
            for call in get_item_stats.call_args_list
        ]

        self.assertEqual(requested_batch_sizes, [150, 1])

    @patch(
        "analytics.services.avito_stats.AvitoApiClient.get_item_stats",
        return_value={"result": {"items": []}},
    )
    def test_v1_import_rejects_unsupported_listings_batch_size(
            self,
            get_item_stats,
    ):
        for batch_size in (0, 201):
            with self.subTest(batch_size=batch_size):
                with override_settings(
                        AVITO_STATS_LISTINGS_BATCH_SIZE=batch_size,
                ):
                    with self.assertRaisesMessage(
                            ValueError,
                            (
                                    "AVITO_STATS_LISTINGS_BATCH_SIZE "
                                    "должен быть от 1 до 200."
                            ),
                    ):
                        import_avito_listing_daily_stats_for_account(
                            avito_account=self.avito_account,
                            date_from=date(2026, 5, 1),
                            date_to=date(2026, 5, 1),
                        )

        get_item_stats.assert_not_called()

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

        coverage = AvitoListingStatsCoverage.objects.get(
            listing=self.listing,
        )
        self.assertEqual(coverage.coverage_from, date(2026, 5, 1))
        self.assertEqual(
            coverage.finalized_through,
            date(2026, 5, 1),
        )
        self.assertIsNone(coverage.spending_coverage_from)
        self.assertIsNone(coverage.spending_finalized_through)
        self.assertIsNotNone(coverage.last_attempted_at)
        self.assertIsNotNone(coverage.last_successful_at)
        self.assertEqual(coverage.error, "")

    @patch(
        "analytics.services.avito_stats.AvitoApiClient.get_item_stats",
        return_value={"result": {"items": []}},
    )
    def test_successful_empty_v1_response_confirms_zero_coverage(
            self,
            get_item_stats,
    ):
        result = import_avito_listing_daily_stats_for_account(
            avito_account=self.avito_account,
            date_from=date(2026, 5, 1),
            date_to=date(2026, 5, 2),
        )

        coverage = AvitoListingStatsCoverage.objects.get(
            listing=self.listing,
        )

        self.assertEqual(result.total_days, 0)
        self.assertFalse(
            AvitoListingDailyStats.objects.filter(
                listing=self.listing,
            ).exists()
        )
        self.assertEqual(coverage.coverage_from, date(2026, 5, 1))
        self.assertEqual(
            coverage.finalized_through,
            date(2026, 5, 2),
        )
        self.assertIsNotNone(coverage.last_successful_at)
        self.assertEqual(coverage.error, "")

    @patch(
        "analytics.services.avito_stats.AvitoApiClient.get_item_stats",
        return_value={"result": {"items": []}},
    )
    def test_successful_v1_import_extends_contiguous_listing_coverage(
            self,
            get_item_stats,
    ):
        AvitoListingStatsCoverage.objects.create(
            workspace=self.workspace,
            listing=self.listing,
            coverage_from=date(2026, 5, 1),
            finalized_through=date(2026, 5, 27),
            last_successful_at=datetime(
                2026,
                5,
                28,
                4,
                10,
                tzinfo=dt_timezone.utc,
            ),
        )

        import_avito_listing_daily_stats_for_account(
            avito_account=self.avito_account,
            date_from=date(2026, 5, 28),
            date_to=date(2026, 5, 29),
        )

        coverage = AvitoListingStatsCoverage.objects.get(
            listing=self.listing,
        )
        self.assertEqual(coverage.coverage_from, date(2026, 5, 1))
        self.assertEqual(
            coverage.finalized_through,
            date(2026, 5, 29),
        )
        self.assertEqual(coverage.error, "")

    @patch(
        "analytics.services.avito_stats.AvitoApiClient.get_item_stats",
        side_effect=AvitoApiError("Avito stats unavailable"),
    )
    def test_failed_v1_import_does_not_advance_listing_coverage(
            self,
            get_item_stats,
    ):
        previous_success = datetime(
            2026,
            5,
            28,
            4,
            10,
            tzinfo=dt_timezone.utc,
        )
        coverage = AvitoListingStatsCoverage.objects.create(
            workspace=self.workspace,
            listing=self.listing,
            coverage_from=date(2026, 5, 1),
            finalized_through=date(2026, 5, 27),
            last_successful_at=previous_success,
        )

        with self.assertRaises(AvitoApiError):
            import_avito_listing_daily_stats_for_account(
                avito_account=self.avito_account,
                date_from=date(2026, 5, 28),
                date_to=date(2026, 5, 29),
            )

        coverage.refresh_from_db()
        self.assertEqual(coverage.coverage_from, date(2026, 5, 1))
        self.assertEqual(
            coverage.finalized_through,
            date(2026, 5, 27),
        )
        self.assertEqual(
            coverage.last_successful_at,
            previous_success,
        )
        self.assertIsNotNone(coverage.last_attempted_at)
        self.assertIn("Avito stats unavailable", coverage.error)

    @patch(
        "analytics.services.avito_stats.AvitoApiClient.get_item_stats",
        return_value={"result": {"items": []}},
    )
    def test_v1_import_rejects_non_contiguous_coverage_range(
            self,
            get_item_stats,
    ):
        AvitoListingStatsCoverage.objects.create(
            workspace=self.workspace,
            listing=self.listing,
            coverage_from=date(2026, 5, 1),
            finalized_through=date(2026, 5, 27),
        )

        with self.assertRaisesMessage(
                ValueError,
                "Диапазон статистики должен продолжать",
        ):
            import_avito_listing_daily_stats_for_account(
                avito_account=self.avito_account,
                date_from=date(2026, 5, 29),
                date_to=date(2026, 5, 29),
            )

        get_item_stats.assert_not_called()

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
                    unchanged_stats=0,
                ),
        ):
            result = import_avito_account_daily_stats_task(
                self.avito_account.id,
                "2026-05-01",
                "2026-05-01",
            )

        sync_state.refresh_from_db()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["unchanged_stats"], 0)
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

    def test_v1_task_finishes_its_owned_run(self):
        run_id = UUID(
            "00000000-0000-0000-0000-000000000011"
        )
        sync_state = AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.QUEUED,
            run_id=run_id,
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
                    unchanged_stats=0,
                ),
        ):
            result = import_avito_account_daily_stats_task(
                self.avito_account.id,
                "2026-05-01",
                "2026-05-01",
                None,
                str(run_id),
            )

        sync_state.refresh_from_db()
        self.assertEqual(result["status"], "success")
        self.assertEqual(
            sync_state.status,
            AvitoStatsSyncState.Status.SUCCESS,
        )
        self.assertEqual(sync_state.run_id, run_id)
        self.assertEqual(
            sync_state.coverage_from,
            date(2026, 5, 1),
        )
        self.assertEqual(
            sync_state.coverage_to,
            date(2026, 5, 1),
        )

    def test_v1_task_marks_error_only_for_its_owned_run(self):
        run_id = UUID(
            "00000000-0000-0000-0000-000000000012"
        )
        sync_state = AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.QUEUED,
            run_id=run_id,
            requested_date_from=date(2026, 5, 1),
            requested_date_to=date(2026, 5, 1),
        )

        with patch(
                "analytics.tasks.import_avito_listing_daily_stats_for_account",
                side_effect=AvitoApiError("Owned v1 run failed"),
        ):
            with self.assertRaises(AvitoApiError):
                import_avito_account_daily_stats_task(
                    self.avito_account.id,
                    "2026-05-01",
                    "2026-05-01",
                    None,
                    str(run_id),
                )

        sync_state.refresh_from_db()
        self.assertEqual(
            sync_state.status,
            AvitoStatsSyncState.Status.ERROR,
        )
        self.assertEqual(sync_state.run_id, run_id)
        self.assertIn("Owned v1 run failed", sync_state.error)

    def test_v1_task_marks_error_when_date_normalization_fails(self):
        run_id = UUID(
            "00000000-0000-0000-0000-000000000071"
        )
        sync_state = AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.QUEUED,
            run_id=run_id,
            requested_date_from=date(2026, 5, 1),
            requested_date_to=date(2026, 5, 1),
        )

        with self.assertRaises(ValueError):
            import_avito_account_daily_stats_task(
                self.avito_account.id,
                "invalid-date",
                "2026-05-01",
                None,
                str(run_id),
            )

        sync_state.refresh_from_db()
        self.assertEqual(
            sync_state.status,
            AvitoStatsSyncState.Status.ERROR,
        )
        self.assertEqual(sync_state.run_id, run_id)
        self.assertTrue(sync_state.error)

    def test_profile_task_marks_error_when_date_normalization_fails(self):
        from analytics.tasks import (
            import_avito_account_profile_daily_stats_task,
        )

        run_id = UUID(
            "00000000-0000-0000-0000-000000000072"
        )
        sync_state = AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.QUEUED,
            run_id=run_id,
            requested_date_from=date(2026, 5, 1),
            requested_date_to=date(2026, 5, 1),
        )

        with self.assertRaises(ValueError):
            import_avito_account_profile_daily_stats_task(
                self.avito_account.id,
                "invalid-date",
                str(run_id),
            )

        sync_state.refresh_from_db()
        self.assertEqual(
            sync_state.status,
            AvitoStatsSyncState.Status.ERROR,
        )
        self.assertEqual(sync_state.run_id, run_id)
        self.assertTrue(sync_state.error)

    def test_backfill_task_marks_error_when_date_normalization_fails(self):
        from analytics.tasks import (
            backfill_missing_avito_listing_stats_task,
        )

        run_id = UUID(
            "00000000-0000-0000-0000-000000000073"
        )
        sync_state = AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.QUEUED,
            run_id=run_id,
            requested_date_from=date(2026, 5, 1),
            requested_date_to=date(2026, 5, 1),
        )

        with self.assertRaises(ValueError):
            backfill_missing_avito_listing_stats_task(
                self.avito_account.id,
                "invalid-date",
                str(run_id),
            )

        sync_state.refresh_from_db()
        self.assertEqual(
            sync_state.status,
            AvitoStatsSyncState.Status.ERROR,
        )
        self.assertEqual(sync_state.run_id, run_id)
        self.assertTrue(sync_state.error)

    def test_v1_task_requeues_owned_run_for_transient_api_error(self):
        run_id = UUID(
            "00000000-0000-0000-0000-000000000081"
        )
        sync_state = AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.QUEUED,
            run_id=run_id,
            requested_date_from=date(2026, 5, 1),
            requested_date_to=date(2026, 5, 1),
        )
        raised = None

        with patch(
                "analytics.tasks.import_avito_listing_daily_stats_for_account",
                side_effect=AvitoApiError(
                    "Temporary Avito failure",
                    status_code=503,
                ),
        ), patch.object(
            import_avito_account_daily_stats_task,
            "retry",
            side_effect=Retry("retry"),
        ):
            try:
                import_avito_account_daily_stats_task(
                    self.avito_account.id,
                    "2026-05-01",
                    "2026-05-01",
                    None,
                    str(run_id),
                )
            except Exception as exc:
                raised = exc

        sync_state.refresh_from_db()
        self.assertEqual(
            sync_state.status,
            AvitoStatsSyncState.Status.QUEUED,
        )
        self.assertEqual(sync_state.run_id, run_id)
        self.assertIsNone(sync_state.started_at)
        self.assertIsNone(sync_state.heartbeat_at)
        self.assertIn("Temporary Avito failure", sync_state.error)
        self.assertIsInstance(raised, Retry)

    def test_profile_task_requeues_owned_run_for_transient_api_error(self):
        from analytics.tasks import (
            import_avito_account_profile_daily_stats_task,
        )

        run_id = UUID(
            "00000000-0000-0000-0000-000000000082"
        )
        sync_state = AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.QUEUED,
            run_id=run_id,
            requested_date_from=date(2026, 5, 1),
            requested_date_to=date(2026, 5, 1),
        )
        raised = None

        with patch(
                "analytics.tasks.import_avito_profile_daily_stats_for_account",
                side_effect=AvitoApiError(
                    "Temporary profile failure",
                    status_code=503,
                ),
        ), patch.object(
            import_avito_account_profile_daily_stats_task,
            "retry",
            side_effect=Retry("retry"),
        ):
            try:
                import_avito_account_profile_daily_stats_task(
                    self.avito_account.id,
                    "2026-05-01",
                    str(run_id),
                )
            except Exception as exc:
                raised = exc

        sync_state.refresh_from_db()
        self.assertEqual(
            sync_state.status,
            AvitoStatsSyncState.Status.QUEUED,
        )
        self.assertEqual(sync_state.run_id, run_id)
        self.assertIsNone(sync_state.started_at)
        self.assertIsNone(sync_state.heartbeat_at)
        self.assertIn("Temporary profile failure", sync_state.error)
        self.assertIsInstance(raised, Retry)

    def test_backfill_task_requeues_owned_run_for_transient_api_error(self):
        from analytics.tasks import (
            backfill_missing_avito_listing_stats_task,
        )

        run_id = UUID(
            "00000000-0000-0000-0000-000000000083"
        )
        sync_state = AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.QUEUED,
            run_id=run_id,
            requested_date_from=date(2026, 5, 1),
            requested_date_to=date(2026, 5, 1),
        )
        raised = None

        with patch(
                "analytics.tasks.build_avito_stats_backfill_plan",
                side_effect=AvitoApiError(
                    "Temporary backfill failure",
                    status_code=503,
                ),
        ), patch.object(
            backfill_missing_avito_listing_stats_task,
            "retry",
            side_effect=Retry("retry"),
        ):
            try:
                backfill_missing_avito_listing_stats_task(
                    self.avito_account.id,
                    "2026-05-01",
                    str(run_id),
                )
            except Exception as exc:
                raised = exc

        sync_state.refresh_from_db()
        self.assertEqual(
            sync_state.status,
            AvitoStatsSyncState.Status.QUEUED,
        )
        self.assertEqual(sync_state.run_id, run_id)
        self.assertIsNone(sync_state.started_at)
        self.assertIsNone(sync_state.heartbeat_at)
        self.assertIn("Temporary backfill failure", sync_state.error)
        self.assertIsInstance(raised, Retry)

    @override_settings(AVITO_STATS_LISTINGS_BATCH_SIZE=1)
    def test_v1_task_stops_between_api_batches_when_superseded(self):
        stale_run_id = UUID(
            "00000000-0000-0000-0000-000000000061"
        )
        current_run_id = UUID(
            "00000000-0000-0000-0000-000000000062"
        )
        AvitoListing.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            avito_id="24122262",
            status="active",
            title="Second analytics import listing",
        )
        sync_state = AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.QUEUED,
            run_id=stale_run_id,
            requested_date_from=date(2026, 5, 1),
            requested_date_to=date(2026, 5, 1),
        )
        requested_batches = []

        def replace_owner_after_first_request(**kwargs):
            requested_batches.append(tuple(kwargs["item_ids"]))

            if len(requested_batches) == 1:
                AvitoStatsSyncState.objects.filter(
                    pk=sync_state.pk,
                ).update(
                    status=AvitoStatsSyncState.Status.QUEUED,
                    run_id=current_run_id,
                    requested_date_from=date(2026, 5, 2),
                    requested_date_to=date(2026, 5, 2),
                    requested_at=datetime.now(tz=dt_timezone.utc),
                    started_at=None,
                    heartbeat_at=None,
                )

            return {"result": {"items": []}}

        with patch(
                "analytics.services.avito_stats.AvitoApiClient.get_item_stats",
                side_effect=replace_owner_after_first_request,
        ):
            result = import_avito_account_daily_stats_task(
                self.avito_account.id,
                "2026-05-01",
                "2026-05-01",
                None,
                str(stale_run_id),
            )

        sync_state.refresh_from_db()
        self.assertEqual(result["status"], "superseded")
        self.assertEqual(len(requested_batches), 1)
        self.assertEqual(
            sync_state.status,
            AvitoStatsSyncState.Status.QUEUED,
        )
        self.assertEqual(sync_state.run_id, current_run_id)

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

    @override_settings(AVITO_STATS_STALE_TIMEOUT_MINUTES=30)
    def test_running_sync_uses_fresh_heartbeat_for_staleness(self):
        from analytics.tasks import is_active_sync

        now = datetime(
            2026,
            7,
            31,
            12,
            0,
            tzinfo=dt_timezone.utc,
        )
        sync_state = AvitoStatsSyncState(
            status=AvitoStatsSyncState.Status.RUNNING,
            started_at=now - timedelta(hours=2),
            heartbeat_at=now - timedelta(minutes=5),
        )

        self.assertTrue(
            is_active_sync(sync_state, now=now)
        )

    @patch(
        "analytics.tasks.timezone.now",
        return_value=datetime(
            2026,
            7,
            31,
            12,
            0,
            tzinfo=dt_timezone.utc,
        ),
    )
    def test_claim_sync_starts_heartbeat_for_owned_run(
            self,
            now,
    ):
        from analytics.tasks import claim_sync

        run_id = UUID(
            "00000000-0000-0000-0000-000000000031"
        )
        sync_state = AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.QUEUED,
            run_id=run_id,
            requested_date_from=date(2026, 7, 28),
            requested_date_to=date(2026, 7, 28),
        )

        claimed = claim_sync(
            self.avito_account,
            run_id=str(run_id),
        )

        sync_state.refresh_from_db()
        expected_time = datetime(
            2026,
            7,
            31,
            12,
            0,
            tzinfo=dt_timezone.utc,
        )
        self.assertTrue(claimed)
        self.assertEqual(
            sync_state.status,
            AvitoStatsSyncState.Status.RUNNING,
        )
        self.assertEqual(sync_state.started_at, expected_time)
        self.assertEqual(sync_state.heartbeat_at, expected_time)

    @override_settings(AVITO_STATS_STALE_TIMEOUT_MINUTES=30)
    @patch(
        "analytics.tasks.timezone.now",
        return_value=datetime(
            2026,
            7,
            31,
            12,
            0,
            tzinfo=dt_timezone.utc,
        ),
    )
    def test_claim_sync_never_reclaims_running_run_with_same_token(
            self,
            now,
    ):
        from analytics.tasks import claim_sync

        run_id = UUID(
            "00000000-0000-0000-0000-000000000032"
        )
        previous_time = datetime(
            2026,
            7,
            31,
            10,
            0,
            tzinfo=dt_timezone.utc,
        )
        sync_state = AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.RUNNING,
            run_id=run_id,
            started_at=previous_time,
            heartbeat_at=previous_time,
        )

        claimed = claim_sync(
            self.avito_account,
            run_id=str(run_id),
        )

        sync_state.refresh_from_db()
        self.assertFalse(claimed)
        self.assertEqual(
            sync_state.status,
            AvitoStatsSyncState.Status.RUNNING,
        )
        self.assertEqual(sync_state.started_at, previous_time)
        self.assertEqual(sync_state.heartbeat_at, previous_time)

    @patch(
        "analytics.tasks.timezone.now",
        return_value=datetime(
            2026,
            7,
            31,
            12,
            30,
            tzinfo=dt_timezone.utc,
        ),
    )
    def test_heartbeat_is_updated_only_by_owned_running_run(
            self,
            now,
    ):
        from analytics import tasks

        touch_sync_heartbeat = getattr(
            tasks,
            "touch_sync_heartbeat",
            None,
        )
        self.assertIsNotNone(touch_sync_heartbeat)

        current_run_id = UUID(
            "00000000-0000-0000-0000-000000000031"
        )
        stale_run_id = UUID(
            "00000000-0000-0000-0000-000000000030"
        )
        previous_heartbeat = datetime(
            2026,
            7,
            31,
            12,
            0,
            tzinfo=dt_timezone.utc,
        )
        expected_heartbeat = datetime(
            2026,
            7,
            31,
            12,
            30,
            tzinfo=dt_timezone.utc,
        )
        sync_state = AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.RUNNING,
            run_id=current_run_id,
            started_at=previous_heartbeat,
            heartbeat_at=previous_heartbeat,
        )

        stale_updated = touch_sync_heartbeat(
            avito_account_id=self.avito_account.id,
            run_id=str(stale_run_id),
        )

        sync_state.refresh_from_db()
        self.assertFalse(stale_updated)
        self.assertEqual(
            sync_state.heartbeat_at,
            previous_heartbeat,
        )

        current_updated = touch_sync_heartbeat(
            avito_account_id=self.avito_account.id,
            run_id=str(current_run_id),
        )

        sync_state.refresh_from_db()
        self.assertTrue(current_updated)
        self.assertEqual(
            sync_state.heartbeat_at,
            expected_heartbeat,
        )

    @patch(
        "analytics.tasks.import_avito_account_profile_daily_stats_task.delay",
    )
    def test_profile_daily_sync_enqueue_uses_requested_day(
            self,
            delay,
    ):
        from analytics.tasks import enqueue_avito_profile_daily_sync

        delay.return_value.id = "profile-daily-task-id"

        result = enqueue_avito_profile_daily_sync(
            avito_account=self.avito_account,
            stat_date=date(2026, 7, 28),
        )

        sync_state = AvitoStatsSyncState.objects.get(
            avito_account=self.avito_account,
        )
        self.assertTrue(result["queued"])
        self.assertEqual(result["task_id"], "profile-daily-task-id")
        self.assertEqual(
            sync_state.status,
            AvitoStatsSyncState.Status.QUEUED,
        )
        self.assertEqual(
            sync_state.requested_date_from,
            date(2026, 7, 28),
        )
        self.assertEqual(
            sync_state.requested_date_to,
            date(2026, 7, 28),
        )
        delay.assert_called_once()
        task_args = delay.call_args.args
        self.assertEqual(len(task_args), 3)
        self.assertEqual(
            task_args[:2],
            (
                self.avito_account.id,
                "2026-07-28",
            ),
        )
        run_id = UUID(task_args[2])
        self.assertEqual(sync_state.run_id, run_id)
        self.assertIsNone(sync_state.heartbeat_at)

    @patch(
        "analytics.tasks.enqueue_avito_profile_daily_sync",
    )
    @patch(
        "analytics.tasks.timezone.localdate",
        return_value=date(2026, 7, 29),
    )
    def test_daily_dispatcher_queues_only_yesterday(
            self,
            localdate,
            enqueue_profile_sync,
    ):
        from analytics.tasks import (
            enqueue_daily_avito_stats_syncs_task,
        )

        enqueue_profile_sync.return_value = {
            "queued": True,
        }

        result = enqueue_daily_avito_stats_syncs_task()

        self.assertEqual(result, {"queued": 1, "skipped": 0})
        enqueue_profile_sync.assert_called_once()
        call = enqueue_profile_sync.call_args
        self.assertEqual(
            call.kwargs["avito_account"].id,
            self.avito_account.id,
        )
        self.assertEqual(
            call.kwargs["stat_date"],
            date(2026, 7, 28),
        )

    @patch("analytics.tasks.enqueue_avito_stats_backfill")
    @patch(
        "analytics.tasks.import_avito_profile_daily_stats_for_account",
        return_value=SimpleNamespace(
            total_received=10,
            matched_listings=2,
            created_stats=2,
            updated_stats=0,
            deleted_zero_stats=0,
            confirmed_listings=1,
        ),
    )
    def test_profile_daily_task_marks_sync_success(
            self,
            profile_importer,
            enqueue_backfill,
    ):
        from analytics.tasks import (
            import_avito_account_profile_daily_stats_task,
        )

        enqueue_backfill.return_value = {
            "queued": True,
            "task_id": "backfill-task-id",
        }

        sync_state = AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.QUEUED,
            requested_date_from=date(2026, 7, 28),
            requested_date_to=date(2026, 7, 28),
        )

        result = import_avito_account_profile_daily_stats_task(
            self.avito_account.id,
            "2026-07-28",
        )

        sync_state.refresh_from_db()
        self.assertEqual(result["status"], "success")
        self.assertEqual(
            sync_state.status,
            AvitoStatsSyncState.Status.SUCCESS,
        )
        self.assertEqual(
            sync_state.coverage_to,
            date(2026, 7, 28),
        )
        self.assertTrue(result["backfill_queued"])
        profile_importer.assert_called_once_with(
            avito_account=self.avito_account,
            stat_date=date(2026, 7, 28),
        )
        enqueue_backfill.assert_called_once_with(
            avito_account=self.avito_account,
            target_date=date(2026, 7, 28),
        )

    @patch("analytics.tasks.enqueue_avito_stats_backfill")
    @patch(
        "analytics.tasks.import_avito_profile_daily_stats_for_account",
        side_effect=[
            SimpleNamespace(
                total_received=7,
                matched_listings=1,
                created_stats=1,
                updated_stats=0,
                deleted_zero_stats=0,
                confirmed_listings=1,
            ),
            SimpleNamespace(
                total_received=9,
                matched_listings=1,
                created_stats=0,
                updated_stats=1,
                deleted_zero_stats=0,
                confirmed_listings=1,
            ),
        ],
    )
    def test_profile_daily_task_catches_up_missed_days_in_order(
            self,
            profile_importer,
            enqueue_backfill,
    ):
        from analytics.tasks import (
            import_avito_account_profile_daily_stats_task,
        )

        enqueue_backfill.return_value = {
            "queued": True,
            "task_id": "backfill-task-id",
        }
        sync_state = AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.QUEUED,
            requested_date_from=date(2026, 7, 28),
            requested_date_to=date(2026, 7, 28),
            coverage_from=date(2026, 7, 1),
            coverage_to=date(2026, 7, 26),
        )

        result = import_avito_account_profile_daily_stats_task(
            self.avito_account.id,
            "2026-07-28",
        )

        self.assertEqual(
            profile_importer.call_args_list,
            [
                (
                    (),
                    {
                        "avito_account": self.avito_account,
                        "stat_date": date(2026, 7, 27),
                    },
                ),
                (
                    (),
                    {
                        "avito_account": self.avito_account,
                        "stat_date": date(2026, 7, 28),
                    },
                ),
            ],
        )
        enqueue_backfill.assert_called_once_with(
            avito_account=self.avito_account,
            target_date=date(2026, 7, 28),
        )

        sync_state.refresh_from_db()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["dates_processed"], 2)
        self.assertEqual(result["total_received"], 16)
        self.assertEqual(result["created_stats"], 1)
        self.assertEqual(result["updated_stats"], 1)
        self.assertEqual(
            sync_state.coverage_to,
            date(2026, 7, 28),
        )

    @patch("analytics.tasks.enqueue_avito_stats_backfill")
    def test_profile_daily_task_stops_between_days_when_superseded(
            self,
            enqueue_backfill,
    ):
        from analytics.tasks import (
            import_avito_account_profile_daily_stats_task,
        )

        stale_run_id = UUID(
            "00000000-0000-0000-0000-000000000041"
        )
        current_run_id = UUID(
            "00000000-0000-0000-0000-000000000042"
        )
        sync_state = AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.QUEUED,
            run_id=stale_run_id,
            requested_date_from=date(2026, 7, 28),
            requested_date_to=date(2026, 7, 28),
            coverage_from=date(2026, 7, 1),
            coverage_to=date(2026, 7, 26),
        )
        processed_dates = []

        def replace_owner_after_first_day(
                *,
                avito_account,
                stat_date,
        ):
            processed_dates.append(stat_date)

            if len(processed_dates) == 1:
                AvitoStatsSyncState.objects.filter(
                    pk=sync_state.pk,
                ).update(
                    status=AvitoStatsSyncState.Status.QUEUED,
                    run_id=current_run_id,
                    requested_date_from=date(2026, 7, 29),
                    requested_date_to=date(2026, 7, 29),
                    requested_at=datetime.now(tz=dt_timezone.utc),
                    started_at=None,
                    heartbeat_at=None,
                )

            return SimpleNamespace(
                total_received=1,
                matched_listings=1,
                created_stats=1,
                updated_stats=0,
                deleted_zero_stats=0,
                confirmed_listings=1,
            )

        with patch(
                "analytics.tasks.import_avito_profile_daily_stats_for_account",
                side_effect=replace_owner_after_first_day,
        ):
            result = import_avito_account_profile_daily_stats_task(
                self.avito_account.id,
                "2026-07-28",
                str(stale_run_id),
            )

        sync_state.refresh_from_db()
        self.assertEqual(result["status"], "superseded")
        self.assertEqual(
            processed_dates,
            [date(2026, 7, 27)],
        )
        self.assertEqual(
            sync_state.status,
            AvitoStatsSyncState.Status.QUEUED,
        )
        self.assertEqual(sync_state.run_id, current_run_id)
        enqueue_backfill.assert_not_called()

    @patch("analytics.tasks.enqueue_avito_stats_backfill")
    @patch(
        "analytics.tasks.import_avito_profile_daily_stats_for_account",
        side_effect=AvitoApiError("Profile stats unavailable"),
    )
    def test_profile_daily_task_marks_sync_error(
            self,
            profile_importer,
            enqueue_backfill,
    ):
        from analytics.tasks import (
            import_avito_account_profile_daily_stats_task,
        )

        sync_state = AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.QUEUED,
            requested_date_from=date(2026, 7, 28),
            requested_date_to=date(2026, 7, 28),
        )

        with self.assertRaises(AvitoApiError):
            import_avito_account_profile_daily_stats_task(
                self.avito_account.id,
                "2026-07-28",
            )

        sync_state.refresh_from_db()
        self.assertEqual(
            sync_state.status,
            AvitoStatsSyncState.Status.ERROR,
        )
        self.assertIn(
            "Profile stats unavailable",
            sync_state.error,
        )
        enqueue_backfill.assert_not_called()

    @patch(
        "analytics.tasks.import_avito_profile_daily_stats_for_account",
    )
    def test_profile_daily_task_does_not_run_during_active_v1_sync(
            self,
            profile_importer,
    ):
        from analytics.tasks import (
            import_avito_account_profile_daily_stats_task,
        )

        AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.RUNNING,
            started_at=datetime.now(tz=dt_timezone.utc),
        )

        result = import_avito_account_profile_daily_stats_task(
            self.avito_account.id,
            "2026-07-28",
        )

        self.assertEqual(result["status"], "skipped")
        profile_importer.assert_not_called()

    @patch("analytics.tasks.enqueue_avito_stats_backfill")
    @patch(
        "analytics.tasks.import_avito_profile_daily_stats_for_account",
        return_value=SimpleNamespace(
            total_received=1,
            matched_listings=1,
            created_stats=1,
            updated_stats=0,
            deleted_zero_stats=0,
            confirmed_listings=1,
        ),
    )
    def test_profile_daily_task_does_not_claim_superseded_run(
            self,
            profile_importer,
            enqueue_backfill,
    ):
        from analytics.tasks import (
            import_avito_account_profile_daily_stats_task,
        )

        current_run_id = UUID(
            "00000000-0000-0000-0000-000000000002"
        )
        stale_run_id = UUID(
            "00000000-0000-0000-0000-000000000001"
        )
        sync_state = AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.QUEUED,
            run_id=current_run_id,
            requested_date_from=date(2026, 7, 28),
            requested_date_to=date(2026, 7, 28),
        )

        result = import_avito_account_profile_daily_stats_task(
            self.avito_account.id,
            "2026-07-28",
            str(stale_run_id),
        )

        sync_state.refresh_from_db()
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(
            sync_state.status,
            AvitoStatsSyncState.Status.QUEUED,
        )
        self.assertEqual(sync_state.run_id, current_run_id)
        profile_importer.assert_not_called()
        enqueue_backfill.assert_not_called()

    @patch("analytics.tasks.enqueue_avito_stats_backfill")
    def test_profile_daily_task_cannot_finish_superseded_run(
            self,
            enqueue_backfill,
    ):
        from analytics.tasks import (
            import_avito_account_profile_daily_stats_task,
        )

        stale_run_id = UUID(
            "00000000-0000-0000-0000-000000000001"
        )
        current_run_id = UUID(
            "00000000-0000-0000-0000-000000000002"
        )
        sync_state = AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.QUEUED,
            run_id=stale_run_id,
            requested_date_from=date(2026, 7, 28),
            requested_date_to=date(2026, 7, 28),
        )

        def replace_owner_during_import(**kwargs):
            AvitoStatsSyncState.objects.filter(
                pk=sync_state.pk,
            ).update(
                status=AvitoStatsSyncState.Status.QUEUED,
                run_id=current_run_id,
                requested_date_from=date(2026, 7, 29),
                requested_date_to=date(2026, 7, 29),
                requested_at=datetime.now(tz=dt_timezone.utc),
                started_at=None,
            )
            return SimpleNamespace(
                total_received=1,
                matched_listings=1,
                created_stats=1,
                updated_stats=0,
                deleted_zero_stats=0,
                confirmed_listings=1,
            )

        with patch(
                "analytics.tasks.import_avito_profile_daily_stats_for_account",
                side_effect=replace_owner_during_import,
        ):
            result = import_avito_account_profile_daily_stats_task(
                self.avito_account.id,
                "2026-07-28",
                str(stale_run_id),
            )

        sync_state.refresh_from_db()
        self.assertEqual(result["status"], "superseded")
        self.assertEqual(
            sync_state.status,
            AvitoStatsSyncState.Status.QUEUED,
        )
        self.assertEqual(sync_state.run_id, current_run_id)
        self.assertEqual(
            sync_state.requested_date_from,
            date(2026, 7, 29),
        )
        self.assertEqual(
            sync_state.requested_date_to,
            date(2026, 7, 29),
        )
        self.assertIsNone(sync_state.coverage_from)
        self.assertIsNone(sync_state.coverage_to)
        self.assertIsNone(sync_state.last_successful_at)
        enqueue_backfill.assert_not_called()

    @patch("analytics.tasks.enqueue_avito_stats_backfill")
    def test_profile_daily_task_cannot_fail_superseded_run(
            self,
            enqueue_backfill,
    ):
        from analytics.tasks import (
            import_avito_account_profile_daily_stats_task,
        )

        stale_run_id = UUID(
            "00000000-0000-0000-0000-000000000001"
        )
        current_run_id = UUID(
            "00000000-0000-0000-0000-000000000002"
        )
        sync_state = AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.QUEUED,
            run_id=stale_run_id,
            requested_date_from=date(2026, 7, 28),
            requested_date_to=date(2026, 7, 28),
        )

        def replace_owner_and_fail(**kwargs):
            AvitoStatsSyncState.objects.filter(
                pk=sync_state.pk,
            ).update(
                status=AvitoStatsSyncState.Status.QUEUED,
                run_id=current_run_id,
                requested_date_from=date(2026, 7, 29),
                requested_date_to=date(2026, 7, 29),
                requested_at=datetime.now(tz=dt_timezone.utc),
                started_at=None,
            )
            raise AvitoApiError("Stale profile run failed")

        with patch(
                "analytics.tasks.import_avito_profile_daily_stats_for_account",
                side_effect=replace_owner_and_fail,
        ):
            with self.assertRaises(AvitoApiError):
                import_avito_account_profile_daily_stats_task(
                    self.avito_account.id,
                    "2026-07-28",
                    str(stale_run_id),
                )

        sync_state.refresh_from_db()
        self.assertEqual(
            sync_state.status,
            AvitoStatsSyncState.Status.QUEUED,
        )
        self.assertEqual(sync_state.run_id, current_run_id)
        self.assertEqual(
            sync_state.requested_date_from,
            date(2026, 7, 29),
        )
        self.assertEqual(
            sync_state.requested_date_to,
            date(2026, 7, 29),
        )
        self.assertIsNone(sync_state.finished_at)
        self.assertEqual(sync_state.error, "")
        enqueue_backfill.assert_not_called()

    @patch(
        "analytics.tasks.backfill_missing_avito_listing_stats_task.delay",
    )
    def test_backfill_enqueue_uses_target_day(
            self,
            delay,
    ):
        from analytics.tasks import enqueue_avito_stats_backfill

        delay.return_value.id = "backfill-task-id"

        AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.SUCCESS,
            coverage_from=date(2026, 7, 28),
            coverage_to=date(2026, 7, 28),
        )

        result = enqueue_avito_stats_backfill(
            avito_account=self.avito_account,
            target_date=date(2026, 7, 28),
        )

        sync_state = AvitoStatsSyncState.objects.get(
            avito_account=self.avito_account,
        )
        self.assertTrue(result["queued"])
        self.assertEqual(result["task_id"], "backfill-task-id")
        self.assertEqual(
            sync_state.status,
            AvitoStatsSyncState.Status.QUEUED,
        )
        self.assertEqual(
            sync_state.requested_date_from,
            date(2026, 7, 28),
        )
        self.assertEqual(
            sync_state.requested_date_to,
            date(2026, 7, 28),
        )
        delay.assert_called_once()
        task_args = delay.call_args.args
        self.assertEqual(len(task_args), 3)
        self.assertEqual(
            task_args[:2],
            (
                self.avito_account.id,
                "2026-07-28",
            ),
        )
        run_id = UUID(task_args[2])
        self.assertEqual(sync_state.run_id, run_id)
        self.assertIsNone(sync_state.heartbeat_at)

    @patch(
        "analytics.tasks.build_avito_stats_backfill_plan",
        return_value=[],
    )
    def test_backfill_task_finishes_its_owned_run(
            self,
            build_plan,
    ):
        from analytics.tasks import (
            backfill_missing_avito_listing_stats_task,
        )

        run_id = UUID(
            "00000000-0000-0000-0000-000000000021"
        )
        sync_state = AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.QUEUED,
            run_id=run_id,
            requested_date_from=date(2026, 7, 28),
            requested_date_to=date(2026, 7, 28),
        )

        result = backfill_missing_avito_listing_stats_task(
            self.avito_account.id,
            "2026-07-28",
            str(run_id),
        )

        sync_state.refresh_from_db()
        self.assertEqual(result["status"], "success")
        self.assertEqual(
            sync_state.status,
            AvitoStatsSyncState.Status.SUCCESS,
        )
        self.assertEqual(sync_state.run_id, run_id)
        self.assertEqual(
            sync_state.coverage_to,
            date(2026, 7, 28),
        )
        build_plan.assert_called_once_with(
            avito_account=self.avito_account,
            target_date=date(2026, 7, 28),
        )

    @patch(
        "analytics.tasks.build_avito_stats_backfill_plan",
        side_effect=AvitoApiError("Owned backfill failed"),
    )
    def test_backfill_task_marks_error_only_for_its_owned_run(
            self,
            build_plan,
    ):
        from analytics.tasks import (
            backfill_missing_avito_listing_stats_task,
        )

        run_id = UUID(
            "00000000-0000-0000-0000-000000000022"
        )
        sync_state = AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.QUEUED,
            run_id=run_id,
            requested_date_from=date(2026, 7, 28),
            requested_date_to=date(2026, 7, 28),
        )

        with self.assertRaises(AvitoApiError):
            backfill_missing_avito_listing_stats_task(
                self.avito_account.id,
                "2026-07-28",
                str(run_id),
            )

        sync_state.refresh_from_db()
        self.assertEqual(
            sync_state.status,
            AvitoStatsSyncState.Status.ERROR,
        )
        self.assertEqual(sync_state.run_id, run_id)
        self.assertIn("Owned backfill failed", sync_state.error)

    @patch("analytics.tasks.build_avito_stats_backfill_plan")
    def test_backfill_task_stops_between_batches_when_superseded(
            self,
            build_plan,
    ):
        from analytics.tasks import (
            backfill_missing_avito_listing_stats_task,
        )

        stale_run_id = UUID(
            "00000000-0000-0000-0000-000000000051"
        )
        current_run_id = UUID(
            "00000000-0000-0000-0000-000000000052"
        )
        build_plan.return_value = [
            SimpleNamespace(
                date_from=date(2026, 7, 1),
                date_to=date(2026, 7, 10),
                listing_ids=(self.listing.id,),
            ),
            SimpleNamespace(
                date_from=date(2026, 7, 20),
                date_to=date(2026, 7, 27),
                listing_ids=(self.listing.id,),
            ),
        ]
        sync_state = AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.QUEUED,
            run_id=stale_run_id,
            requested_date_from=date(2026, 7, 28),
            requested_date_to=date(2026, 7, 28),
        )
        processed_ranges = []

        def replace_owner_after_first_batch(
                *,
                avito_account,
                date_from,
                date_to,
                listing_ids,
                progress_callback,
        ):
            processed_ranges.append((date_from, date_to))

            if len(processed_ranges) == 1:
                AvitoStatsSyncState.objects.filter(
                    pk=sync_state.pk,
                ).update(
                    status=AvitoStatsSyncState.Status.QUEUED,
                    run_id=current_run_id,
                    requested_date_from=date(2026, 7, 29),
                    requested_date_to=date(2026, 7, 29),
                    requested_at=datetime.now(tz=dt_timezone.utc),
                    started_at=None,
                    heartbeat_at=None,
                )

            return SimpleNamespace(
                total_listings=1,
                total_days=10,
                created_stats=1,
                updated_stats=0,
                unchanged_stats=9,
            )

        with patch(
                "analytics.tasks.import_avito_listing_daily_stats_for_account",
                side_effect=replace_owner_after_first_batch,
        ):
            result = backfill_missing_avito_listing_stats_task(
                self.avito_account.id,
                "2026-07-28",
                str(stale_run_id),
            )

        sync_state.refresh_from_db()
        self.assertEqual(result["status"], "superseded")
        self.assertEqual(
            processed_ranges,
            [(date(2026, 7, 1), date(2026, 7, 10))],
        )
        self.assertEqual(
            sync_state.status,
            AvitoStatsSyncState.Status.QUEUED,
        )
        self.assertEqual(sync_state.run_id, current_run_id)

    @patch(
        "analytics.tasks.import_avito_listing_daily_stats_for_account",
        side_effect=[
            SimpleNamespace(
                total_listings=1,
                total_days=10,
                created_stats=2,
                updated_stats=0,
                unchanged_stats=8,
            ),
            SimpleNamespace(
                total_listings=1,
                total_days=8,
                created_stats=1,
                updated_stats=1,
                unchanged_stats=6,
            ),
        ],
    )
    @patch("analytics.tasks.build_avito_stats_backfill_plan")
    def test_backfill_task_executes_plan_in_order(
            self,
            build_plan,
            v1_importer,
    ):
        from analytics.tasks import (
            backfill_missing_avito_listing_stats_task,
        )

        build_plan.return_value = [
            SimpleNamespace(
                date_from=date(2026, 7, 1),
                date_to=date(2026, 7, 10),
                listing_ids=(self.listing.id,),
            ),
            SimpleNamespace(
                date_from=date(2026, 7, 20),
                date_to=date(2026, 7, 27),
                listing_ids=(self.listing.id,),
            ),
        ]
        AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.QUEUED,
            requested_date_from=date(2026, 7, 28),
            requested_date_to=date(2026, 7, 28),
        )

        result = backfill_missing_avito_listing_stats_task(
            self.avito_account.id,
            "2026-07-28",
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["requests_processed"], 2)
        self.assertEqual(result["unchanged_stats"], 14)
        build_plan.assert_called_once_with(
            avito_account=self.avito_account,
            target_date=date(2026, 7, 28),
        )

        processed_requests = [
            (
                call.kwargs["date_from"],
                call.kwargs["date_to"],
                call.kwargs["listing_ids"],
            )
            for call in v1_importer.call_args_list
        ]
        self.assertEqual(
            processed_requests,
            [
                (
                    date(2026, 7, 1),
                    date(2026, 7, 10),
                    [self.listing.id],
                ),
                (
                    date(2026, 7, 20),
                    date(2026, 7, 27),
                    [self.listing.id],
                ),
            ],
        )

        sync_state = AvitoStatsSyncState.objects.get(
            avito_account=self.avito_account,
        )
        self.assertEqual(
            sync_state.status,
            AvitoStatsSyncState.Status.SUCCESS,
        )
        self.assertEqual(
            sync_state.coverage_to,
            date(2026, 7, 28),
        )

    @override_settings(AVITO_STATS_HISTORY_DAYS=27)
    @patch(
        "analytics.tasks.import_avito_listing_daily_stats_for_account",
    )
    def test_empty_backfill_plan_finishes_successfully(
            self,
            v1_importer,
    ):
        from analytics.tasks import (
            backfill_missing_avito_listing_stats_task,
        )

        AvitoListingStatsCoverage.objects.create(
            workspace=self.workspace,
            listing=self.listing,
            coverage_from=date(2026, 7, 1),
            finalized_through=date(2026, 7, 28),
        )
        AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.QUEUED,
            requested_date_from=date(2026, 7, 28),
            requested_date_to=date(2026, 7, 28),
        )

        result = backfill_missing_avito_listing_stats_task(
            self.avito_account.id,
            "2026-07-28",
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["requests_processed"], 0)
        v1_importer.assert_not_called()

        sync_state = AvitoStatsSyncState.objects.get(
            avito_account=self.avito_account,
        )
        self.assertEqual(
            sync_state.status,
            AvitoStatsSyncState.Status.SUCCESS,
        )

    @patch(
        "analytics.tasks.import_avito_listing_daily_stats_for_account",
        side_effect=AvitoApiError("Backfill unavailable"),
    )
    @patch("analytics.tasks.build_avito_stats_backfill_plan")
    def test_failed_backfill_preserves_profile_day_data(
            self,
            build_plan,
            v1_importer,
    ):
        from analytics.tasks import (
            backfill_missing_avito_listing_stats_task,
        )

        profile_stat = AvitoListingDailyStats.objects.create(
            workspace=self.workspace,
            listing=self.listing,
            date=date(2026, 7, 28),
            views=15,
            contacts=3,
            raw_metrics={
                "stats_v2": {
                    "views": 15,
                    "contacts": 3,
                },
            },
        )
        coverage = AvitoListingStatsCoverage.objects.create(
            workspace=self.workspace,
            listing=self.listing,
            coverage_from=date(2026, 7, 28),
            finalized_through=date(2026, 7, 28),
        )
        AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.QUEUED,
            requested_date_from=date(2026, 7, 28),
            requested_date_to=date(2026, 7, 28),
        )
        build_plan.return_value = [
            SimpleNamespace(
                date_from=date(2026, 7, 1),
                date_to=date(2026, 7, 27),
                listing_ids=(self.listing.id,),
            ),
        ]

        with self.assertRaises(AvitoApiError):
            backfill_missing_avito_listing_stats_task(
                self.avito_account.id,
                "2026-07-28",
            )

        profile_stat.refresh_from_db()
        coverage.refresh_from_db()
        sync_state = AvitoStatsSyncState.objects.get(
            avito_account=self.avito_account,
        )

        self.assertEqual(profile_stat.views, 15)
        self.assertEqual(profile_stat.contacts, 3)
        self.assertEqual(
            coverage.coverage_from,
            date(2026, 7, 28),
        )
        self.assertEqual(
            coverage.finalized_through,
            date(2026, 7, 28),
        )
        self.assertEqual(
            sync_state.status,
            AvitoStatsSyncState.Status.ERROR,
        )
        self.assertIn("Backfill unavailable", sync_state.error)

    @patch("analytics.tasks.build_avito_stats_backfill_plan")
    def test_backfill_task_does_not_run_during_active_sync(
            self,
            build_plan,
    ):
        from analytics.tasks import (
            backfill_missing_avito_listing_stats_task,
        )

        AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.RUNNING,
            started_at=datetime.now(tz=dt_timezone.utc),
        )

        result = backfill_missing_avito_listing_stats_task(
            self.avito_account.id,
            "2026-07-28",
        )

        self.assertEqual(result["status"], "skipped")
        build_plan.assert_not_called()


class AvitoStatsV1BatchImportTests(TestCase):
    def test_listing_query_loads_only_fields_required_for_stats(self):
        expected_loaded_fields = {
            "id",
            "workspace_id",
            "avito_account_id",
            "avito_id",
            "published_at",
        }

        with CaptureQueriesContext(connection) as queries:
            listings = get_listings_for_stats(self.avito_account)

            self.assertEqual(len(listings), 1)

            listing = listings[0]

            # Обращение к разрешённым полям не должно создавать
            # дополнительные запросы к отложенным полям.
            required_values = (
                listing.id,
                listing.workspace_id,
                listing.avito_account_id,
                listing.avito_id,
                listing.published_at,
            )

            loaded_fields = {
                field.attname
                for field in listing._meta.concrete_fields
                if field.attname in listing.__dict__
            }

        self.assertEqual(len(queries), 1)
        self.assertEqual(loaded_fields, expected_loaded_fields)
        self.assertEqual(required_values[0], self.listing.id)

        deferred_fields = listing.get_deferred_fields()

        self.assertTrue(
            {
                "description",
                "image_urls",
                "base_data",
                "option_data",
                "raw_data",
                "unmapped_data",
                "imported_payload",
            }.issubset(deferred_fields)
        )

    def setUp(self):
        self.user = User.objects.create_user(
            email="analytics-v1-batch-owner@example.com",
            password="test",
        )
        self.workspace = Workspace.objects.create(
            name="Analytics v1 batch workspace",
            slug="analytics-v1-batch-workspace",
            owner=self.user,
        )
        self.avito_account = AvitoAccount.objects.create(
            workspace=self.workspace,
            name="Analytics v1 batch account",
            external_account_id="94235341",
        )
        AvitoOAuthToken.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            access_token="analytics-v1-batch-access-token",
            refresh_token="analytics-v1-batch-refresh-token",
            scope="stats:read",
        )
        self.listing = AvitoListing.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            avito_id="24122501",
            status="active",
            title="Analytics v1 batch listing",
        )

    def test_imports_200_daily_rows_with_bounded_query_count(self):
        first_day = date(2026, 1, 1)
        stats = [
            self.v1_stat(
                first_day + timedelta(days=offset),
                views=offset + 1,
                contacts=offset % 5,
                favorites=offset % 3,
                calls=offset % 2,
                messages=offset % 4,
            )
            for offset in range(200)
        ]

        with patch(
                "analytics.services.avito_stats.AvitoApiClient.get_item_stats",
                return_value=self.v1_payload(stats),
        ):
            with CaptureQueriesContext(connection) as queries:
                result = self.import_stats(
                    date_from=first_day,
                    date_to=first_day + timedelta(days=199),
                )

        self.assertLessEqual(
            len(queries),
            25,
            (
                "Импорт 200 дневных строк не должен выполнять "
                "построчные SELECT/INSERT/UPDATE."
            ),
        )
        self.assertEqual(result.total_days, 200)
        self.assertEqual(result.created_stats, 200)
        self.assertEqual(result.updated_stats, 0)
        self.assertEqual(result.unchanged_stats, 0)
        self.assertEqual(
            AvitoListingDailyStats.objects.filter(
                listing=self.listing,
            ).count(),
            200,
        )

    def test_identical_reimport_does_not_update_daily_rows(self):
        first_day = date(2026, 1, 1)
        stats = [
            self.v1_stat(
                first_day + timedelta(days=offset),
                views=offset + 1,
                contacts=offset % 5,
            )
            for offset in range(200)
        ]
        payload = self.v1_payload(stats)

        with patch(
                "analytics.services.avito_stats.AvitoApiClient.get_item_stats",
                return_value=payload,
        ):
            first_result = self.import_stats(
                date_from=first_day,
                date_to=first_day + timedelta(days=199),
            )

        updated_at_before = dict(
            AvitoListingDailyStats.objects.filter(
                listing=self.listing,
            ).values_list("date", "updated_at")
        )

        with patch(
                "analytics.services.avito_stats.AvitoApiClient.get_item_stats",
                return_value=payload,
        ):
            second_result = self.import_stats(
                date_from=first_day,
                date_to=first_day + timedelta(days=199),
            )

        updated_at_after = dict(
            AvitoListingDailyStats.objects.filter(
                listing=self.listing,
            ).values_list("date", "updated_at")
        )

        self.assertEqual(first_result.created_stats, 200)
        self.assertEqual(first_result.updated_stats, 0)
        self.assertEqual(first_result.unchanged_stats, 0)
        self.assertEqual(second_result.created_stats, 0)
        self.assertEqual(second_result.updated_stats, 0)
        self.assertEqual(second_result.unchanged_stats, 200)
        self.assertEqual(updated_at_after, updated_at_before)
        self.assertEqual(
            AvitoListingDailyStats.objects.filter(
                listing=self.listing,
            ).count(),
            200,
        )

    def test_mixed_batch_creates_updates_and_skips_unchanged_rows(self):
        unchanged_day = date(2026, 5, 1)
        changed_day = date(2026, 5, 2)
        created_day = date(2026, 5, 3)

        unchanged_raw_metrics = self.v1_stat(
            unchanged_day,
            views=10,
            contacts=2,
            favorites=1,
            calls=1,
            messages=1,
        )
        unchanged_raw_metrics.update({
            "stats_v2": {"views": 10, "contacts": 2},
            "custom_metric": "keep-me",
        })
        unchanged = AvitoListingDailyStats.objects.create(
            workspace=self.workspace,
            listing=self.listing,
            date=unchanged_day,
            views=10,
            contacts=2,
            favorites=1,
            calls=1,
            messages=1,
            total_spend=Decimal("12.50"),
            raw_metrics=unchanged_raw_metrics,
        )

        changed = AvitoListingDailyStats.objects.create(
            workspace=self.workspace,
            listing=self.listing,
            date=changed_day,
            views=1,
            contacts=1,
            favorites=1,
            calls=1,
            messages=1,
            total_spend=Decimal("99.90"),
            raw_metrics={
                "stats_v2": {"views": 20, "contacts": 3},
                "custom_metric": "keep-me-too",
            },
        )

        unchanged_updated_at = unchanged.updated_at
        changed_updated_at = changed.updated_at
        payload = self.v1_payload([
            self.v1_stat(
                unchanged_day,
                views=10,
                contacts=2,
                favorites=1,
                calls=1,
                messages=1,
            ),
            self.v1_stat(
                changed_day,
                views=20,
                contacts=3,
                favorites=4,
                calls=5,
                messages=6,
            ),
            self.v1_stat(
                created_day,
                views=30,
                contacts=4,
                favorites=5,
                calls=6,
                messages=7,
            ),
        ])

        with patch(
                "analytics.services.avito_stats.AvitoApiClient.get_item_stats",
                return_value=payload,
        ):
            result = self.import_stats(
                date_from=unchanged_day,
                date_to=created_day,
            )

        unchanged.refresh_from_db()
        changed.refresh_from_db()
        created = AvitoListingDailyStats.objects.get(
            listing=self.listing,
            date=created_day,
        )

        self.assertEqual(result.total_days, 3)
        self.assertEqual(result.created_stats, 1)
        self.assertEqual(result.updated_stats, 1)
        self.assertEqual(result.unchanged_stats, 1)

        self.assertEqual(unchanged.updated_at, unchanged_updated_at)
        self.assertEqual(unchanged.total_spend, Decimal("12.50"))
        self.assertEqual(
            unchanged.raw_metrics["stats_v2"],
            {"views": 10, "contacts": 2},
        )
        self.assertEqual(
            unchanged.raw_metrics["custom_metric"],
            "keep-me",
        )

        self.assertGreater(changed.updated_at, changed_updated_at)
        self.assertEqual(changed.views, 20)
        self.assertEqual(changed.contacts, 3)
        self.assertEqual(changed.favorites, 4)
        self.assertEqual(changed.calls, 5)
        self.assertEqual(changed.messages, 6)
        self.assertEqual(changed.total_spend, Decimal("99.90"))
        self.assertEqual(
            changed.raw_metrics["stats_v2"],
            {"views": 20, "contacts": 3},
        )
        self.assertEqual(
            changed.raw_metrics["custom_metric"],
            "keep-me-too",
        )
        self.assertEqual(changed.raw_metrics["uniqViews"], 20)

        self.assertEqual(created.views, 30)
        self.assertIsNone(created.total_spend)
        self.assertEqual(created.raw_metrics["uniqContacts"], 4)

    def test_invalid_row_rolls_back_the_whole_api_response(self):
        first_day = date(2026, 5, 1)
        payload = self.v1_payload([
            self.v1_stat(first_day, views=10, contacts=2),
            {
                "date": "not-a-date",
                "uniqViews": 20,
                "uniqContacts": 3,
            },
        ])

        with patch(
                "analytics.services.avito_stats.AvitoApiClient.get_item_stats",
                return_value=payload,
        ):
            with self.assertRaises(ValueError):
                self.import_stats(
                    date_from=first_day,
                    date_to=first_day + timedelta(days=1),
                )

        self.assertFalse(
            AvitoListingDailyStats.objects.filter(
                listing=self.listing,
            ).exists()
        )
        coverage = AvitoListingStatsCoverage.objects.get(
            listing=self.listing,
        )
        self.assertIsNone(coverage.coverage_from)
        self.assertIsNone(coverage.finalized_through)
        self.assertTrue(coverage.error)

    def test_profile_coverage_uses_one_set_based_update(self):
        from analytics.services.avito_stats import (
            update_listing_coverages_for_profile_day,
        )
        from django.utils import timezone

        AvitoListing.objects.bulk_create([
            AvitoListing(
                workspace=self.workspace,
                avito_account=self.avito_account,
                avito_id=str(40_000_000 + index),
                status="active",
                title=f"Analytics coverage batch listing {index}",
            )
            for index in range(500)
        ])
        listings = list(
            AvitoListing.objects.filter(
                avito_account=self.avito_account,
            ).order_by("id")
        )
        bulk_create_batch_sizes = []
        bulk_update_batch_sizes = []
        original_bulk_create = QuerySet.bulk_create
        original_bulk_update = QuerySet.bulk_update

        def tracked_bulk_create(queryset, objs, **kwargs):
            if queryset.model is AvitoListingStatsCoverage:
                bulk_create_batch_sizes.append(
                    kwargs.get("batch_size")
                )
            return original_bulk_create(queryset, objs, **kwargs)

        def tracked_bulk_update(queryset, objs, fields, **kwargs):
            if queryset.model is AvitoListingStatsCoverage:
                bulk_update_batch_sizes.append(
                    kwargs.get("batch_size")
                )
            return original_bulk_update(
                queryset,
                objs,
                fields,
                **kwargs,
            )

        with CaptureQueriesContext(connection) as queries:
            with (
                patch.object(QuerySet, "bulk_create", tracked_bulk_create),
                patch.object(QuerySet, "bulk_update", tracked_bulk_update),
            ):
                update_listing_coverages_for_profile_day(
                    workspace=self.workspace,
                    listings=listings,
                    stat_date=date(2026, 7, 28),
                    now=timezone.now(),
                )

        coverage_table = (
            AvitoListingStatsCoverage._meta.db_table
        )
        coverage_updates = [
            query["sql"]
            for query in queries
            if (
                    query["sql"].lstrip().upper().startswith("UPDATE")
                    and coverage_table in query["sql"]
            )
        ]

        self.assertEqual(len(listings), 501)
        self.assertEqual(bulk_create_batch_sizes, [500])
        self.assertEqual(bulk_update_batch_sizes, [])
        self.assertEqual(len(coverage_updates), 1)
        self.assertEqual(
            AvitoListingStatsCoverage.objects.filter(
                workspace=self.workspace,
                coverage_from=date(2026, 7, 28),
                finalized_through=date(2026, 7, 28),
            ).count(),
            501,
        )

    def test_set_based_profile_coverage_preserves_range_semantics(self):
        from analytics.services.avito_stats import (
            update_listing_coverages_for_profile_day,
        )

        stat_date = date(2026, 7, 28)
        now = datetime(
            2026,
            7,
            29,
            4,
            10,
            tzinfo=dt_timezone.utc,
        )
        previous_success = datetime(
            2026,
            7,
            27,
            4,
            10,
            tzinfo=dt_timezone.utc,
        )
        branch_listings = {
            branch: AvitoListing.objects.create(
                workspace=self.workspace,
                avito_account=self.avito_account,
                avito_id=str(50_000_000 + index),
                status="active",
                title=f"Coverage branch {branch}",
            )
            for index, branch in enumerate(
                ("prepend", "inside", "append", "gap"),
            )
        }
        AvitoListingStatsCoverage.objects.bulk_create([
            AvitoListingStatsCoverage(
                workspace=self.workspace,
                listing=branch_listings["prepend"],
                coverage_from=date(2026, 7, 29),
                finalized_through=date(2026, 8, 2),
                error="old error",
            ),
            AvitoListingStatsCoverage(
                workspace=self.workspace,
                listing=branch_listings["inside"],
                coverage_from=date(2026, 7, 20),
                finalized_through=date(2026, 7, 30),
                error="old error",
            ),
            AvitoListingStatsCoverage(
                workspace=self.workspace,
                listing=branch_listings["append"],
                coverage_from=date(2026, 7, 20),
                finalized_through=date(2026, 7, 27),
                error="old error",
            ),
            AvitoListingStatsCoverage(
                workspace=self.workspace,
                listing=branch_listings["gap"],
                coverage_from=date(2026, 7, 10),
                finalized_through=date(2026, 7, 20),
                last_successful_at=previous_success,
                error="",
            ),
        ])

        listings = [
            self.listing,
            *branch_listings.values(),
        ]
        update_listing_coverages_for_profile_day(
            workspace=self.workspace,
            listings=listings,
            stat_date=stat_date,
            now=now,
        )
        coverages = {
            coverage.listing_id: coverage
            for coverage in AvitoListingStatsCoverage.objects.filter(
                listing_id__in=[
                    listing.id
                    for listing in listings
                ],
            )
        }

        new_coverage = coverages[self.listing.id]
        self.assertEqual(new_coverage.coverage_from, stat_date)
        self.assertEqual(new_coverage.finalized_through, stat_date)
        self.assertEqual(new_coverage.last_successful_at, now)

        prepend = coverages[branch_listings["prepend"].id]
        self.assertEqual(prepend.coverage_from, stat_date)
        self.assertEqual(
            prepend.finalized_through,
            date(2026, 8, 2),
        )
        self.assertEqual(prepend.last_successful_at, now)
        self.assertEqual(prepend.error, "")

        inside = coverages[branch_listings["inside"].id]
        self.assertEqual(inside.coverage_from, date(2026, 7, 20))
        self.assertEqual(
            inside.finalized_through,
            date(2026, 7, 30),
        )
        self.assertEqual(inside.last_successful_at, now)
        self.assertEqual(inside.error, "")

        append = coverages[branch_listings["append"].id]
        self.assertEqual(append.coverage_from, date(2026, 7, 20))
        self.assertEqual(append.finalized_through, stat_date)
        self.assertEqual(append.last_successful_at, now)
        self.assertEqual(append.error, "")

        gap = coverages[branch_listings["gap"].id]
        self.assertEqual(gap.coverage_from, date(2026, 7, 10))
        self.assertEqual(
            gap.finalized_through,
            date(2026, 7, 20),
        )
        self.assertEqual(
            gap.last_successful_at,
            previous_success,
        )
        self.assertEqual(gap.last_attempted_at, now)
        self.assertIn("пропущенного диапазона", gap.error)
        self.assertIn("2026-07-10..2026-07-20", gap.error)

    def import_stats(self, *, date_from, date_to):
        return import_avito_listing_daily_stats_for_account(
            avito_account=self.avito_account,
            date_from=date_from,
            date_to=date_to,
        )

    def v1_payload(self, stats):
        return {
            "result": {
                "items": [
                    {
                        "itemId": self.listing.avito_id,
                        "stats": stats,
                    },
                ],
            },
        }

    @staticmethod
    def v1_stat(
            stat_date,
            *,
            views,
            contacts,
            favorites=0,
            calls=0,
            messages=0,
    ):
        return {
            "date": stat_date.isoformat(),
            "uniqViews": views,
            "uniqContacts": contacts,
            "uniqFavorites": favorites,
            "calls": calls,
            "messages": messages,
        }


class AvitoListingStatsCoverageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="analytics-coverage-owner@example.com",
            password="test",
        )
        self.workspace = Workspace.objects.create(
            name="Analytics coverage workspace",
            slug="analytics-coverage-workspace",
            owner=self.user,
        )
        self.avito_account = AvitoAccount.objects.create(
            workspace=self.workspace,
            name="Analytics coverage account",
            external_account_id="94235321",
        )
        self.listing = AvitoListing.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            avito_id="24122301",
            status="active",
            title="Analytics coverage listing",
        )
        self.item = {
            "avito_listing_id": self.listing.id,
            "avito_id": self.listing.avito_id,
        }

    def test_generic_coverage_confirms_base_zero_but_not_spending(self):
        self.create_coverage(
            coverage_from=date(2026, 7, 1),
            finalized_through=date(2026, 7, 28),
        )

        stats = self.get_stats_for_day(date(2026, 7, 28))

        self.assertEqual(stats["status"], "ready")
        self.assertEqual(stats["views"], 0)
        self.assertEqual(stats["contacts"], 0)
        self.assertEqual(stats["favorites"], 0)
        self.assertIs(stats.get("spend_complete"), False)
        self.assertIsNone(stats["total_spend"])
        self.assertIsNone(stats["views_to_contacts_conversion"])

    def test_day_outside_listing_coverage_is_not_reported_as_zero(self):
        AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.SUCCESS,
            coverage_from=date(2026, 7, 1),
            coverage_to=date(2026, 7, 28),
            last_successful_at=datetime(
                2026,
                7,
                29,
                4,
                10,
                tzinfo=dt_timezone.utc,
            ),
        )
        self.create_coverage(
            coverage_from=date(2026, 7, 1),
            finalized_through=date(2026, 7, 28),
        )

        stats = self.get_stats_for_day(date(2026, 7, 29))

        self.assertEqual(stats["status"], "processing")
        self.assertIsNone(stats["views"])
        self.assertIsNone(stats["contacts"])
        self.assertIsNone(stats["favorites"])
        self.assertIs(stats.get("spend_complete"), False)
        self.assertIsNone(stats["total_spend"])
        self.assertIsNone(stats["views_to_contacts_conversion"])

    def test_generic_coverage_does_not_confirm_daily_spending(self):
        requested_day = date(2026, 7, 28)
        self.create_coverage(
            coverage_from=date(2026, 7, 1),
            finalized_through=requested_day,
        )
        AvitoListingDailyStats.objects.create(
            workspace=self.workspace,
            listing=self.listing,
            date=requested_day,
            views=7,
            contacts=2,
            favorites=3,
            total_spend=Decimal("12.50"),
        )

        stats = self.get_stats_for_day(requested_day)

        self.assertEqual(stats["status"], "ready")
        self.assertEqual(stats["views"], 7)
        self.assertEqual(stats["contacts"], 2)
        self.assertEqual(stats["favorites"], 3)
        self.assertIs(stats.get("spend_complete"), False)
        self.assertIsNone(stats["total_spend"])
        self.assertEqual(
            stats["views_to_contacts_conversion"],
            "28.57",
        )

    def test_unavailable_listing_returns_stable_empty_stats_shape(self):
        payload = build_avito_ads_stats_payload(
            workspace=self.workspace,
            avito_account=self.avito_account,
            items=[{
                "avito_listing_id": None,
                "avito_id": "",
            }],
        )

        stats = payload["results"][0]["stats"]

        self.assertEqual(stats["status"], "unavailable")
        self.assertIsNone(stats["views"])
        self.assertIsNone(stats["contacts"])
        self.assertIsNone(stats["favorites"])
        self.assertIs(stats.get("spend_complete"), False)
        self.assertIsNone(stats["total_spend"])
        self.assertIsNone(stats["views_to_contacts_conversion"])

    def create_coverage(self, *, coverage_from, finalized_through):
        coverage_model = apps.get_model(
            "analytics",
            "AvitoListingStatsCoverage",
        )
        return coverage_model.objects.create(
            workspace=self.workspace,
            listing=self.listing,
            coverage_from=coverage_from,
            finalized_through=finalized_through,
        )

    def get_stats_for_day(self, requested_day):
        payload = build_avito_ads_stats_payload(
            workspace=self.workspace,
            avito_account=self.avito_account,
            items=[self.item],
            date_from=requested_day,
            date_to=requested_day,
        )
        return payload["results"][0]["stats"]


class AvitoProfileDailyStatsImportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="analytics-v2-owner@example.com",
            password="test",
        )
        self.workspace = Workspace.objects.create(
            name="Analytics v2 workspace",
            slug="analytics-v2-workspace",
            owner=self.user,
        )
        self.avito_account = AvitoAccount.objects.create(
            workspace=self.workspace,
            name="Analytics v2 account",
            external_account_id="94235331",
        )
        AvitoOAuthToken.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            access_token="analytics-v2-access-token",
            refresh_token="analytics-v2-refresh-token",
            scope="stats:read",
        )
        self.listing_with_activity = AvitoListing.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            avito_id="24122401",
            status="active",
            title="Analytics v2 active listing",
        )
        self.listing_without_activity = AvitoListing.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            avito_id="24122402",
            status="active",
            title="Analytics v2 zero listing",
        )
        self.requested_day = date(2026, 7, 28)

    @override_settings(AVITO_STATS_V2_PAGE_SIZE=2)
    @patch(
        "analytics.services.avito_stats.AvitoApiClient.get_item_analytics",
    )
    def test_v2_import_paginates_saves_activity_and_confirms_zero(
            self,
            get_item_analytics,
    ):
        get_item_analytics.side_effect = [
            {
                "result": {
                    "dataTotalCount": 3,
                    "groupings": [
                        self.v2_grouping(
                            self.listing_with_activity.avito_id,
                            views=12,
                            contacts=1,
                            favorites=3,
                            all_spending=1250,
                        ),
                        self.v2_grouping(
                            "99999901",
                            views=5,
                            contacts=1,
                        ),
                    ],
                },
            },
            {
                "result": {
                    "dataTotalCount": 3,
                    "groupings": [
                        self.v2_grouping(
                            "99999902",
                            views=3,
                            contacts=0,
                        ),
                    ],
                },
            },
        ]

        self.import_profile_day()

        calls = get_item_analytics.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].kwargs["limit"], 2)
        self.assertEqual(calls[0].kwargs["offset"], 0)
        self.assertEqual(calls[1].kwargs["limit"], 2)
        self.assertEqual(calls[1].kwargs["offset"], 2)
        self.assertEqual(calls[0].kwargs["grouping"], "item")
        self.assertEqual(
            calls[0].kwargs["metrics"],
            [
                "views",
                "contacts",
                "favorites",
                "allSpending",
            ],
        )

        stat = AvitoListingDailyStats.objects.get(
            listing=self.listing_with_activity,
            date=self.requested_day,
        )
        self.assertEqual(stat.views, 12)
        self.assertEqual(stat.contacts, 1)
        self.assertEqual(stat.favorites, 3)
        self.assertEqual(stat.total_spend, Decimal("12.50"))
        self.assertEqual(
            stat.raw_metrics["stats_v2"],
            {
                "views": 12,
                "contacts": 1,
                "favorites": 3,
                "allSpending": 1250,
            },
        )
        self.assertFalse(
            AvitoListingDailyStats.objects.filter(
                listing=self.listing_without_activity,
                date=self.requested_day,
            ).exists()
        )

        coverages = {
            coverage.listing_id: coverage
            for coverage in AvitoListingStatsCoverage.objects.filter(
                listing__in=[
                    self.listing_with_activity,
                    self.listing_without_activity,
                ],
            )
        }
        self.assertEqual(
            coverages[
                self.listing_with_activity.id
            ].coverage_from,
            self.requested_day,
        )
        self.assertEqual(
            coverages[
                self.listing_without_activity.id
            ].finalized_through,
            self.requested_day,
        )
        self.assertEqual(
            coverages[
                self.listing_with_activity.id
            ].spending_coverage_from,
            self.requested_day,
        )
        self.assertEqual(
            coverages[
                self.listing_without_activity.id
            ].spending_finalized_through,
            self.requested_day,
        )

    @patch(
        "analytics.services.avito_stats.AvitoApiClient.get_item_analytics",
    )
    def test_v2_does_not_confirm_spending_for_grouping_without_metric(
            self,
            get_item_analytics,
    ):
        get_item_analytics.return_value = {
            "result": {
                "dataTotalCount": 2,
                "groupings": [
                    self.v2_grouping(
                        self.listing_with_activity.avito_id,
                        views=1,
                        contacts=0,
                        all_spending=1250,
                    ),
                    self.v2_grouping(
                        self.listing_without_activity.avito_id,
                        views=0,
                        contacts=0,
                    ),
                ],
            },
        }

        self.import_profile_day()

        confirmed_coverage = AvitoListingStatsCoverage.objects.get(
            listing=self.listing_with_activity,
        )
        unconfirmed_coverage = AvitoListingStatsCoverage.objects.get(
            listing=self.listing_without_activity,
        )

        self.assertEqual(
            confirmed_coverage.spending_coverage_from,
            self.requested_day,
        )
        self.assertEqual(
            confirmed_coverage.spending_finalized_through,
            self.requested_day,
        )
        self.assertIsNone(
            unconfirmed_coverage.spending_coverage_from
        )
        self.assertIsNone(
            unconfirmed_coverage.spending_finalized_through
        )

    @patch(
        "analytics.services.avito_stats.AvitoApiClient.get_item_analytics",
    )
    def test_nonempty_v2_response_without_local_matches_does_not_confirm_coverage(
            self,
            get_item_analytics,
    ):
        get_item_analytics.return_value = {
            "result": {
                "dataTotalCount": 1,
                "groupings": [
                    self.v2_grouping(
                        "99999999",
                        views=12,
                        contacts=1,
                    ),
                ],
            },
        }

        with self.assertRaisesMessage(
                AvitoApiError,
                "не сопоставлена",
        ):
            self.import_profile_day()

        self.assertFalse(
            AvitoListingDailyStats.objects.filter(
                workspace=self.workspace,
            ).exists()
        )
        self.assertFalse(
            AvitoListingStatsCoverage.objects.filter(
                workspace=self.workspace,
            ).exists()
        )

    @patch(
        "analytics.services.avito_stats.AvitoApiClient.get_item_analytics",
    )
    def test_zero_v2_grouping_counts_as_matched_listing(
            self,
            get_item_analytics,
    ):
        get_item_analytics.return_value = {
            "result": {
                "dataTotalCount": 1,
                "groupings": [
                    self.v2_grouping(
                        self.listing_without_activity.avito_id,
                        views=0,
                        contacts=0,
                    ),
                ],
            },
        }

        result = self.import_profile_day()

        self.assertEqual(result.total_received, 1)
        self.assertEqual(result.matched_listings, 1)
        self.assertFalse(
            AvitoListingDailyStats.objects.filter(
                workspace=self.workspace,
            ).exists()
        )
        self.assertEqual(
            AvitoListingStatsCoverage.objects.filter(
                workspace=self.workspace,
                coverage_from=self.requested_day,
                finalized_through=self.requested_day,
            ).count(),
            2,
        )

    @patch(
        "analytics.services.avito_stats.AvitoApiClient.get_item_analytics",
    )
    def test_v2_reimport_updates_values_and_preserves_spending(
            self,
            get_item_analytics,
    ):
        AvitoListingDailyStats.objects.create(
            workspace=self.workspace,
            listing=self.listing_with_activity,
            date=self.requested_day,
            views=5,
            contacts=0,
            total_spend=Decimal("12.50"),
        )
        get_item_analytics.return_value = {
            "result": {
                "dataTotalCount": 1,
                "groupings": [
                    self.v2_grouping(
                        self.listing_with_activity.avito_id,
                        views=7,
                        contacts=2,
                    ),
                ],
            },
        }

        self.import_profile_day()

        stats = AvitoListingDailyStats.objects.filter(
            listing=self.listing_with_activity,
            date=self.requested_day,
        )
        self.assertEqual(stats.count(), 1)
        stat = stats.get()
        self.assertEqual(stat.views, 7)
        self.assertEqual(stat.contacts, 2)
        self.assertEqual(stat.total_spend, Decimal("12.50"))

    @patch(
        "analytics.services.avito_stats.AvitoApiClient.get_item_analytics",
    )
    def test_zero_v2_grouping_without_spending_preserves_existing_spend(
            self,
            get_item_analytics,
    ):
        AvitoListingDailyStats.objects.create(
            workspace=self.workspace,
            listing=self.listing_with_activity,
            date=self.requested_day,
            views=5,
            contacts=2,
            favorites=4,
            total_spend=Decimal("12.50"),
        )
        get_item_analytics.return_value = {
            "result": {
                "dataTotalCount": 1,
                "groupings": [
                    self.v2_grouping(
                        self.listing_with_activity.avito_id,
                        views=0,
                        contacts=0,
                        favorites=0,
                    ),
                ],
            },
        }

        self.import_profile_day()

        stat = AvitoListingDailyStats.objects.get(
            listing=self.listing_with_activity,
            date=self.requested_day,
        )
        self.assertEqual(stat.views, 0)
        self.assertEqual(stat.contacts, 0)
        self.assertEqual(stat.favorites, 0)
        self.assertEqual(stat.total_spend, Decimal("12.50"))
        self.assertEqual(
            stat.raw_metrics["stats_v2"],
            {
                "views": 0,
                "contacts": 0,
                "favorites": 0,
            },
        )

    @patch(
        "analytics.services.avito_stats.AvitoApiClient.get_item_analytics",
    )
    def test_v2_import_converts_zero_spending_to_decimal_rubles(
            self,
            get_item_analytics,
    ):
        get_item_analytics.return_value = {
            "result": {
                "dataTotalCount": 1,
                "groupings": [
                    self.v2_grouping(
                        self.listing_with_activity.avito_id,
                        views=1,
                        contacts=0,
                        favorites=0,
                        all_spending=0,
                    ),
                ],
            },
        }

        self.import_profile_day()

        stat = AvitoListingDailyStats.objects.get(
            listing=self.listing_with_activity,
            date=self.requested_day,
        )
        self.assertEqual(stat.total_spend, Decimal("0.00"))

    @patch(
        "analytics.services.avito_stats.AvitoApiClient.get_item_analytics",
        return_value={
            "result": {
                "dataTotalCount": 0,
                "groupings": [],
            },
        },
    )
    def test_empty_v2_response_without_spending_preserves_existing_spend(
            self,
            get_item_analytics,
    ):
        AvitoListingDailyStats.objects.create(
            workspace=self.workspace,
            listing=self.listing_with_activity,
            date=self.requested_day,
            views=5,
            contacts=2,
            favorites=4,
            total_spend=Decimal("12.50"),
        )

        self.import_profile_day()

        stat = AvitoListingDailyStats.objects.get(
            listing=self.listing_with_activity,
            date=self.requested_day,
        )
        self.assertEqual(stat.views, 0)
        self.assertEqual(stat.contacts, 0)
        self.assertEqual(stat.favorites, 0)
        self.assertEqual(stat.total_spend, Decimal("12.50"))
        self.assertEqual(
            stat.raw_metrics["stats_v2"],
            {
                "views": 0,
                "contacts": 0,
                "favorites": 0,
            },
        )
        coverage = AvitoListingStatsCoverage.objects.get(
            listing=self.listing_with_activity,
        )
        self.assertEqual(
            coverage.finalized_through,
            self.requested_day,
        )

    @override_settings(AVITO_STATS_V2_PAGE_SIZE=1)
    @patch(
        "analytics.services.avito_stats.AvitoApiClient.get_item_analytics",
    )
    def test_failed_v2_page_does_not_change_stats_or_coverage(
            self,
            get_item_analytics,
    ):
        previous_day = self.requested_day - timedelta(days=1)
        existing_stat = AvitoListingDailyStats.objects.create(
            workspace=self.workspace,
            listing=self.listing_with_activity,
            date=self.requested_day,
            views=5,
            contacts=1,
        )
        coverage = AvitoListingStatsCoverage.objects.create(
            workspace=self.workspace,
            listing=self.listing_with_activity,
            coverage_from=previous_day,
            finalized_through=previous_day,
            last_successful_at=datetime(
                2026,
                7,
                28,
                4,
                10,
                tzinfo=dt_timezone.utc,
            ),
        )
        get_item_analytics.side_effect = [
            {
                "result": {
                    "dataTotalCount": 2,
                    "groupings": [
                        self.v2_grouping(
                            self.listing_with_activity.avito_id,
                            views=10,
                            contacts=3,
                        ),
                    ],
                },
            },
            AvitoApiError("Second v2 page unavailable"),
        ]

        with self.assertRaises(AvitoApiError):
            self.import_profile_day()

        existing_stat.refresh_from_db()
        coverage.refresh_from_db()
        self.assertEqual(existing_stat.views, 5)
        self.assertEqual(existing_stat.contacts, 1)
        self.assertEqual(
            coverage.finalized_through,
            previous_day,
        )

    @patch(
        "analytics.services.avito_stats.AvitoApiClient.get_item_analytics",
    )
    def test_v2_import_rejects_unsupported_page_size(
            self,
            get_item_analytics,
    ):
        for page_size in (0, 1001):
            with self.subTest(page_size=page_size):
                with override_settings(
                        AVITO_STATS_V2_PAGE_SIZE=page_size,
                ):
                    with self.assertRaisesMessage(
                            ValueError,
                            (
                                    "AVITO_STATS_V2_PAGE_SIZE "
                                    "должен быть от 1 до 1000."
                            ),
                    ):
                        self.import_profile_day()

        get_item_analytics.assert_not_called()

    def import_profile_day(self):
        from analytics.services.avito_stats import (
            import_avito_profile_daily_stats_for_account,
        )

        return import_avito_profile_daily_stats_for_account(
            avito_account=self.avito_account,
            stat_date=self.requested_day,
        )

    @staticmethod
    def v2_grouping(
            avito_id,
            *,
            views,
            contacts,
            favorites=0,
            all_spending=None,
    ):
        metrics = [
            {
                "slug": "views",
                "value": views,
            },
            {
                "slug": "contacts",
                "value": contacts,
            },
            {
                "slug": "favorites",
                "value": favorites,
            },
        ]

        if all_spending is not None:
            metrics.append({
                "slug": "allSpending",
                "value": all_spending,
            })

        return {
            "id": int(avito_id),
            "type": "items",
            "metrics": metrics,
        }


class AvitoStatsBackfillPlanTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="analytics-backfill-owner@example.com",
            password="test",
        )
        self.workspace = Workspace.objects.create(
            name="Analytics backfill workspace",
            slug="analytics-backfill-workspace",
            owner=self.user,
        )
        self.avito_account = AvitoAccount.objects.create(
            workspace=self.workspace,
            name="Analytics backfill account",
            external_account_id="94235341",
        )
        self.listing = AvitoListing.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            avito_id="24122501",
            status="active",
            title="Analytics backfill listing",
        )
        self.target_date = date(2026, 7, 29)
        self.backfill_to = self.target_date - timedelta(days=1)

    def test_backfill_plan_loads_only_required_listing_fields(self):
        listing_table = AvitoListing._meta.db_table

        with CaptureQueriesContext(connection) as queries:
            plan = self.build_plan()

        listing_queries = [
            query["sql"]
            for query in queries
            if listing_table in query["sql"]
        ]

        self.assertEqual(len(plan), 1)
        self.assertEqual(len(listing_queries), 1)

        listing_sql = listing_queries[0]
        self.assertIn('"id"', listing_sql)
        self.assertIn('"published_at"', listing_sql)

        for unused_field in (
                "description",
                "image_urls",
                "base_data",
                "option_data",
                "raw_data",
                "unmapped_data",
                "imported_payload",
        ):
            with self.subTest(field=unused_field):
                self.assertNotIn(
                    f'"{unused_field}"',
                    listing_sql,
                )

    @override_settings(AVITO_STATS_HISTORY_DAYS=270)
    def test_listing_without_coverage_gets_maximum_history_before_target_day(
            self,
    ):
        plan = self.build_plan()

        self.assertEqual(len(plan), 1)
        self.assertEqual(
            plan[0].date_from,
            self.backfill_to - timedelta(days=269),
        )
        self.assertEqual(plan[0].date_to, self.backfill_to)
        self.assertEqual(plan[0].listing_ids, (self.listing.id,))

    @override_settings(AVITO_STATS_HISTORY_DAYS=270)
    def test_publication_date_limits_backfill_and_future_listing_is_skipped(
            self,
    ):
        self.listing.published_at = datetime(
            2026,
            7,
            20,
            8,
            0,
            tzinfo=dt_timezone.utc,
        )
        self.listing.save(
            update_fields=["published_at", "updated_at"],
        )
        AvitoListing.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            avito_id="24122502",
            status="active",
            title="Future analytics backfill listing",
            published_at=datetime(
                2026,
                7,
                29,
                8,
                0,
                tzinfo=dt_timezone.utc,
            ),
        )

        plan = self.build_plan()

        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0].date_from, date(2026, 7, 20))
        self.assertEqual(plan[0].date_to, date(2026, 7, 28))
        self.assertEqual(plan[0].listing_ids, (self.listing.id,))

    @override_settings(AVITO_STATS_HISTORY_DAYS=270)
    def test_existing_coverage_gets_only_missing_forward_days(self):
        history_from = self.backfill_to - timedelta(days=269)
        AvitoListingStatsCoverage.objects.create(
            workspace=self.workspace,
            listing=self.listing,
            coverage_from=history_from,
            finalized_through=date(2026, 7, 27),
        )

        plan = self.build_plan()

        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0].date_from, date(2026, 7, 28))
        self.assertEqual(plan[0].date_to, date(2026, 7, 28))
        self.assertEqual(plan[0].listing_ids, (self.listing.id,))

    @override_settings(AVITO_STATS_HISTORY_DAYS=270)
    def test_middle_coverage_creates_backward_and_forward_requests(self):
        AvitoListingStatsCoverage.objects.create(
            workspace=self.workspace,
            listing=self.listing,
            coverage_from=date(2026, 7, 1),
            finalized_through=date(2026, 7, 27),
        )

        plan = self.build_plan()

        self.assertEqual(len(plan), 2)
        self.assertEqual(
            (
                plan[0].date_from,
                plan[0].date_to,
                plan[0].listing_ids,
            ),
            (
                self.backfill_to - timedelta(days=269),
                date(2026, 6, 30),
                (self.listing.id,),
            ),
        )
        self.assertEqual(
            (
                plan[1].date_from,
                plan[1].date_to,
                plan[1].listing_ids,
            ),
            (
                date(2026, 7, 28),
                date(2026, 7, 28),
                (self.listing.id,),
            ),
        )

    @override_settings(AVITO_STATS_HISTORY_DAYS=270)
    def test_profile_day_only_coverage_gets_missing_history_backward(self):
        AvitoListingStatsCoverage.objects.create(
            workspace=self.workspace,
            listing=self.listing,
            coverage_from=self.target_date,
            finalized_through=self.target_date,
        )

        plan = self.build_plan()

        self.assertEqual(len(plan), 1)
        self.assertEqual(
            plan[0].date_from,
            self.backfill_to - timedelta(days=269),
        )
        self.assertEqual(plan[0].date_to, self.backfill_to)
        self.assertEqual(plan[0].listing_ids, (self.listing.id,))

    @override_settings(AVITO_STATS_HISTORY_DAYS=270)
    def test_equal_missing_ranges_are_grouped_into_one_request(self):
        second_listing = AvitoListing.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            avito_id="24122503",
            status="active",
            title="Second analytics backfill listing",
        )

        plan = self.build_plan()

        self.assertEqual(len(plan), 1)
        self.assertEqual(
            plan[0].listing_ids,
            tuple(sorted([self.listing.id, second_listing.id])),
        )

    def test_backfill_rejects_unsupported_history_days(self):
        for history_days in (0, 271):
            with self.subTest(history_days=history_days):
                with override_settings(
                        AVITO_STATS_HISTORY_DAYS=history_days,
                ):
                    with self.assertRaisesMessage(
                            ValueError,
                            (
                                    "AVITO_STATS_HISTORY_DAYS "
                                    "должен быть от 1 до 270."
                            ),
                    ):
                        self.build_plan()

    def build_plan(self):
        from analytics.services.avito_stats import (
            build_avito_stats_backfill_plan,
        )

        return build_avito_stats_backfill_plan(
            avito_account=self.avito_account,
            target_date=self.target_date,
        )


class AvitoApiClientAnalyticsTests(TestCase):
    def test_get_item_analytics_sends_profile_stats_v2_request(self):
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
            date_from=date(2026, 5, 1),
            date_to=date(2026, 5, 2),
            metrics=["views", "contacts"],
            grouping="item",
            limit=1000,
            offset=2000,
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
                "dateFrom": "2026-05-01",
                "dateTo": "2026-05-02",
                "metrics": ["views", "contacts"],
                "grouping": "item",
                "limit": 1000,
                "offset": 2000,
            },
        )
        self.assertEqual(
            session.calls[0][2]["headers"]["Authorization"],
            "Bearer stats-access-token",
        )
