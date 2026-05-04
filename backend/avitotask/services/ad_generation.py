import hashlib
import json
import random
import re
import string
from dataclasses import dataclass

from django.db import transaction
from django.template import Context, Template

from avitotask.services.ad_export_state import mark_avito_accounts_export_dirty
from avitotask.models import (
    AdBatch,
    AdCreative,
    AdGenerationTask,
    AdPublication,
)

MAX_CREATIVE_GENERATION_ATTEMPTS = 50


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


def generate_ads_from_task(task_id, *, workspace, user=None):
    """
    Генерирует базовый креатив из AdGenerationTask.

    На этом шаге функция еще не создает AdPublication.
    Это будет добавлено отдельно, чтобы не смешивать генерацию креатива,
    уникальность и массовое создание строк CSV.
    """

    task = get_generation_task(task_id=task_id, workspace=workspace)
    validate_task_for_generation(task)

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
    base_data = dict(base_data or {})
    option_data = dict(option_data or {})

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
            "adgenerationtaskoptionassignment_set__option"
        )
        .get(id=task_id, workspace=workspace)
    )


def validate_task_for_generation(task):
    if not task.is_active:
        raise AdGenerationError("Задача генерации не активна")
    if not task.titles:
        raise AdGenerationError("У задачи нет заголовков")
    if not task.descriptions:
        raise AdGenerationError("У задачи нет описаний")
    if not task.main_images:
        raise AdGenerationError("У задачи нет основных изображений")
    if not task.addresses:
        raise AdGenerationError("У задачи нет адресов")
    if not task.avito_accounts.exists():
        raise AdGenerationError("У задачи нет аккаунтов Avito")


def build_unique_creative_candidate(task):
    """
    Быстро подбирает еще не созданный креатив.

    Вместо бесконечного while True делаем ограниченное число попыток.
    Проверка дубля идет по identity_hash, который уже индексирован в БД.
    """
    used_hashes = set(
        AdCreative.objects.filter(
            workspace=task.workspace,
            task=task,
            identity_hash__isnull=False,
        )
        .exclude(identity_hash="")
        .values_list("identity_hash", flat=True)
    )

    for _ in range(MAX_CREATIVE_GENERATION_ATTEMPTS):
        candidate = build_creative_candidate(task)

        if candidate.identity_hash not in used_hashes:
            return candidate

    raise AdGenerationError(
        "Не удалось подобрать уникальное объявление. "
        "Возможные комбинации для этой задачи уже исчерпаны или слишком часто повторяются."
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

    return CreativeCandidate(
        title=title,
        description=rendered_description,
        image_urls=image_urls,
        base_data=base_data,
        option_data=option_data,
        identity_hash=identity_hash,
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
    main_images = random.choice(task.main_images)

    additional_images = task.additional_images or []
    if len(additional_images) <= 9:
        selected_additional = list(additional_images)
    else:
        selected_additional = random.sample(additional_images, 9)
    return [main_images, *selected_additional]


def render_description(*, processed_template, title, sku):
    template = Template(processed_template)
    context = Context({
        "TITLE": title,
        "SKU": sku,
    })

    return template.render(context)


def build_base_data(task):
    base_data = dict(task.base_data or {})

    base_data.update({
        "Category": task.category.category if task.category else "",
        "Price": task.price or 0,
    })

    return base_data


def build_option_data(task):
    assignments = task.adgenerationtaskoptionassignment_set.all()

    return {
        assigment.option.option_title_en: assigment.selected_value for assigment in assignments
    }


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
