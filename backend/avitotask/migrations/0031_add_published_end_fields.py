from datetime import date, datetime, timedelta

from django.db import migrations, models
from django.utils import timezone


BATCH_SIZE = 500
PUBLICATION_LIFETIME_DAYS = 30

DATE_END_KEYS = ("DateEnd", "date_end")
RAW_DATE_END_KEYS = ("AvitoDateEnd", "DateEnd", "date_end")


def has_value(value):
    return value is not None and str(value).strip() != ""


def get_payload_value(payload, keys):
    if not isinstance(payload, dict):
        return None

    for key in keys:
        value = payload.get(key)

        if has_value(value):
            return value

    return None


def normalize_datetime_to_local_date(value):
    if timezone.is_naive(value):
        value = timezone.make_aware(
            value,
            timezone.get_current_timezone(),
        )

    return timezone.localtime(value).date()


def parse_legacy_date(value):
    if not has_value(value):
        return None

    if isinstance(value, datetime):
        return normalize_datetime_to_local_date(value)

    if isinstance(value, date):
        return value

    raw_value = str(value).strip()

    try:
        parsed = datetime.fromisoformat(
            raw_value.replace("Z", "+00:00"),
        )
    except ValueError:
        parsed = None

    if parsed is not None:
        return normalize_datetime_to_local_date(parsed)

    for date_format in (
        "%d.%m.%Y",
        "%d.%m.%y",
        "%Y-%m-%d",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d.%m.%y %H:%M:%S",
        "%d.%m.%y %H:%M",
    ):
        try:
            parsed = datetime.strptime(raw_value, date_format)
        except ValueError:
            continue

        return normalize_datetime_to_local_date(parsed)

    return None


def date_from_payloads(payloads, keys, counters, counter_name):
    for payload in payloads:
        value = get_payload_value(payload, keys)

        if not has_value(value):
            continue

        parsed = parse_legacy_date(value)

        if parsed is not None:
            return parsed

        counters[counter_name] += 1

    return None


def created_date_plus_lifetime(created_at):
    if created_at is None:
        created_date = timezone.localdate()
    elif isinstance(created_at, datetime):
        created_date = normalize_datetime_to_local_date(created_at)
    else:
        created_date = created_at

    return created_date + timedelta(days=PUBLICATION_LIFETIME_DAYS)


def backfill_published_end(apps, schema_editor):
    AdCreative = apps.get_model("avitotask", "AdCreative")
    AdPublication = apps.get_model("avitotask", "AdPublication")
    AvitoListing = apps.get_model("avitotask", "AvitoListing")

    counters = {
        "creative_invalid": 0,
        "publication_invalid": 0,
        "listing_invalid": 0,
        "creative_updated": 0,
        "publication_updated": 0,
        "listing_updated": 0,
        "listing_without_date": 0,
    }

    # Нужен для старой логики get_creative_effective_date_end:
    # если у креатива нет собственной DateEnd, берётся максимальная
    # created_at + 30 среди публикаций без валидного override.
    default_dates_by_creative = {}

    publication_defaults = (
        AdPublication.objects
        .all()
        .only("creative_id", "created_at", "overrides")
        .order_by()
    )

    for publication in publication_defaults.iterator(chunk_size=BATCH_SIZE):
        override_value = get_payload_value(
            publication.overrides,
            DATE_END_KEYS,
        )

        if parse_legacy_date(override_value) is not None:
            continue

        default_end = created_date_plus_lifetime(publication.created_at)
        current_end = default_dates_by_creative.get(publication.creative_id)

        if current_end is None or default_end > current_end:
            default_dates_by_creative[publication.creative_id] = default_end

    creative_state = {}
    creatives_to_update = []

    creatives = (
        AdCreative.objects
        .all()
        .only(
            "id",
            "created_at",
            "base_data",
            "option_data",
            "published_end",
            "published_end_source",
        )
        .order_by()
    )

    for creative in creatives.iterator(chunk_size=BATCH_SIZE):
        explicit_end = date_from_payloads(
            [creative.base_data, creative.option_data],
            DATE_END_KEYS,
            counters,
            "creative_invalid",
        )

        if explicit_end is not None:
            published_end = explicit_end
            published_end_source = "creative"
        else:
            published_end = (
                default_dates_by_creative.get(creative.id)
                or created_date_plus_lifetime(creative.created_at)
            )
            published_end_source = "default"

        creative.published_end = published_end
        creative.published_end_source = published_end_source

        creative_state[creative.id] = (
            published_end,
            published_end_source,
        )
        creatives_to_update.append(creative)

    if creatives_to_update:
        AdCreative.objects.bulk_update(
            creatives_to_update,
            ["published_end", "published_end_source"],
            batch_size=BATCH_SIZE,
        )
        counters["creative_updated"] = len(creatives_to_update)

    publication_state = {}
    publications_to_update = []

    publications = (
        AdPublication.objects
        .all()
        .only(
            "id",
            "creative_id",
            "created_at",
            "overrides",
            "published_end",
            "published_end_source",
        )
        .order_by()
    )

    for publication in publications.iterator(chunk_size=BATCH_SIZE):
        override_end = date_from_payloads(
            [publication.overrides],
            DATE_END_KEYS,
            counters,
            "publication_invalid",
        )

        creative_end, creative_source = creative_state[
            publication.creative_id
        ]

        if override_end is not None:
            published_end = override_end
            published_end_source = "publication"
        elif creative_source == "creative":
            published_end = creative_end
            published_end_source = "creative"
        else:
            # Сохраняем прежнее поведение: до первого изменения креатива
            # default вычислялся отдельно от created_at каждой публикации.
            published_end = created_date_plus_lifetime(
                publication.created_at,
            )
            published_end_source = "default"

        publication.published_end = published_end
        publication.published_end_source = published_end_source

        publication_state[publication.id] = published_end
        publications_to_update.append(publication)

    if publications_to_update:
        AdPublication.objects.bulk_update(
            publications_to_update,
            ["published_end", "published_end_source"],
            batch_size=BATCH_SIZE,
        )
        counters["publication_updated"] = len(publications_to_update)

    listings_to_update = []

    listings = (
        AvitoListing.objects
        .all()
        .only(
            "id",
            "source",
            "publication_id",
            "base_data",
            "option_data",
            "raw_data",
            "published_end",
        )
        .order_by()
    )

    for listing in listings.iterator(chunk_size=BATCH_SIZE):
        explicit_end = date_from_payloads(
            [
                listing.base_data,
                listing.option_data,
                listing.raw_data,
            ],
            RAW_DATE_END_KEYS,
            counters,
            "listing_invalid",
        )

        if explicit_end is not None:
            published_end = explicit_end
        elif (
            listing.source == "service"
            and listing.publication_id in publication_state
        ):
            published_end = publication_state[listing.publication_id]
        else:
            published_end = None
            counters["listing_without_date"] += 1

        listing.published_end = published_end
        listings_to_update.append(listing)

    if listings_to_update:
        AvitoListing.objects.bulk_update(
            listings_to_update,
            ["published_end"],
            batch_size=BATCH_SIZE,
        )
        counters["listing_updated"] = len(listings_to_update)

    print(f"published_end backfill: {counters}")


class Migration(migrations.Migration):

    dependencies = [
        ("avitotask", "0030_backfill_task_autoload_category"),
    ]

    operations = [
        migrations.AddField(
            model_name="adcreative",
            name="published_end",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="adcreative",
            name="published_end_source",
            field=models.CharField(
                choices=[
                    ("default", "30 дней"),
                    ("creative", "Креатив"),
                ],
                default="default",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="adpublication",
            name="published_end",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="adpublication",
            name="published_end_source",
            field=models.CharField(
                choices=[
                    ("default", "30 дней"),
                    ("creative", "Креатив"),
                    ("publication", "Публикация"),
                ],
                default="default",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="avitolisting",
            name="published_end",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.RunPython(
            backfill_published_end,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddIndex(
            model_name="adcreative",
            index=models.Index(
                fields=["workspace", "published_end", "id"],
                name="idx_adcreative_ws_pubend",
            ),
        ),
        migrations.AddIndex(
            model_name="adpublication",
            index=models.Index(
                fields=[
                    "workspace",
                    "avito_account",
                    "published_end",
                    "id",
                ],
                name="idx_adpub_acc_pubend",
            ),
        ),
        migrations.AddIndex(
            model_name="avitolisting",
            index=models.Index(
                fields=[
                    "workspace",
                    "avito_account",
                    "published_end",
                    "id",
                ],
                name="idx_avlisting_acc_pubend",
            ),
        ),
    ]