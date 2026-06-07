import hashlib
import json
import random
import re
import string
from dataclasses import dataclass

from datetime import timedelta
from django.utils import timezone

from django.db import transaction
from django.template import Context, Template

from avitotask.services.ad_export_state import mark_avito_accounts_export_dirty
from avitotask.models import (
    AdBatch,
    AdCreative,
    AdGenerationTask,
    AdPublication,
)

from avitotask.services.ad_publication_dates import (
    DATE_END_FIELD,
    PUBLICATION_EXTENSION_DAYS,
    format_avito_date,
)

MAX_CREATIVE_GENERATION_ATTEMPTS = 50
RECENT_CREATIVE_LOOKBACK_DAYS = 30
DUPLICATE_CREATIVE_MATCH_THRESHOLD = 2

AVITO_DEFAULT_CATEGORY = "Ремонт и строительство"


def force_default_avito_category(base_data):
    base_data = dict(base_data or {})
    base_data["Category"] = AVITO_DEFAULT_CATEGORY
    return base_data


def force_default_creative_date_end(base_data):
    base_data = dict(base_data or {})

    if not base_data.get(DATE_END_FIELD):
        date_end = timezone.localdate() + timedelta(days=PUBLICATION_EXTENSION_DAYS)
        base_data[DATE_END_FIELD] = format_avito_date(date_end)

    return base_data


class AdGenerationError(Exception):
    """Ошибка генерации объявления из задачи."""


@dataclass(frozen=True)
class CreativeCandidate:
    title: str
    description: str
    image_urls: list[str]
    base_data: dict
    option_data: dict
    identity_hash: str
    dedupe_title: str
    dedupe_description: str
    dedupe_images_hash: str


@dataclass(frozen=True)
class GenerationResult:
    batch: AdBatch
    creative: AdCreative
    publications: list[AdPublication]


def generate_random_id(length=16):
    characters = string.ascii_letters + string.digits
    return "".join(random.choices(characters, k=length)).upper()


def process_dynamic_text(template_text):
    def replace_choices(match):
        choices = match.group(1).split('|')
        return random.choice(choices).strip()

    return re.sub(r'\[([^\]]+)\]', replace_choices, template_text or "")


def generate_ads_from_task(task_id, *, workspace, user=None, require_active=True):
    """
    Генерирует базовый креатив из AdGenerationTask.

    На этом шаге функция еще не создает AdPublication.
    Это будет добавлено отдельно, чтобы не смешивать генерацию креатива,
    уникальность и массовое создание строк CSV.
    """

    task = get_generation_task(task_id=task_id, workspace=workspace)
    validate_task_for_generation(task, require_active=require_active)

    with transaction.atomic():
        batch = AdBatch.objects.create(
            workspace=workspace,
            task=task,
            source=AdBatch.Source.AUTO,
            status=AdBatch.Status.DRAFT,
            created_by=user
        )

        candidate = build_unique_creative_candidate(task)

        creative = AdCreative.objects.create(
            workspace=workspace,
            task=task,
            batch=batch,
            source=AdCreative.Source.AUTO,
            title=candidate.title,
            description=candidate.description,
            image_urls=candidate.image_urls,
            base_data=candidate.base_data,
            option_data=candidate.option_data,
            identity_hash=candidate.identity_hash,
            dedupe_title=candidate.dedupe_title,
            dedupe_description=candidate.dedupe_description,
            dedupe_images_hash=candidate.dedupe_images_hash,
        )
        publications = create_publications_for_creative(
            task=task,
            batch=batch,
            creative=creative,
        )

        mark_avito_accounts_export_dirty(task.avito_accounts.all())

        batch.total_creatives = 1
        batch.total_publications = len(publications)
        batch.status = AdBatch.Status.COMPLETED
        batch.save(update_fields=['total_creatives', 'total_publications', 'status'])

    return GenerationResult(
        batch=batch,
        creative=creative,
        publications=publications,
    )


def create_manual_mass_posting(
        *,
        workspace,
        avito_accounts,
        addresses,
        title,
        description,
        image_urls=None,
        base_data=None,
        option_data=None,
        user=None
):
    """
    Создает ручной масс-постинг через те же сущности, что и автогенерация.
    """
    validate_manual_mass_posting_data(
        avito_accounts=avito_accounts,
        addresses=addresses,
        title=title,
        description=description,
    )

    image_urls = list(image_urls or [])
    base_data = force_default_creative_date_end(
        force_default_avito_category(base_data)
    )
    option_data = dict(option_data or {})

    dedupe_data = build_creative_dedupe_data(
        title=title,
        description=description,
        image_urls=image_urls,
    )
    duplicate = find_recent_similar_creative(workspace=workspace, **dedupe_data)
    if duplicate is not None:
        raise AdGenerationError(f"Похожий креатив уже существует: #{duplicate.id}")

    with transaction.atomic():
        batch = AdBatch.objects.create(
            workspace=workspace,
            task=None,
            source=AdBatch.Source.MANUAL,
            status=AdBatch.Status.DRAFT,
            created_by=user
        )

        creative = AdCreative.objects.create(
            workspace=workspace,
            task=None,
            batch=batch,
            source=AdCreative.Source.MANUAL,
            title=title,
            description=description,
            image_urls=image_urls,
            base_data=base_data,
            option_data=option_data,
            identity_hash=build_identity_hash(
                title=title,
                description=description,
                image_urls=image_urls,
                base_data=base_data,
                option_data=option_data,
            ),
            dedupe_title=dedupe_data["dedupe_title"],
            dedupe_description=dedupe_data["dedupe_description"],
            dedupe_images_hash=dedupe_data["dedupe_images_hash"],
        )

        publications = create_manual_publications_for_creative(
            workspace=workspace,
            avito_accounts=avito_accounts,
            addresses=addresses,
            batch=batch,
            creative=creative,

        )

        mark_avito_accounts_export_dirty(avito_accounts)

        batch.total_creatives = 1
        batch.total_publications = len(publications)
        batch.status = AdBatch.Status.COMPLETED
        batch.save(update_fields=['total_creatives', 'total_publications', 'status'])

    return GenerationResult(
        batch=batch,
        creative=creative,
        publications=publications,
    )


def validate_manual_mass_posting_data(*, avito_accounts, addresses, title, description):
    if not title:
        raise AdGenerationError("У ручного объявления нет заголовка.")
    if not description:
        raise AdGenerationError("У ручного объявления нет описания.")
    if not addresses:
        raise AdGenerationError("У ручного объявления нет адресов.")
    if not avito_accounts:
        raise AdGenerationError("У ручного объявления нет аккаунтов Avito.")


def get_generation_task(task_id, *, workspace):
    return (
        AdGenerationTask.objects
        .select_related("workspace", "category")
        .prefetch_related(
            "avito_accounts",
            "adgenerationtaskoptionassignment_set__option",
            "main_image_assets",
            "additional_image_assets",
        )
        .get(id=task_id, workspace=workspace)
    )


def validate_task_for_generation(task, *, require_active=True):
    if require_active and not task.is_active:
        raise AdGenerationError("Задача генерации не активна")
    if not task.titles:
        raise AdGenerationError("У задачи нет заголовков")
    if not task.descriptions:
        raise AdGenerationError("У задачи нет описаний")
    if not task.main_image_assets.exists():
        raise AdGenerationError("У задачи нет основных изображений")
    if not task.addresses:
        raise AdGenerationError("У задачи нет адресов")
    if not task.avito_accounts.exists():
        raise AdGenerationError("У задачи нет аккаунтов Avito")


def build_unique_creative_candidate(task):
    for _ in range(MAX_CREATIVE_GENERATION_ATTEMPTS):
        candidate = build_creative_candidate(task)

        duplicate = find_recent_similar_creative(
            workspace=task.workspace,
            dedupe_title=candidate.dedupe_title,
            dedupe_description=candidate.dedupe_description,
            dedupe_images_hash=candidate.dedupe_images_hash,
        )
        if duplicate is None:
            return candidate

    raise AdGenerationError(
        "Не удалось подобрать уникальный креатив. "
        "За последние 30 дней уже есть похожие креативы."
    )


def build_creative_candidate(task):
    title = random.choice(task.titles)
    description_template = choose_description(task)
    image_urls = choose_image_urls(task)

    processed_description_template = process_dynamic_text(description_template)

    rendered_description = render_description(
        processed_template=processed_description_template,
        title=title,
        sku=generate_random_id(),
    )

    description_for_hash = render_description(
        processed_template=processed_description_template,
        title=title,
        sku="__SKU__",
    )

    base_data = build_base_data(task)
    option_data = build_option_data(task)

    identity_hash = build_identity_hash(
        title=title,
        description=description_for_hash,
        image_urls=image_urls,
        base_data=base_data,
        option_data=option_data,
    )

    dedupe_data = build_creative_dedupe_data(
        title=title,
        description=description_for_hash,
        image_urls=image_urls,
    )

    return CreativeCandidate(
        title=title,
        description=rendered_description,
        image_urls=image_urls,
        base_data=base_data,
        option_data=option_data,
        identity_hash=identity_hash,
        dedupe_title=dedupe_data["dedupe_title"],
        dedupe_description=dedupe_data["dedupe_description"],
        dedupe_images_hash=dedupe_data["dedupe_images_hash"],
    )


def choose_description(task):
    descriptions = task.descriptions

    if isinstance(descriptions, dict):
        values = [value for value in descriptions.values() if value]
    else:
        values = [value for value in descriptions if value]

    if not values:
        raise AdGenerationError("У задачи нет доступных описания")

    return random.choice(values)


def choose_image_urls(task):
    main_assets = list(task.main_image_assets.all())
    if not main_assets:
        raise AdGenerationError("У задачи нет основных изображений")

    main_asset = random.choice(main_assets)

    additional_assets = list(task.additional_image_assets.all())
    if len(additional_assets) <= 9:
        selected_additional = additional_assets
    else:
        selected_additional = random.sample(additional_assets, 9)

    return [
        main_asset.url,
        *[asset.url for asset in selected_additional],
    ]


def render_description(*, processed_template, title, sku):
    template = Template(processed_template)
    context = Context({
        "TITLE": title,
        "SKU": sku,
    })

    return template.render(context)


def build_base_data(task):
    base_data = force_default_creative_date_end(
        force_default_avito_category(task.base_data)
    )

    base_data.update({
        "Price": task.price or 0,
    })

    return base_data


def normalize_option_data_value(assignment):
    value = assignment.selected_value

    if assignment.option.allow_multiple_options:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]

        normalized = str(value).strip() if value is not None else ""
        return [normalized] if normalized else []

    if isinstance(value, list):
        return str(value[0]).strip() if value else ""

    return str(value).strip() if value is not None else ""


def build_option_data(task):
    assignments = task.adgenerationtaskoptionassignment_set.select_related("option")

    option_data = {}

    for assignment in assignments:
        key = assignment.option.option_title_en.strip()
        value = normalize_option_data_value(assignment)

        if not key or value == [] or value == "":
            continue

        option_data[key] = value

    return option_data


def create_publications_for_creative(*, task, batch, creative):
    avito_accounts = list(task.avito_accounts.all())
    addresses = list(task.addresses or [])

    publications = []

    for avito_account in avito_accounts:
        for address in addresses:
            address_text, address_data = normalize_address(address)

            publications.append(
                AdPublication(
                    workspace=task.workspace,
                    avito_account=avito_account,
                    creative=creative,
                    task=task,
                    batch=batch,
                    source=AdPublication.Source.AUTO,
                    status=AdPublication.Status.ACTIVE,
                    row_id=generate_publication_row_id(),
                    address=address_text,
                    address_data=address_data,
                    overrides={},
                )
            )
    return AdPublication.objects.bulk_create(publications)


def create_manual_publications_for_creative(
        *,
        workspace,
        avito_accounts,
        addresses,
        batch,
        creative
):
    publications = []

    for avito_account in avito_accounts:
        if avito_account.workspace_id != workspace.id:
            raise AdGenerationError("Аккаунт Avito принадлежит другому workspace.")

        for address in addresses:
            address_text, address_data = normalize_address(address)

            publications.append(
                AdPublication(
                    workspace=workspace,
                    avito_account=avito_account,
                    creative=creative,
                    task=None,
                    batch=batch,
                    source=AdPublication.Source.MANUAL,
                    status=AdPublication.Status.ACTIVE,
                    row_id=generate_publication_row_id(),
                    address=address_text,
                    address_data=address_data,
                    overrides={},
                )
            )

    return AdPublication.objects.bulk_create(publications)


def normalize_address(address):
    if isinstance(address, dict):
        address_text = (
                address.get("Address")
                or address.get("address")
                or address.get("full_address")
                or address.get("value")
                or ""
        )

        return str(address_text), address
    return str(address), {}


def generate_publication_row_id():
    return f"AD-{generate_random_id()}"


def build_identity_hash(*, title, description, image_urls, base_data, option_data):
    payload = {
        "title": title,
        "description": description,
        "image_urls": image_urls,
        "base_data": base_data,
        "option_data": option_data
    }

    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()


def build_creative_dedupe_data(*, title, description, image_urls):
    return {
        "dedupe_title": normalize_text_for_dedupe(title),
        "dedupe_description": normalize_text_for_dedupe(description),
        "dedupe_images_hash": build_images_hash(image_urls),
    }


def normalize_text_for_dedupe(value):
    return " ".join(str(value or "").split()).casefold()


def build_images_hash(image_urls):
    normalized_urls = sorted(
        str(url).strip()
        for url in image_urls
        if str(url).strip()
    )
    serialized = json.dumps(normalized_urls, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def find_recent_similar_creative(*, workspace, dedupe_title, dedupe_description, dedupe_images_hash):
    cutoff = timezone.now() - timedelta(days=RECENT_CREATIVE_LOOKBACK_DAYS)

    creatives = AdCreative.objects.filter(
        workspace=workspace,
        source__in=[AdCreative.Source.AUTO, AdCreative.Source.MANUAL],
        created_at__gte=cutoff,
    ).only("id", "dedupe_title", "dedupe_description", "dedupe_images_hash")

    for creative in creatives.iterator():
        matches = 0
        if creative.dedupe_title == dedupe_title:
            matches += 1
        if creative.dedupe_description == dedupe_description:
            matches += 1
        if creative.dedupe_images_hash == dedupe_images_hash:
            matches += 1

        if matches >= DUPLICATE_CREATIVE_MATCH_THRESHOLD:
            return creative

    return None
