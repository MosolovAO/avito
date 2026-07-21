import json

from django.core.management.base import BaseCommand, CommandError

from avitotask.models import AdCreative, AdPublication, AvitoListing
from avitotask.services.ad_publication_dates import parse_avito_date


DATE_END_KEYS = ("DateEnd", "date_end")
LISTING_DATE_END_FIELDS = (
    ("base_data", DATE_END_KEYS),
    ("option_data", DATE_END_KEYS),
    ("raw_data", ("AvitoDateEnd", "DateEnd", "date_end")),
)
SAMPLE_LIMIT = 20


def build_model_report():
    return {
        "total": 0,
        "null": 0,
        "invalid_legacy": 0,
        "mismatch": 0,
        "source_mismatch": 0,
        "samples": [],
    }


def has_value(value):
    return value is not None and str(value).strip() != ""


def resolve_legacy_date(instance, fields):
    resolved = None
    invalid = []

    for field_name, keys in fields:
        payload = getattr(instance, field_name, None)

        if not isinstance(payload, dict):
            continue

        raw_value = None
        raw_key = None

        for key in keys:
            candidate = payload.get(key)

            if has_value(candidate):
                raw_value = candidate
                raw_key = key
                break

        if raw_key is None:
            continue

        parsed = parse_avito_date(raw_value)

        if parsed is None:
            invalid.append({
                "field": f"{field_name}.{raw_key}",
                "value": str(raw_value),
            })
            continue

        if resolved is None:
            resolved = parsed

    return resolved, invalid


def add_sample(report, *, object_id, problem, details=None):
    if len(report["samples"]) >= SAMPLE_LIMIT:
        return

    sample = {
        "id": object_id,
        "problem": problem,
    }

    if details:
        sample.update(details)

    report["samples"].append(sample)


def audit_creatives(queryset):
    report = build_model_report()
    allowed_sources = {
        AdCreative.PublishedEndSource.DEFAULT,
        AdCreative.PublishedEndSource.CREATIVE,
    }

    queryset = queryset.only(
        "id",
        "base_data",
        "option_data",
        "published_end",
        "published_end_source",
    ).order_by("id")

    for creative in queryset.iterator(chunk_size=500):
        report["total"] += 1

        legacy_date, invalid = resolve_legacy_date(
            creative,
            (
                ("base_data", DATE_END_KEYS),
                ("option_data", DATE_END_KEYS),
            ),
        )

        if invalid:
            report["invalid_legacy"] += 1
            add_sample(
                report,
                object_id=creative.id,
                problem="invalid_legacy",
                details={"values": invalid},
            )

        if creative.published_end is None:
            report["null"] += 1
            add_sample(
                report,
                object_id=creative.id,
                problem="published_end_null",
            )
        elif (
            legacy_date is not None
            and legacy_date != creative.published_end
        ):
            report["mismatch"] += 1
            add_sample(
                report,
                object_id=creative.id,
                problem="legacy_mismatch",
                details={
                    "published_end": creative.published_end.isoformat(),
                    "legacy_date_end": legacy_date.isoformat(),
                },
            )

        if creative.published_end_source not in allowed_sources:
            report["source_mismatch"] += 1
            add_sample(
                report,
                object_id=creative.id,
                problem="invalid_source",
                details={"source": creative.published_end_source},
            )

    return report


def audit_publications(queryset):
    report = build_model_report()
    allowed_sources = {
        AdPublication.PublishedEndSource.DEFAULT,
        AdPublication.PublishedEndSource.CREATIVE,
        AdPublication.PublishedEndSource.PUBLICATION,
    }

    queryset = (
        queryset
        .select_related("creative")
        .only(
            "id",
            "overrides",
            "published_end",
            "published_end_source",
            "creative__published_end",
        )
        .order_by("id")
    )

    for publication in queryset.iterator(chunk_size=500):
        report["total"] += 1

        override_date, invalid = resolve_legacy_date(
            publication,
            (("overrides", DATE_END_KEYS),),
        )

        if invalid:
            report["invalid_legacy"] += 1
            add_sample(
                report,
                object_id=publication.id,
                problem="invalid_legacy",
                details={"values": invalid},
            )

        if publication.published_end is None:
            report["null"] += 1
            add_sample(
                report,
                object_id=publication.id,
                problem="published_end_null",
            )

        source = publication.published_end_source

        if source not in allowed_sources:
            report["source_mismatch"] += 1
            add_sample(
                report,
                object_id=publication.id,
                problem="invalid_source",
                details={"source": source},
            )
            continue

        if source == AdPublication.PublishedEndSource.PUBLICATION:
            if (
                override_date is None
                or override_date != publication.published_end
            ):
                report["mismatch"] += 1
                add_sample(
                    report,
                    object_id=publication.id,
                    problem="publication_override_mismatch",
                    details={
                        "published_end": (
                            publication.published_end.isoformat()
                            if publication.published_end
                            else None
                        ),
                        "override_date_end": (
                            override_date.isoformat()
                            if override_date
                            else None
                        ),
                    },
                )
            continue

        if override_date is not None:
            report["source_mismatch"] += 1
            add_sample(
                report,
                object_id=publication.id,
                problem="inherited_publication_has_override",
                details={
                    "source": source,
                    "override_date_end": override_date.isoformat(),
                },
            )

        if (
            source == AdPublication.PublishedEndSource.CREATIVE
            and publication.published_end
            != publication.creative.published_end
        ):
            report["mismatch"] += 1
            add_sample(
                report,
                object_id=publication.id,
                problem="creative_date_mismatch",
                details={
                    "published_end": (
                        publication.published_end.isoformat()
                        if publication.published_end
                        else None
                    ),
                    "creative_published_end": (
                        publication.creative.published_end.isoformat()
                        if publication.creative.published_end
                        else None
                    ),
                },
            )

    return report


def audit_listings(queryset):
    report = build_model_report()

    queryset = (
        queryset
        .select_related("publication")
        .only(
            "id",
            "source",
            "publication_id",
            "base_data",
            "option_data",
            "raw_data",
            "published_end",
            "publication__published_end",
        )
        .order_by("id")
    )

    for listing in queryset.iterator(chunk_size=500):
        report["total"] += 1

        legacy_date, invalid = resolve_legacy_date(
            listing,
            LISTING_DATE_END_FIELDS,
        )

        if invalid:
            report["invalid_legacy"] += 1
            add_sample(
                report,
                object_id=listing.id,
                problem="invalid_legacy",
                details={"values": invalid},
            )

        if listing.published_end is None:
            report["null"] += 1

        if (
            legacy_date is not None
            and legacy_date != listing.published_end
        ):
            report["mismatch"] += 1
            add_sample(
                report,
                object_id=listing.id,
                problem="legacy_mismatch",
                details={
                    "published_end": (
                        listing.published_end.isoformat()
                        if listing.published_end
                        else None
                    ),
                    "legacy_date_end": legacy_date.isoformat(),
                },
            )

        if (
            listing.source == AvitoListing.Source.SERVICE
            and listing.publication_id is not None
            and listing.published_end
            != listing.publication.published_end
        ):
            report["mismatch"] += 1
            add_sample(
                report,
                object_id=listing.id,
                problem="linked_publication_mismatch",
                details={
                    "published_end": (
                        listing.published_end.isoformat()
                        if listing.published_end
                        else None
                    ),
                    "publication_published_end": (
                        listing.publication.published_end.isoformat()
                        if listing.publication.published_end
                        else None
                    ),
                },
            )

    return report


class Command(BaseCommand):
    help = (
        "Проверяет перенос legacy DateEnd в каноническое "
        "поле published_end."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace-id",
            type=int,
            default=None,
        )
        parser.add_argument(
            "--no-fail",
            action="store_true",
            help="Только вывести отчёт, не завершать команду с ошибкой.",
        )

    def handle(self, *args, **options):
        workspace_id = options["workspace_id"]

        creatives = AdCreative.objects.all()
        publications = AdPublication.objects.all()
        listings = AvitoListing.objects.all()

        if workspace_id is not None:
            creatives = creatives.filter(workspace_id=workspace_id)
            publications = publications.filter(workspace_id=workspace_id)
            listings = listings.filter(workspace_id=workspace_id)

        report = {
            "workspace_id": workspace_id,
            "creative": audit_creatives(creatives),
            "publication": audit_publications(publications),
            "listing": audit_listings(listings),
        }

        report["critical"] = sum(
            report[model][counter]
            for model in ("creative", "publication", "listing")
            for counter in ("mismatch", "source_mismatch")
        )
        report["critical"] += (
            report["creative"]["null"]
            + report["publication"]["null"]
        )

        self.stdout.write(
            json.dumps(
                report,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )

        if report["critical"] and not options["no_fail"]:
            raise CommandError(
                "Audit published_end обнаружил "
                f"{report['critical']} критических проблем."
            )

        if report["critical"] == 0:
            self.stdout.write(
                self.style.SUCCESS("Audit published_end пройден.")
            )