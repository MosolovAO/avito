import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0002_rename_clicks_avitolistingdailystats_contacts"),
    ]

    operations = [
        migrations.CreateModel(
            name="AvitoStatsSyncState",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("not_started", "Не запускалась"),
                            ("queued", "В очереди"),
                            ("running", "Выполняется"),
                            ("success", "Успешно"),
                            ("error", "Ошибка"),
                        ],
                        default="not_started",
                        max_length=20,
                    ),
                ),
                ("requested_date_from", models.DateField(blank=True, null=True)),
                ("requested_date_to", models.DateField(blank=True, null=True)),
                ("coverage_from", models.DateField(blank=True, null=True)),
                ("coverage_to", models.DateField(blank=True, null=True)),
                ("requested_at", models.DateTimeField(blank=True, null=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("last_successful_at", models.DateTimeField(blank=True, null=True)),
                ("error", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "avito_account",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="analytics_stats_sync",
                        to="avitotask.avitoaccount",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="avito_stats_sync_states",
                        to="accounts.workspace",
                    ),
                ),
            ],
            options={
                "verbose_name": "Состояние синхронизации статистики Avito",
                "verbose_name_plural": "Состояния синхронизации статистики Avito",
                "indexes": [
                    models.Index(
                        fields=["workspace", "status"],
                        name="idx_an_avsync_ws_status",
                    ),
                ],
            },
        ),
    ]