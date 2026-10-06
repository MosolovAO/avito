from datetime import datetime, timedelta, timezone

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User, Workspace, WorkspaceMembership
from avitotask.models import AvitoAccount
from calls.models import Call


class CallDailyReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("daily-owner@example.com")
        cls.viewer = User.objects.create_user("daily-viewer@example.com")
        cls.other_owner = User.objects.create_user("daily-other@example.com")
        cls.workspace = Workspace.objects.create(
            name="Daily", slug="calls-daily", owner=cls.owner,
        )
        cls.other_workspace = Workspace.objects.create(
            name="Foreign", slug="calls-daily-foreign", owner=cls.other_owner,
        )
        for user, workspace, role in (
            (cls.owner, cls.workspace, WorkspaceMembership.Role.OWNER),
            (cls.viewer, cls.workspace, WorkspaceMembership.Role.VIEWER),
            (cls.other_owner, cls.other_workspace, WorkspaceMembership.Role.OWNER),
        ):
            WorkspaceMembership.objects.create(user=user, workspace=workspace, role=role)
        cls.account = AvitoAccount.objects.create(workspace=cls.workspace, name="Основной")
        cls.second_account = AvitoAccount.objects.create(workspace=cls.workspace, name="Второй")
        cls.foreign_account = AvitoAccount.objects.create(workspace=cls.other_workspace, name="Чужой")

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)
        self.client.defaults["HTTP_X_WORKSPACE_ID"] = str(self.workspace.pk)
        self.params = {"avito_account_id": self.account.pk, "date": "2026-09-29"}
        self.url = "/api/calls/reports/daily/"

    def make_report(self, external_id, when, text, account=None, phone="+70000000001"):
        account = account or self.account
        return Call.objects.create(
            workspace=account.workspace, avito_account=account,
            external_id=external_id, occurred_at=when,
            buyer_phone=phone, report_text=text,
        )

    def test_daily_report_preserves_text_and_orders_calls_chronologically(self):
        self.make_report("later", datetime(2026, 9, 29, 10, tzinfo=timezone.utc), "Виктория\n40 кубов")
        self.make_report("first", datetime(2026, 9, 29, 9, tzinfo=timezone.utc), "  Клиент перезвонит\nМосква  ")
        self.make_report("same-time", datetime(2026, 9, 29, 10, tzinfo=timezone.utc), "Заказ подтвержден")

        response = self.client.get(self.url, self.params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {
            "avito_account_id": self.account.pk,
            "account_name": "Основной",
            "date": "2026-09-29",
            "report_count": 3,
            "report_text": (
                "Вторник, 29 сентября\nОсновной\n\n"
                "+7 (000) 000-00-01\n  Клиент перезвонит\nМосква  \n\n"
                "+7 (000) 000-00-01\nВиктория\n40 кубов\n\n"
                "+7 (000) 000-00-01\nЗаказ подтвержден"
            ),
        })

    def test_daily_report_uses_moscow_midnight_boundaries(self):
        start = datetime(2026, 9, 28, 21, tzinfo=timezone.utc)
        self.make_report("before", start - timedelta(seconds=1), "Вчера")
        self.make_report("start", start, "Начало дня")
        self.make_report("last", start + timedelta(days=1, seconds=-1), "Конец дня")
        self.make_report("after", start + timedelta(days=1), "Завтра")

        response = self.client.get(self.url, self.params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["report_count"], 2)
        self.assertEqual(response.data["report_text"], "Вторник, 29 сентября\nОсновной\n\n+7 (000) 000-00-01\nНачало дня\n\n+7 (000) 000-00-01\nКонец дня")

    def test_daily_report_is_not_limited_by_pagination_or_search(self):
        start = datetime(2026, 9, 29, 9, tzinfo=timezone.utc)
        reports = [f"Отчет {index}" for index in range(105)]
        for index, text in enumerate(reports):
            self.make_report(str(index), start + timedelta(seconds=index), text)

        response = self.client.get(self.url, {
            **self.params, "search": "Нет совпадений", "page": 2, "page_size": 1,
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["report_count"], 105)
        self.assertEqual(response.data["report_text"], "Вторник, 29 сентября\nОсновной\n\n" + "\n\n".join(f"+7 (000) 000-00-01\n{text}" for text in reports))

    def test_daily_report_returns_empty_text_without_saved_reports(self):
        when = datetime(2026, 9, 29, 9, tzinfo=timezone.utc)
        for index, text in enumerate(("", " \n\t\u00a0")):
            self.make_report(str(index), when, text)

        response = self.client.get(self.url, self.params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["report_count"], 0)
        self.assertEqual(response.data["report_text"], "")

    def test_daily_report_excludes_other_accounts_and_inconsistent_workspace(self):
        when = datetime(2026, 9, 29, 9, tzinfo=timezone.utc)
        self.make_report("main", when, "Наш отчет")
        self.make_report("second", when, "Второй аккаунт", self.second_account)
        self.make_report("foreign", when, "Чужой кабинет", self.foreign_account)
        inconsistent = self.make_report("inconsistent", when, "Неверный кабинет")
        Call.objects.filter(pk=inconsistent.pk).update(workspace=self.other_workspace)

        response = self.client.get(self.url, self.params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["report_count"], 1)
        self.assertEqual(response.data["report_text"], "Вторник, 29 сентября\nОсновной\n\n+7 (000) 000-00-01\nНаш отчет")
        for account_id in (self.foreign_account.pk, 999999):
            with self.subTest(account_id=account_id):
                denied = self.client.get(self.url, {**self.params, "avito_account_id": account_id})
                self.assertEqual(denied.status_code, 404)

    def test_daily_report_requires_valid_account_and_date(self):
        for params, field in (
            ({"avito_account_id": self.account.pk}, "date"),
            ({"date": "2026-09-29"}, "avito_account_id"),
            ({**self.params, "date": "2026-09-31"}, "date"),
            ({**self.params, "date": ""}, "date"),
            ({**self.params, "avito_account_id": 0}, "avito_account_id"),
        ):
            with self.subTest(params=params):
                response = self.client.get(self.url, params)
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.data)

    def test_daily_report_respects_call_access_roles(self):
        for role, user in (
            (WorkspaceMembership.Role.OWNER, self.owner),
            (WorkspaceMembership.Role.ADMIN, self.viewer),
            (WorkspaceMembership.Role.MANAGER, self.viewer),
            (WorkspaceMembership.Role.ANALYST, self.viewer),
            (WorkspaceMembership.Role.VIEWER, self.viewer),
        ):
            with self.subTest(role=role):
                WorkspaceMembership.objects.filter(user=user, workspace=self.workspace).update(role=role)
                self.client.force_authenticate(user=user)
                response = self.client.get(self.url, self.params)
                self.assertEqual(response.status_code, 403 if role == WorkspaceMembership.Role.VIEWER else 200)

    def test_daily_report_includes_formatted_phone_before_each_summary(self):
        self.account.name = "Третий авито"
        self.account.save(update_fields=["name"])
        self.make_report(
            "diana", datetime(2026, 9, 28, 9, tzinfo=timezone.utc),
            "Диана\nКирпич / Москва / Перезвонит клиенту", phone="+79622491936",
        )
        self.make_report(
            "victoria", datetime(2026, 9, 28, 10, tzinfo=timezone.utc),
            "Виктория\nГСБ / Москва / Перезвонит клиенту", phone="+79065436645",
        )

        response = self.client.get(self.url, {**self.params, "date": "2026-09-28"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["report_text"], (
            "Понедельник, 28 сентября\nТретий авито\n\n"
            "+7 (962) 249-19-36\nДиана\nКирпич / Москва / Перезвонит клиенту\n\n"
            "+7 (906) 543-66-45\nВиктория\nГСБ / Москва / Перезвонит клиенту"
        ))
        self.assertEqual(response.data["report_count"], 2)

    def test_daily_report_formats_russian_phones_and_preserves_other_phone_values(self):
        cases = (
            ("+79622491936", "+7 (962) 249-19-36"),
            ("89622491936", "+7 (962) 249-19-36"),
            ("9622491936", "+7 (962) 249-19-36"),
            ("+7 (962) 249-19-36", "+7 (962) 249-19-36"),
            ("+7 (962) ***-**-36", "+7 (962) ***-**-36"),
            ("+12025550123", "+12025550123"),
            ("", "Номер неизвестен"),
        )
        start = datetime(2026, 9, 29, 9, tzinfo=timezone.utc)
        for index, (phone, _) in enumerate(cases):
            self.make_report(str(index), start + timedelta(seconds=index), f"Отчет {index}", phone=phone)

        response = self.client.get(self.url, self.params)

        self.assertEqual(response.status_code, 200)
        blocks = [f"{expected}\nОтчет {index}" for index, (_, expected) in enumerate(cases)]
        self.assertEqual(response.data["report_text"], "Вторник, 29 сентября\nОсновной\n\n" + "\n\n".join(blocks))
        self.assertEqual(response.data["report_count"], 7)

    def test_daily_report_requires_authentication(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(self.url, self.params)

        self.assertEqual(response.status_code, 401)
