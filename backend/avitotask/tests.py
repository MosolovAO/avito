from django.test import TestCase
from avitotask.services.ad_editing import update_ad_creative, update_ad_publication
from avitotask.services.ad_export import (
    build_publication_export_row,
    export_avito_account_publications_to_csv,
)
from datetime import datetime

from avitotask.services.ad_schedule import (
    advance_task_schedule_after_run,
    initialize_task_schedule,
    run_due_ad_generation_tasks,
)

from avitotask.tasks import export_avito_account_csv_task, export_dirty_avito_accounts_csv_task
from accounts.models import User, Workspace
from avitotask.models import (
    AdGenerationTask,
    AdPublication,
    AvitoAccount,
)
from avitotask.services.ad_generation import (
    create_manual_mass_posting,
    generate_ads_from_task,
)

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
