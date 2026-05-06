from django.test import TestCase
from avitotask.services.ad_editing import update_ad_creative, update_ad_publication
from avitotask.services.ad_export import (
    build_publication_export_row,
    export_avito_account_publications_to_csv,
)

from django.utils import timezone

from avitotask.services.avito_import import import_avito_listings_for_account

from avitotask.services.avito_autoload import link_publications_to_avito_ids_for_account

from urllib.parse import parse_qs, urlparse
from django.test import TestCase, override_settings
from accounts.models import User, Workspace, WorkspaceMembership
from avitotask.services.avito_api import (
    build_avito_authorization_url,
    build_avito_oauth_state,
    connect_avito_account_from_authorization_code,
    connect_avito_account_from_token,
    parse_avito_oauth_state,
)

from django.urls import NoReverseMatch, reverse
from system.celery import app as celery_app

from datetime import datetime, date, timedelta

from avitotask.services.ad_schedule import (
    advance_task_schedule_after_run,
    initialize_task_schedule,
    run_due_ad_generation_tasks,
)
from avitotask.services.ad_cleanup import archive_stale_publications
from avitotask.services.avito_stats import import_avito_listing_daily_stats_for_account

from avitotask.tasks import export_avito_account_csv_task, export_dirty_avito_accounts_csv_task, \
    import_avito_account_listings_task, link_avito_account_publications_task, import_avito_account_daily_stats_task
from accounts.models import User, Workspace
from avitotask.models import (
    AdBatch,
    AdCreative,
    AvitoListing,
    AvitoListingDailyStats,
    AdGenerationTask,
    AdPublication,
    AvitoAccount,
    AvitoOAuthToken,
)
from avitotask.services.ad_generation import (
    create_manual_mass_posting,
    generate_ads_from_task,
)

from avitotask.services.avito_api import connect_avito_account_from_token

import csv
import tempfile
from pathlib import Path


class AdGenerationServiceTests(TestCase):
    def test_generate_ads_from_task_creates_publications_for_each_address_and_account(self):
        user = User.objects.create_user(email="owner@example.com", password="test")
        workspace = Workspace.objects.create(
            name="Test workspace",
            slug="test-workspace",
            owner=user,
        )

        account_1 = AvitoAccount.objects.create(workspace=workspace, name="Account 1")
        account_2 = AvitoAccount.objects.create(workspace=workspace, name="Account 2")

        task = AdGenerationTask.objects.create(
            workspace=workspace,
            name="Test task",
            is_active=True,
            titles=["Title 1"],
            descriptions={"1": "Description {{ TITLE }} / {{ SKU }}"},
            main_images=["https://example.com/main.jpg"],
            additional_images=[],
            addresses=["Address 1", "Address 2"],
            price=100,
        )
        task.avito_accounts.add(account_1, account_2)

        result = generate_ads_from_task(task.id, workspace=workspace)

        publications = AdPublication.objects.filter(
            workspace=workspace,
            creative=result.creative,
        )

        self.assertEqual(publications.count(), 4)
        self.assertEqual(result.batch.total_creatives, 1)
        self.assertEqual(result.batch.total_publications, 4)
        self.assertEqual(len(result.publications), 4)
        self.assertEqual(
            set(publications.values_list("address", flat=True)),
            {"Address 1", "Address 2"},
        )
        self.assertEqual(
            set(publications.values_list("avito_account__name", flat=True)),
            {"Account 1", "Account 2"},
        )

    def test_create_manual_mass_posting_creates_creative_and_publications(self):
        user = User.objects.create_user(email="manual-owner@example.com", password="test")
        workspace = Workspace.objects.create(
            name="Manual workspace",
            slug="manual-workspace",
            owner=user,
        )

        account_1 = AvitoAccount.objects.create(workspace=workspace, name="Manual Account 1")
        account_2 = AvitoAccount.objects.create(workspace=workspace, name="Manual Account 2")

        result = create_manual_mass_posting(
            workspace=workspace,
            user=user,
            avito_accounts=[account_1, account_2],
            addresses=["Manual Address 1", "Manual Address 2", "Manual Address 3"],
            title="Ручное объявление",
            description="Описание ручного объявления",
            image_urls=["https://example.com/manual-main.jpg"],
            base_data={"Price": 500, "Category": "Ремонт и строительство"},
            option_data={"Condition": "Новое"},
        )

        publications = AdPublication.objects.filter(
            workspace=workspace,
            creative=result.creative,
        )

        self.assertEqual(result.batch.source, "manual")
        self.assertEqual(result.creative.source, "manual")
        self.assertIsNone(result.creative.task)
        self.assertEqual(publications.count(), 6)
        self.assertEqual(len(result.publications), 6)
        self.assertEqual(result.batch.total_creatives, 1)
        self.assertEqual(result.batch.total_publications, 6)
        self.assertEqual(
            set(publications.values_list("address", flat=True)),
            {"Manual Address 1", "Manual Address 2", "Manual Address 3"},
        )

    def test_update_ad_publication_changes_only_selected_publication_overrides(self):
        user = User.objects.create_user(email="edit-owner@example.com", password="test")
        workspace = Workspace.objects.create(
            name="Edit workspace",
            slug="edit-workspace",
            owner=user,
        )

        account = AvitoAccount.objects.create(workspace=workspace, name="Edit Account")

        result = create_manual_mass_posting(
            workspace=workspace,
            user=user,
            avito_accounts=[account],
            addresses=["Edit Address 1", "Edit Address 2"],
            title="Editable ad",
            description="Editable description",
            image_urls=["https://example.com/edit.jpg"],
            base_data={"Price": 500, "Category": "Стройматериалы"},
            option_data={},
        )

        first_publication = result.publications[0]
        second_publication = result.publications[1]

        updated_publication = update_ad_publication(
            publication_id=first_publication.id,
            workspace=workspace,
            overrides={"Price": 700, "Title": "Индивидуальный заголовок"},
            address="Updated Address 1",
        )

        second_publication.refresh_from_db()

        self.assertEqual(updated_publication.overrides["Price"], 700)
        self.assertEqual(updated_publication.overrides["Title"], "Индивидуальный заголовок")
        self.assertEqual(updated_publication.address, "Updated Address 1")

        self.assertEqual(second_publication.overrides, {})
        self.assertEqual(second_publication.address, "Edit Address 2")
        self.assertEqual(result.creative.base_data["Price"], 500)
        self.assertEqual(result.creative.title, "Editable ad")

    def test_update_ad_creative_updates_shared_data_and_clears_matching_publication_overrides(self):
        user = User.objects.create_user(email="bulk-edit-owner@example.com", password="test")
        workspace = Workspace.objects.create(
            name="Bulk edit workspace",
            slug="bulk-edit-workspace",
            owner=user,
        )

        account = AvitoAccount.objects.create(workspace=workspace, name="Bulk Edit Account")

        result = create_manual_mass_posting(
            workspace=workspace,
            user=user,
            avito_accounts=[account],
            addresses=["Bulk Address 1", "Bulk Address 2"],
            title="Old shared title",
            description="Old shared description",
            image_urls=["https://example.com/old.jpg"],
            base_data={"Price": 500, "Category": "Стройматериалы"},
            option_data={"Condition": "Новое"},
        )

        first_publication = result.publications[0]
        second_publication = result.publications[1]

        update_ad_publication(
            publication_id=first_publication.id,
            workspace=workspace,
            overrides={"Price": 700, "Title": "Individual title"},
        )

        updated_creative = update_ad_creative(
            creative_id=result.creative.id,
            workspace=workspace,
            title="New shared title",
            base_data={"Price": 900},
            option_data={"Condition": "Б/у"},
            clear_publication_override_fields=["Price", "Title", "Condition"],
        )

        first_publication.refresh_from_db()
        second_publication.refresh_from_db()

        self.assertEqual(updated_creative.title, "New shared title")
        self.assertEqual(updated_creative.base_data["Price"], 900)
        self.assertEqual(updated_creative.base_data["Category"], "Стройматериалы")
        self.assertEqual(updated_creative.option_data["Condition"], "Б/у")

        self.assertNotIn("Price", first_publication.overrides)
        self.assertNotIn("Title", first_publication.overrides)
        self.assertEqual(second_publication.overrides, {})

    def test_build_publication_export_row_merges_creative_data_and_publication_overrides(self):
        user = User.objects.create_user(email="export-row-owner@example.com", password="test")
        workspace = Workspace.objects.create(
            name="Export row workspace",
            slug="export-row-workspace",
            owner=user,
        )

        account = AvitoAccount.objects.create(workspace=workspace, name="Export Row Account")

        result = create_manual_mass_posting(
            workspace=workspace,
            user=user,
            avito_accounts=[account],
            addresses=["Original Address"],
            title="Shared title",
            description="Shared description",
            image_urls=["https://example.com/1.jpg", "https://example.com/2.jpg"],
            base_data={"Price": 500, "Category": "Стройматериалы"},
            option_data={"Condition": "Новое"},
        )

        publication = update_ad_publication(
            publication_id=result.publications[0].id,
            workspace=workspace,
            overrides={
                "Price": 700,
                "Title": "Individual title",
                "CustomField": "Custom value",
            },
            address="Updated Address",
        )

        row = build_publication_export_row(publication)

        self.assertEqual(row["Id"], publication.row_id)
        self.assertEqual(row["Title"], "Individual title")
        self.assertEqual(row["Description"], "Shared description")
        self.assertEqual(row["ImageUrls"], "https://example.com/1.jpg | https://example.com/2.jpg")
        self.assertEqual(row["Address"], "Updated Address")
        self.assertEqual(row["Price"], 700)
        self.assertEqual(row["Category"], "Стройматериалы")
        self.assertEqual(row["Condition"], "Новое")
        self.assertEqual(row["CustomField"], "Custom value")

    def test_export_avito_account_publications_to_csv_writes_active_publications(self):
        user = User.objects.create_user(email="csv-owner@example.com", password="test")
        workspace = Workspace.objects.create(
            name="CSV workspace",
            slug="csv-workspace",
            owner=user,
        )

        account = AvitoAccount.objects.create(workspace=workspace, name="CSV Account")

        result = create_manual_mass_posting(
            workspace=workspace,
            user=user,
            avito_accounts=[account],
            addresses=["CSV Address 1", "CSV Address 2"],
            title="CSV title",
            description="CSV description",
            image_urls=["https://example.com/csv.jpg"],
            base_data={"Price": 500, "Category": "Стройматериалы"},
            option_data={"Condition": "Новое"},
        )

        update_ad_publication(
            publication_id=result.publications[0].id,
            workspace=workspace,
            overrides={"Price": 700},
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = export_avito_account_publications_to_csv(
                workspace=workspace,
                avito_account=account,
                output_dir=Path(temp_dir),
            )

            with open(file_path, newline="", encoding="utf-8") as csv_file:
                rows = list(csv.DictReader(csv_file, delimiter=";"))

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["Title"], "CSV title")
        self.assertEqual(rows[0]["Address"], "CSV Address 1")
        self.assertEqual(rows[0]["Price"], "700")
        self.assertEqual(rows[1]["Price"], "500")
        self.assertIn("Condition", rows[0])

    def test_account_export_status_changes_after_publication_change_and_export(self):
        user = User.objects.create_user(email="dirty-owner@example.com", password="test")
        workspace = Workspace.objects.create(
            name="Dirty workspace",
            slug="dirty-workspace",
            owner=user,
        )

        account = AvitoAccount.objects.create(workspace=workspace, name="Dirty Account")

        result = create_manual_mass_posting(
            workspace=workspace,
            user=user,
            avito_accounts=[account],
            addresses=["Dirty Address"],
            title="Dirty title",
            description="Dirty description",
            image_urls=["https://example.com/dirty.jpg"],
            base_data={"Price": 500},
            option_data={},
        )

        account.refresh_from_db()
        self.assertEqual(account.export_status, AvitoAccount.ExportStatus.DIRTY)

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = export_avito_account_publications_to_csv(
                workspace=workspace,
                avito_account=account,
                output_dir=Path(temp_dir),
            )

        account.refresh_from_db()
        self.assertEqual(account.export_status, AvitoAccount.ExportStatus.CLEAN)
        self.assertEqual(account.export_file_path, str(file_path))
        self.assertIsNotNone(account.last_exported_at)

        update_ad_publication(
            publication_id=result.publications[0].id,
            workspace=workspace,
            overrides={"Price": 700},
        )

        account.refresh_from_db()
        self.assertEqual(account.export_status, AvitoAccount.ExportStatus.DIRTY)

    def test_export_dirty_avito_accounts_csv_task_exports_dirty_accounts(self):
        user = User.objects.create_user(email="celery-export-owner@example.com", password="test")
        workspace = Workspace.objects.create(
            name="Celery export workspace",
            slug="celery-export-workspace",
            owner=user,
        )

        account = AvitoAccount.objects.create(workspace=workspace, name="Celery Export Account")

        create_manual_mass_posting(
            workspace=workspace,
            user=user,
            avito_accounts=[account],
            addresses=["Celery Address"],
            title="Celery title",
            description="Celery description",
            image_urls=["https://example.com/celery.jpg"],
            base_data={"Price": 500},
            option_data={},
        )

        account.refresh_from_db()
        self.assertEqual(account.export_status, AvitoAccount.ExportStatus.DIRTY)

        exported_count = export_dirty_avito_accounts_csv_task()

        account.refresh_from_db()
        self.assertEqual(exported_count, 1)
        self.assertEqual(account.export_status, AvitoAccount.ExportStatus.CLEAN)
        self.assertTrue(account.export_file_path)
        self.assertIsNotNone(account.last_exported_at)

    def test_schedule_initializes_next_slot_inside_current_cycle(self):
        user = User.objects.create_user(email="schedule-init-owner@example.com", password="test")
        workspace = Workspace.objects.create(
            name="Schedule init workspace",
            slug="schedule-init-workspace",
            owner=user,
        )

        task = AdGenerationTask.objects.create(
            workspace=workspace,
            name="Schedule init task",
            is_active=True,
            schedule={"Пн": "12:00", "Ср": "12:00"},
            publication_interval_days=14,
        )

        next_update_time = initialize_task_schedule(
            task,
            from_dt=datetime(2026, 5, 5, 10, 0),
        )

        task.refresh_from_db()

        self.assertEqual(next_update_time, datetime(2026, 5, 6, 12, 0))
        self.assertEqual(task.schedule_cycle_started_at, datetime(2026, 5, 4, 12, 0))
        self.assertEqual(task.next_update_time, datetime(2026, 5, 6, 12, 0))

    def test_schedule_advances_inside_cycle_then_to_next_interval_cycle(self):
        user = User.objects.create_user(email="schedule-owner@example.com", password="test")
        workspace = Workspace.objects.create(
            name="Schedule workspace",
            slug="schedule-workspace",
            owner=user,
        )

        task = AdGenerationTask.objects.create(
            workspace=workspace,
            name="Schedule task",
            is_active=True,
            schedule={"Пн": "12:00", "Ср": "12:00"},
            publication_interval_days=14,
            schedule_cycle_started_at=datetime(2026, 5, 4, 12, 0),
            next_update_time=datetime(2026, 5, 4, 12, 0),
        )

        advance_task_schedule_after_run(
            task,
            run_at=datetime(2026, 5, 4, 12, 0),
        )

        task.refresh_from_db()
        self.assertEqual(task.schedule_cycle_started_at, datetime(2026, 5, 4, 12, 0))
        self.assertEqual(task.next_update_time, datetime(2026, 5, 6, 12, 0))

        advance_task_schedule_after_run(
            task,
            run_at=datetime(2026, 5, 6, 12, 0),
        )

        task.refresh_from_db()
        self.assertEqual(task.schedule_cycle_started_at, datetime(2026, 5, 18, 12, 0))
        self.assertEqual(task.next_update_time, datetime(2026, 5, 18, 12, 0))

    def test_run_due_ad_generation_tasks_generates_ads_and_advances_schedule(self):
        user = User.objects.create_user(email="schedule-run-owner@example.com", password="test")
        workspace = Workspace.objects.create(
            name="Schedule run workspace",
            slug="schedule-run-workspace",
            owner=user,
        )

        account = AvitoAccount.objects.create(workspace=workspace, name="Schedule Run Account")

        task = AdGenerationTask.objects.create(
            workspace=workspace,
            name="Schedule run task",
            is_active=True,
            titles=["Schedule title"],
            descriptions={"1": "Schedule description {{ TITLE }} / {{ SKU }}"},
            main_images=["https://example.com/schedule.jpg"],
            additional_images=[],
            addresses=["Schedule Address"],
            price=100,
            schedule={"Пн": "12:00", "Ср": "12:00"},
            publication_interval_days=14,
            schedule_cycle_started_at=datetime(2026, 5, 4, 12, 0),
            next_update_time=datetime(2026, 5, 4, 12, 0),
        )
        task.avito_accounts.add(account)

        generated_count = run_due_ad_generation_tasks(
            now_dt=datetime(2026, 5, 4, 12, 1),
        )

        task.refresh_from_db()

        self.assertEqual(generated_count, 1)
        self.assertEqual(AdPublication.objects.filter(task=task).count(), 1)
        self.assertEqual(task.next_update_time, datetime(2026, 5, 6, 12, 0))

    def test_connect_avito_account_from_token_sets_external_account_id(self):
        user = User.objects.create_user(email="avito-api-owner@example.com", password="test")
        workspace = Workspace.objects.create(
            name="Avito API workspace",
            slug="avito-api-workspace",
            owner=user,
        )

        account = AvitoAccount.objects.create(workspace=workspace, name="Local Avito Account")

        token = AvitoOAuthToken.objects.create(
            workspace=workspace,
            avito_account=account,
            access_token="test-access-token",
            refresh_token="test-refresh-token",
            scope="user:read items:info stats:read autoload:reports",
        )

        class FakeResponse:
            status_code = 200
            text = '{"id": 94235311}'

            def json(self):
                return {
                    "id": 94235311,
                    "name": "Петр",
                    "email": "owner@example.com",
                    "phone": "71112223344",
                    "phones": ["71112223344"],
                    "profile_url": "https://avito.ru/user/test/profile",
                }

        class FakeSession:
            def request(self, method, url, **kwargs):
                self.method = method
                self.url = url
                self.kwargs = kwargs
                return FakeResponse()

        session = FakeSession()

        connected_account = connect_avito_account_from_token(
            avito_account=account,
            token=token,
            session=session,
        )

        token.refresh_from_db()

        self.assertEqual(connected_account.external_account_id, "94235311")
        self.assertEqual(token.user_info["id"], 94235311)
        self.assertEqual(token.user_info["name"], "Петр")
        self.assertEqual(session.method, "GET")
        self.assertEqual(session.url, "https://api.avito.ru/core/v1/accounts/self")
        self.assertEqual(
            session.kwargs["headers"]["Authorization"],
            "Bearer test-access-token",
        )

    @override_settings(AVITO_CLIENT_ID="test-client-id")
    def test_build_avito_authorization_url_contains_signed_state(self):
        user = User.objects.create_user(email="oauth-url-owner@example.com", password="test")
        workspace = Workspace.objects.create(name="OAuth URL workspace", slug="oauth-url-workspace", owner=user)
        account = AvitoAccount.objects.create(workspace=workspace, name="OAuth Account")

        authorization_url = build_avito_authorization_url(account)
        parsed = urlparse(authorization_url)
        query = parse_qs(parsed.query)

        self.assertEqual(f"{parsed.scheme}://{parsed.netloc}{parsed.path}", "https://avito.ru/oauth")
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["pro_users_flow"], ["true"])
        self.assertEqual(query["client_id"], ["test-client-id"])
        self.assertEqual(query["scope"], ["user:read,items:info,stats:read,autoload:reports"])

        state_payload = parse_avito_oauth_state(query["state"][0])
        self.assertEqual(state_payload["workspace_id"], workspace.id)
        self.assertEqual(state_payload["avito_account_id"], account.id)

    @override_settings(AVITO_CLIENT_ID="test-client-id", AVITO_CLIENT_SECRET="test-client-secret")
    def test_connect_avito_account_from_authorization_code_exchanges_code_and_connects_account(self):
        user = User.objects.create_user(email="oauth-callback-owner@example.com", password="test")
        workspace = Workspace.objects.create(name="OAuth callback workspace", slug="oauth-callback-workspace",
                                             owner=user)
        account = AvitoAccount.objects.create(workspace=workspace, name="Callback Account")
        state = build_avito_oauth_state(account)

        class FakeResponse:
            def __init__(self, status_code, payload):
                self.status_code = status_code
                self.payload = payload
                self.text = "json"

            def json(self):
                return self.payload

        class FakeSession:
            def __init__(self):
                self.calls = []

            def request(self, method, url, **kwargs):
                self.calls.append((method, url, kwargs))
                if url == "https://api.avito.ru/token":
                    return FakeResponse(200, {
                        "access_token": "new-access-token",
                        "refresh_token": "new-refresh-token",
                        "expires_in": 86400,
                        "token_type": "Bearer",
                        "scope": "user:read items:info stats:read autoload:reports",
                    })
                return FakeResponse(200, {
                    "id": 94235311,
                    "name": "Петр",
                    "email": "owner@example.com",
                })

        session = FakeSession()

        connected_account = connect_avito_account_from_authorization_code(
            code="auth-code",
            state=state,
            session=session,
        )

        token = AvitoOAuthToken.objects.get(avito_account=account)

        self.assertEqual(connected_account.external_account_id, "94235311")
        self.assertEqual(token.access_token, "new-access-token")
        self.assertEqual(token.refresh_token, "new-refresh-token")
        self.assertIsNotNone(token.expires_at)
        self.assertEqual(session.calls[0][0], "POST")
        self.assertEqual(session.calls[1][0], "GET")

    def test_import_avito_listings_for_account_creates_listings_and_is_idempotent(self):
        user = User.objects.create_user(email="avito-import-owner@example.com", password="test")
        workspace = Workspace.objects.create(
            name="Avito import workspace",
            slug="avito-import-workspace",
            owner=user,
        )
        account = AvitoAccount.objects.create(
            workspace=workspace,
            name="Import Account",
            external_account_id="94235311",
        )
        AvitoOAuthToken.objects.create(
            workspace=workspace,
            avito_account=account,
            access_token="import-access-token",
            refresh_token="import-refresh-token",
            scope="items:info",
        )

        class FakeResponse:
            status_code = 200
            text = "json"

            def json(self):
                return {
                    "meta": {"page": 1, "per_page": 25},
                    "resources": [
                        {
                            "id": 24122231,
                            "title": "Кирпич облицовочный",
                            "status": "active",
                            "url": "https://www.avito.ru/item/24122231",
                            "price": 100,
                            "address": "Москва, Лесная 7",
                            "category": {"id": 19, "name": "Стройматериалы"},
                        },
                        {
                            "id": 24122232,
                            "title": "Кирпич рядовой",
                            "status": "removed",
                            "url": None,
                            "price": None,
                            "address": "Москва, Тестовая 1",
                            "category": {"id": 19, "name": "Стройматериалы"},
                        },
                    ],
                }

        class FakeSession:
            def __init__(self):
                self.calls = []

            def request(self, method, url, **kwargs):
                self.calls.append((method, url, kwargs))
                return FakeResponse()

        session = FakeSession()

        result = import_avito_listings_for_account(account, session=session)

        self.assertEqual(result.total_received, 2)
        self.assertEqual(result.created_listings, 2)
        self.assertEqual(result.updated_listings, 0)
        self.assertEqual(result.created_publications, 2)

        self.assertEqual(AvitoListing.objects.filter(avito_account=account).count(), 2)
        self.assertEqual(AdCreative.objects.filter(workspace=workspace, source="import").count(), 2)
        self.assertEqual(AdPublication.objects.filter(workspace=workspace, source="import").count(), 2)

        listing = AvitoListing.objects.get(avito_id="24122231")
        self.assertEqual(listing.status, "active")
        self.assertEqual(listing.title, "Кирпич облицовочный")
        self.assertEqual(listing.publication.status, AdPublication.Status.DRAFT)
        self.assertEqual(listing.publication.address, "Москва, Лесная 7")
        self.assertEqual(listing.publication.creative.base_data["Price"], 100)
        self.assertEqual(listing.publication.creative.base_data["Category"], "Стройматериалы")

        second_result = import_avito_listings_for_account(account, session=session)

        self.assertEqual(second_result.created_listings, 0)
        self.assertEqual(second_result.updated_listings, 2)
        self.assertEqual(second_result.created_publications, 0)
        self.assertEqual(AvitoListing.objects.filter(avito_account=account).count(), 2)
        self.assertEqual(AdPublication.objects.filter(workspace=workspace, source="import").count(), 2)

    def test_import_avito_account_listings_task_imports_account_listings(self):
        user = User.objects.create_user(email="avito-import-task-owner@example.com", password="test")
        workspace = Workspace.objects.create(
            name="Avito import task workspace",
            slug="avito-import-task-workspace",
            owner=user,
        )
        account = AvitoAccount.objects.create(
            workspace=workspace,
            name="Import Task Account",
            external_account_id="94235311",
        )
        AvitoOAuthToken.objects.create(
            workspace=workspace,
            avito_account=account,
            access_token="import-task-access-token",
            refresh_token="import-task-refresh-token",
            scope="items:info",
        )

        class FakeResponse:
            status_code = 200
            text = "json"

            def json(self):
                return {
                    "resources": [
                        {
                            "id": 24122233,
                            "title": "Импорт через task",
                            "status": "active",
                            "url": "https://www.avito.ru/item/24122233",
                            "price": 150,
                            "address": "Москва, Task 1",
                            "category": {"id": 19, "name": "Стройматериалы"},
                        },
                    ],
                }

        class FakeSession:
            def request(self, method, url, **kwargs):
                return FakeResponse()

        result = import_avito_account_listings_task(
            account.id,
            session=FakeSession(),
        )

        self.assertEqual(result["total_received"], 1)
        self.assertEqual(result["created_listings"], 1)
        self.assertEqual(AvitoListing.objects.filter(avito_account=account).count(), 1)

    def test_link_publications_to_avito_ids_for_account_links_row_id_to_listing(self):
        user = User.objects.create_user(email="autoload-link-owner@example.com", password="test")
        workspace = Workspace.objects.create(
            name="Autoload link workspace",
            slug="autoload-link-workspace",
            owner=user,
        )
        account = AvitoAccount.objects.create(
            workspace=workspace,
            name="Autoload Account",
            external_account_id="94235311",
        )
        AvitoOAuthToken.objects.create(
            workspace=workspace,
            avito_account=account,
            access_token="autoload-access-token",
            refresh_token="autoload-refresh-token",
            scope="autoload:reports",
        )

        mass_posting = create_manual_mass_posting(
            workspace=workspace,
            user=user,
            avito_accounts=[account],
            addresses=["Autoload Address 1", "Autoload Address 2"],
            title="Autoload title",
            description="Autoload description",
            image_urls=["https://example.com/autoload.jpg"],
            base_data={"Price": 500},
            option_data={},
        )

        first_publication = mass_posting.publications[0]
        second_publication = mass_posting.publications[1]

        class FakeResponse:
            status_code = 200
            text = "json"

            def json(self):
                return {
                    "items": [
                        {
                            "ad_id": first_publication.row_id,
                            "avito_id": 24122241,
                        },
                        {
                            "ad_id": second_publication.row_id,
                            "avito_id": None,
                        },
                    ],
                }

        class FakeSession:
            def __init__(self):
                self.calls = []

            def request(self, method, url, **kwargs):
                self.calls.append((method, url, kwargs))
                return FakeResponse()

        session = FakeSession()

        result = link_publications_to_avito_ids_for_account(
            account,
            session=session,
        )

        first_publication.refresh_from_db()
        second_publication.refresh_from_db()

        self.assertEqual(result.total_requested, 2)
        self.assertEqual(result.linked, 1)
        self.assertEqual(result.missing, 1)
        self.assertEqual(result.conflicts, 0)
        self.assertEqual(result.created_listings, 1)
        self.assertEqual(result.updated_listings, 0)

        listing = AvitoListing.objects.get(avito_id="24122241")
        self.assertEqual(listing.publication, first_publication)
        self.assertEqual(listing.avito_account, account)
        self.assertEqual(listing.status, "published")
        self.assertEqual(first_publication.avito_listing, listing)

        self.assertFalse(hasattr(second_publication, "avito_listing"))

        self.assertEqual(session.calls[0][0], "GET")
        self.assertEqual(
            session.calls[0][1],
            "https://api.avito.ru/autoload/v2/items/avito_ids",
        )
        self.assertIn(first_publication.row_id, session.calls[0][2]["params"]["query"])
        self.assertIn(second_publication.row_id, session.calls[0][2]["params"]["query"])

        second_result = link_publications_to_avito_ids_for_account(
            account,
            session=session,
        )

        self.assertEqual(second_result.created_listings, 0)
        self.assertEqual(second_result.updated_listings, 1)
        self.assertEqual(AvitoListing.objects.filter(avito_account=account).count(), 1)

    def test_link_avito_account_publications_task_links_publications(self):
        user = User.objects.create_user(email="autoload-link-task-owner@example.com", password="test")
        workspace = Workspace.objects.create(
            name="Autoload link task workspace",
            slug="autoload-link-task-workspace",
            owner=user,
        )
        account = AvitoAccount.objects.create(
            workspace=workspace,
            name="Autoload Link Task Account",
            external_account_id="94235311",
        )
        AvitoOAuthToken.objects.create(
            workspace=workspace,
            avito_account=account,
            access_token="autoload-link-task-token",
            refresh_token="autoload-link-task-refresh",
            scope="autoload:reports",
        )

        mass_posting = create_manual_mass_posting(
            workspace=workspace,
            user=user,
            avito_accounts=[account],
            addresses=["Task Link Address"],
            title="Task link title",
            description="Task link description",
            image_urls=["https://example.com/task-link.jpg"],
            base_data={"Price": 500},
            option_data={},
        )

        publication = mass_posting.publications[0]

        class FakeResponse:
            status_code = 200
            text = "json"

            def json(self):
                return {
                    "items": [
                        {
                            "ad_id": publication.row_id,
                            "avito_id": 24122251,
                        },
                    ],
                }

        class FakeSession:
            def request(self, method, url, **kwargs):
                return FakeResponse()

        result = link_avito_account_publications_task(
            account.id,
            session=FakeSession(),
        )

        publication.refresh_from_db()

        self.assertEqual(result["total_requested"], 1)
        self.assertEqual(result["linked"], 1)
        self.assertEqual(result["created_listings"], 1)
        self.assertEqual(publication.avito_listing.avito_id, "24122251")

    def test_import_avito_listing_daily_stats_for_account_upserts_daily_stats(self):
        user = User.objects.create_user(email="avito-stats-owner@example.com", password="test")
        workspace = Workspace.objects.create(
            name="Avito stats workspace",
            slug="avito-stats-workspace",
            owner=user,
        )
        account = AvitoAccount.objects.create(
            workspace=workspace,
            name="Stats Account",
            external_account_id="94235311",
        )
        AvitoOAuthToken.objects.create(
            workspace=workspace,
            avito_account=account,
            access_token="stats-access-token",
            refresh_token="stats-refresh-token",
            scope="stats:read",
        )

        listing = AvitoListing.objects.create(
            workspace=workspace,
            avito_account=account,
            avito_id="24122261",
            status="active",
            title="Stats listing",
        )

        class FakeResponse:
            status_code = 200
            text = "json"

            def json(self):
                return {
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
                                    {
                                        "date": "2026-05-02",
                                        "uniqViews": 15,
                                        "uniqContacts": 3,
                                        "uniqFavorites": 4,
                                    },
                                ],
                            },
                        ],
                    },
                }

        class FakeSession:
            def __init__(self):
                self.calls = []

            def request(self, method, url, **kwargs):
                self.calls.append((method, url, kwargs))
                return FakeResponse()

        session = FakeSession()

        result = import_avito_listing_daily_stats_for_account(
            avito_account=account,
            date_from=date(2026, 5, 1),
            date_to=date(2026, 5, 2),
            session=session,
        )

        self.assertEqual(result.total_listings, 1)
        self.assertEqual(result.total_days, 2)
        self.assertEqual(result.created_stats, 2)
        self.assertEqual(result.updated_stats, 0)

        first_day = AvitoListingDailyStats.objects.get(
            listing=listing,
            date=date(2026, 5, 1),
        )
        self.assertEqual(first_day.views, 10)
        self.assertEqual(first_day.contacts, 2)
        self.assertEqual(first_day.favorites, 1)
        self.assertEqual(first_day.raw_metrics["uniqViews"], 10)

        self.assertEqual(session.calls[0][0], "POST")
        self.assertEqual(
            session.calls[0][1],
            "https://api.avito.ru/stats/v1/accounts/94235311/items",
        )
        self.assertEqual(session.calls[0][2]["json"]["itemIds"], [24122261])
        self.assertEqual(session.calls[0][2]["json"]["dateFrom"], "2026-05-01")
        self.assertEqual(session.calls[0][2]["json"]["dateTo"], "2026-05-02")

        second_result = import_avito_listing_daily_stats_for_account(
            avito_account=account,
            date_from=date(2026, 5, 1),
            date_to=date(2026, 5, 2),
            session=session,
        )

        self.assertEqual(second_result.created_stats, 0)
        self.assertEqual(second_result.updated_stats, 2)
        self.assertEqual(AvitoListingDailyStats.objects.filter(listing=listing).count(), 2)

    def test_import_avito_account_daily_stats_task_imports_stats(self):
        user = User.objects.create_user(email="avito-stats-task-owner@example.com", password="test")
        workspace = Workspace.objects.create(
            name="Avito stats task workspace",
            slug="avito-stats-task-workspace",
            owner=user,
        )
        account = AvitoAccount.objects.create(
            workspace=workspace,
            name="Stats Task Account",
            external_account_id="94235311",
        )
        AvitoOAuthToken.objects.create(
            workspace=workspace,
            avito_account=account,
            access_token="stats-task-access-token",
            refresh_token="stats-task-refresh-token",
            scope="stats:read",
        )

        listing = AvitoListing.objects.create(
            workspace=workspace,
            avito_account=account,
            avito_id="24122271",
            status="active",
            title="Stats task listing",
        )

        class FakeResponse:
            status_code = 200
            text = "json"

            def json(self):
                return {
                    "result": {
                        "items": [
                            {
                                "itemId": "24122271",
                                "stats": [
                                    {
                                        "date": "2026-05-03",
                                        "uniqViews": 20,
                                        "uniqContacts": 4,
                                        "uniqFavorites": 2,
                                    },
                                ],
                            },
                        ],
                    },
                }

        class FakeSession:
            def request(self, method, url, **kwargs):
                return FakeResponse()

        result = import_avito_account_daily_stats_task(
            account.id,
            "2026-05-03",
            "2026-05-03",
            session=FakeSession(),
        )

        stats = AvitoListingDailyStats.objects.get(
            listing=listing,
            date=date(2026, 5, 3),
        )

        self.assertEqual(result["total_listings"], 1)
        self.assertEqual(result["total_days"], 1)
        self.assertEqual(result["created_stats"], 1)
        self.assertEqual(stats.views, 20)
        self.assertEqual(stats.contacts, 4)
        self.assertEqual(stats.favorites, 2)

    def test_archive_stale_publications_archives_only_old_inactive_publications(self):
        user = User.objects.create_user(email="cleanup-owner@example.com", password="test")
        workspace = Workspace.objects.create(
            name="Cleanup workspace",
            slug="cleanup-workspace",
            owner=user,
        )
        account = AvitoAccount.objects.create(workspace=workspace, name="Cleanup Account")

        old_batch = AdBatch.objects.create(
            workspace=workspace,
            source=AdBatch.Source.MANUAL,
            status=AdBatch.Status.COMPLETED,
        )

        old_creative = AdCreative.objects.create(
            workspace=workspace,
            batch=old_batch,
            source=AdCreative.Source.MANUAL,
            title="Old cleanup title",
            description="Old cleanup description",
            image_urls=[],
            base_data={},
            option_data={},
        )

        old_publication = AdPublication.objects.create(
            workspace=workspace,
            avito_account=account,
            creative=old_creative,
            batch=old_batch,
            source=AdPublication.Source.MANUAL,
            status=AdPublication.Status.PAUSED,
            row_id="OLD-ROW",
            address="Old address",
        )
        fresh_publication = AdPublication.objects.create(
            workspace=workspace,
            avito_account=account,
            creative=old_creative,
            batch=old_batch,
            source=AdPublication.Source.MANUAL,
            status=AdPublication.Status.PAUSED,
            row_id="FRESH-ROW",
            address="Fresh address",
        )
        active_publication = AdPublication.objects.create(
            workspace=workspace,
            avito_account=account,
            creative=old_creative,
            batch=old_batch,
            source=AdPublication.Source.MANUAL,
            status=AdPublication.Status.ACTIVE,
            row_id="ACTIVE-ROW",
            address="Active address",
        )
        linked_active_publication = AdPublication.objects.create(
            workspace=workspace,
            avito_account=account,
            creative=old_creative,
            batch=old_batch,
            source=AdPublication.Source.MANUAL,
            status=AdPublication.Status.PAUSED,
            row_id="LINKED-ROW",
            address="Linked address",
        )

        AvitoListing.objects.create(
            workspace=workspace,
            avito_account=account,
            publication=linked_active_publication,
            avito_id="24122281",
            status="active",
            title="Linked active listing",
        )

        old_dt = timezone.now() - timedelta(days=90)
        fresh_dt = timezone.now() - timedelta(days=5)

        AdPublication.objects.filter(id=old_publication.id).update(created_at=old_dt)
        AdPublication.objects.filter(id=active_publication.id).update(created_at=old_dt)
        AdPublication.objects.filter(id=linked_active_publication.id).update(created_at=old_dt)
        AdPublication.objects.filter(id=fresh_publication.id).update(created_at=fresh_dt)

        result = archive_stale_publications(
            workspace=workspace,
            older_than_days=60,
        )

        old_publication.refresh_from_db()
        fresh_publication.refresh_from_db()
        active_publication.refresh_from_db()
        linked_active_publication.refresh_from_db()

        self.assertEqual(result.archived_publications, 1)
        self.assertEqual(old_publication.status, AdPublication.Status.ARCHIVED)
        self.assertIsNotNone(old_publication.archived_at)

        self.assertEqual(fresh_publication.status, AdPublication.Status.PAUSED)
        self.assertEqual(active_publication.status, AdPublication.Status.ACTIVE)
        self.assertEqual(linked_active_publication.status, AdPublication.Status.PAUSED)
        self.assertEqual(AvitoListing.objects.filter(publication=linked_active_publication).count(), 1)

    def test_legacy_product_random_and_toggle_routes_are_disabled(self):
        with self.assertRaises(NoReverseMatch):
            reverse("product-random-api", args=[1])

        with self.assertRaises(NoReverseMatch):
            reverse("toggle-product-active-api", args=[1])

    def test_legacy_schedule_price_updates_is_not_in_beat_schedule(self):
        beat_schedule = celery_app.conf.beat_schedule

        self.assertNotIn("schedule_price_updates_every_minute", beat_schedule)
        self.assertIn("run_due_ad_generation_tasks_every_minute", beat_schedule)
        self.assertEqual(
            beat_schedule["run_due_ad_generation_tasks_every_minute"]["task"],
            "avitotask.tasks.run_due_ad_generation_tasks",
        )
