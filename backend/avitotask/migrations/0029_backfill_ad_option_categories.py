from django.db import migrations
from django.db.models import OuterRef, Subquery


def backfill_ad_option_categories(apps, schema_editor):
    AdGenerationTask = apps.get_model(
        "avitotask",
        "AdGenerationTask",
    )
    AdCreative = apps.get_model(
        "avitotask",
        "AdCreative",
    )
    AdPublication = apps.get_model(
        "avitotask",
        "AdPublication",
    )
    AvitoListing = apps.get_model(
        "avitotask",
        "AvitoListing",
    )

    # Для автоматических креативов конечная категория достоверно
    # известна: она хранится в задаче генерации.
    task_category = (
        AdGenerationTask.objects
        .filter(pk=OuterRef("task_id"))
        .values("category_id")[:1]
    )

    AdCreative.objects.filter(
        source="auto",
        task_id__isnull=False,
        option_category_id__isnull=True,
    ).update(
        option_category_id=Subquery(task_category),
    )

    # Для связанных с публикациями service-listing переносим категорию
    # из креатива. API- и XLSX-импорты этот запрос не затрагивает.
    publication_category = (
        AdPublication.objects
        .filter(pk=OuterRef("publication_id"))
        .values("creative__option_category_id")[:1]
    )

    AvitoListing.objects.filter(
        source="service",
        publication_id__isnull=False,
        option_category_id__isnull=True,
    ).update(
        option_category_id=Subquery(publication_category),
    )

    # Старые ручные креативы намеренно остаются без категории.
    # base_data["Category"] содержит CSV-категорию и не используется
    # для восстановления конечной категории.
    #
    # API- и XLSX-импорты также остаются с option_category=NULL.


class Migration(migrations.Migration):
    dependencies = [
        ("avitotask", "0028_add_ad_option_categories"),
    ]

    operations = [
        migrations.RunPython(
            backfill_ad_option_categories,
            migrations.RunPython.noop,
        ),
    ]