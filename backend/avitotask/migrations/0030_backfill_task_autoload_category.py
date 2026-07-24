from django.db import migrations


DEFAULT_AUTOLOAD_CATEGORY = "Ремонт и строительство"


def backfill_task_autoload_category(apps, schema_editor):
    AdGenerationTask = apps.get_model(
        "avitotask",
        "AdGenerationTask",
    )
    AdCreative = apps.get_model(
        "avitotask",
        "AdCreative",
    )

    tasks_to_update = []

    for task in AdGenerationTask.objects.only("id", "base_data").iterator():
        base_data = dict(task.base_data or {})

        if str(base_data.get("Category") or "").strip():
            continue

        base_data["Category"] = DEFAULT_AUTOLOAD_CATEGORY
        task.base_data = base_data
        tasks_to_update.append(task)

    if tasks_to_update:
        AdGenerationTask.objects.bulk_update(
            tasks_to_update,
            ["base_data"],
            batch_size=500,
        )

    # Старый генератор всегда использовал это значение для автоматических
    # креативов. Исправляем и объявления, созданные до появления принудительной
    # подстановки, где могла сохраниться конечная категория.
    creatives_to_update = []

    for creative in (
        AdCreative.objects
        .filter(source="auto")
        .only("id", "base_data")
        .iterator()
    ):
        base_data = dict(creative.base_data or {})
        base_data["Category"] = DEFAULT_AUTOLOAD_CATEGORY

        creative.base_data = base_data
        creatives_to_update.append(creative)

    if creatives_to_update:
        AdCreative.objects.bulk_update(
            creatives_to_update,
            ["base_data"],
            batch_size=500,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("avitotask", "0029_backfill_ad_option_categories"),
    ]

    operations = [
        migrations.RunPython(
            backfill_task_autoload_category,
            migrations.RunPython.noop,
        ),
    ]