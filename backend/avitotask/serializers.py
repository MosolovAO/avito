from uuid import uuid4
from django.urls import reverse

from django.db import transaction
from rest_framework import serializers
from .models import (
    ProductOptions,
    Category,
    AvitoAccount,
    AvitoOAuthToken,
    AvitoListing,
    AdPublication,
    AdBatch,
    AdCreative,
    AdGenerationTask,
    AdGenerationTaskOptionAssignment,
    AdImageAsset
)

from avitotask.services.ad_schedule import (
    AdScheduleError,
    FREQUENCY_TO_INTERVAL_DAYS,
    INTERVAL_DAYS_TO_FREQUENCY,
    normalize_schedule,
    recalculate_task_next_update_time,
)

from avitotask.services.avito_excel_import import (
    AvitoExcelImportError,
    import_avito_excel_file,
    preview_avito_excel_file,
)

DAY_KEYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']


class ProductOptionsSerializer(serializers.ModelSerializer):
    """Serializer for the ProductOptions model."""""
    option_title = serializers.CharField(source='option_title_ru', read_only=True)
    option_code = serializers.CharField(source='option_title_en', read_only=True)
    allow_multiple = serializers.BooleanField(source='allow_multiple_options', read_only=True)
    categories = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    class Meta:
        model = ProductOptions
        fields = [
            'id',
            'option_title',
            'option_code',
            'option_title_ru',
            'option_title_en',
            'allow_multiple',
            'allow_multiple_options',
            'categories',
        ]

    def validate_option_title_en(self, value):
        value = value.strip()

        if not value:
            raise serializers.ValidationError("Параметр автозагрузки не может быть пустым.")

        duplicate_exists = ProductOptions.objects.filter(
            option_title_en__iexact=value,
        ).exclude(
            pk=self.instance.pk if self.instance else None,
        ).exists()

        if duplicate_exists:
            raise serializers.ValidationError(
                "Опция с таким параметром автозагрузки уже существует."
            )

        return value

    def validate_option_title_ru(self, value):
        value = value.strip()

        if not value:
            raise serializers.ValidationError("Название опции не может быть пустым.")

        return value


class ProductOptionInputSerializer(serializers.Serializer):
    option_id = serializers.PrimaryKeyRelatedField(
        queryset=ProductOptions.objects.all(),
        source='option',
    )
    value = serializers.JSONField()

    def validate(self, attrs):
        option = attrs['option']
        value = attrs['value']

        if isinstance(value, str):
            values = [value.strip()]
        elif isinstance(value, list):
            values = [str(item).strip() for item in value if str(item).strip()]
        else:
            raise serializers.ValidationError({
                'value': 'Значение опции должно быть строкой или списком строк.'
            })

        if not values:
            raise serializers.ValidationError({
                'value': 'Укажите хотя бы одно значение опции.'
            })

        if not option.allow_multiple_options and len(values) > 1:
            raise serializers.ValidationError({
                'value': f'Опция "{option.option_title_ru}" принимает только одно значение.'
            })

        attrs['value'] = values
        return attrs


class ProductSerializer(serializers.ModelSerializer):
    """
    API serializer для frontend-совместимого /api/products/,
    но модель внутри уже AdGenerationTask.
    """
    main_images = serializers.SerializerMethodField()
    additional_images = serializers.SerializerMethodField()

    main_image_asset_ids = serializers.PrimaryKeyRelatedField(
        source="main_image_assets",
        queryset=AdImageAsset.objects.all(),
        many=True,
        required=False,
    )
    additional_image_asset_ids = serializers.PrimaryKeyRelatedField(
        source="additional_image_assets",
        queryset=AdImageAsset.objects.all(),
        many=True,
        required=False,
    )
    activate = serializers.BooleanField(source="is_active", required=False)
    category = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    descriptions = serializers.JSONField(required=False)
    options = ProductOptionInputSerializer(many=True, write_only=True, required=False)

    avito_account_ids = serializers.PrimaryKeyRelatedField(
        source="avito_accounts",
        queryset=AvitoAccount.objects.all(),
        many=True,
        required=False,
        write_only=True,
    )

    avito_accounts = serializers.SerializerMethodField()

    class Meta:
        model = AdGenerationTask
        fields = [
            "id",
            "workspace",
            "name",
            "url",
            "price",
            "price_randomization_enabled",
            "price_min",
            "price_max",
            "price_step",
            "activate",
            "schedule",
            "schedule_anchor_date",
            "schedule_timezone",
            "next_update_time",
            "last_run_at",
            "last_successful_run_at",
            "last_run_status",
            "last_run_error",
            "titles",
            "main_images",
            "additional_images",
            "descriptions",
            "addresses",
            "selected_options",
            "category",
            "base_data",
            "avito_account_ids",
            "avito_accounts",
            "options",
            "main_image_asset_ids",
            "additional_image_asset_ids",

        ]
        read_only_fields = [
            "workspace",
            "next_update_time",
            "last_run_at",
            "last_successful_run_at",
            "last_run_status",
            "last_run_error",
            "selected_options",
        ]

    def get_main_images(self, instance):
        return [asset.url for asset in instance.main_image_assets.all()]

    def get_additional_images(self, instance):
        return [asset.url for asset in instance.additional_image_assets.all()]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        workspace = self.context.get("workspace")

        if workspace is not None:
            self.fields["main_image_asset_ids"].queryset = AdImageAsset.objects.filter(workspace=workspace)
            self.fields["additional_image_asset_ids"].queryset = AdImageAsset.objects.filter(workspace=workspace)

        if workspace is not None:
            self.fields["avito_account_ids"].queryset = AvitoAccount.objects.filter(
                workspace=workspace,
            )

    def get_avito_accounts(self, instance):
        return [
            {
                "id": account.id,
                "name": account.name,
                "export_status": account.export_status,
            }
            for account in instance.avito_accounts.all()
        ]

    def _normalize_descriptions(self, value):
        """Приводит descriptions к формату модели Product.descriptions."""
        if value is None:
            return {}

        if isinstance(value, list):
            return {
                str(index): item
                for index, item in enumerate(value)
                if str(item).strip()
            }

        if isinstance(value, dict):
            return value

        raise serializers.ValidationError('descriptions должен быть списком или объектом.')

    def _resolve_category(self, value):
        if not value:
            return None

        category_name = str(value).strip()

        category = (
            Category.objects
            .filter(category__iexact=category_name)
            .first()
        )

        if category is None:
            raise serializers.ValidationError({
                "category": "Выбранная категория не найдена."
            })

        return category

    def _replace_options(self, task, options_data):
        AdGenerationTaskOptionAssignment.objects.filter(task=task).delete()

        assignments = [
            AdGenerationTaskOptionAssignment(
                task=task,
                option=item["option"],
                selected_value=item["value"],
            )
            for item in options_data
        ]
        AdGenerationTaskOptionAssignment.objects.bulk_create(assignments)

        task.selected_options = {
            item["option"].option_title_en: item["value"]
            for item in options_data
        }
        task.save(update_fields=["selected_options"])

    def _normalize_schedule(self, value):
        """Приводит расписание из frontend-формата к backend-формату."""
        if not value:
            return {}

        if isinstance(value, dict) and 'days' in value:
            days = value.get('days') or []
            return {
                DAY_KEYS[index]: time_value
                for index, time_value in enumerate(days[:7])
                if time_value
            }
        return value

    def _normalize_schedule_for_task(self, schedule, publication_interval_days):
        try:
            return normalize_schedule(
                schedule,
                publication_interval_days=publication_interval_days,
            )
        except AdScheduleError as exc:
            raise serializers.ValidationError({"schedule": str(exc)})

    def _refresh_next_update_time(self, task):
        try:
            recalculate_task_next_update_time(task)
        except AdScheduleError as exc:
            raise serializers.ValidationError({"schedule": str(exc)})

    def _valid_image_urls(self, value, field_name):
        if value is None:
            return []

        if not isinstance(value, list):
            raise serializers.ValidationError(f'{field_name} должен быть списком URL.')

        invalid_items = [
            item
            for item in value
            if not isinstance(item.src) or not item.strip()
        ]

        if invalid_items:
            raise serializers.ValidationError(
                f'{field_name} должен содержать только непустые строки URL.'
            )

        return [item.strip() for item in value]

    def valid_main_images(self, value):
        return self._valid_image_urls(value, 'main_images')

    def valid_additional_images(self, value):
        return self._valid_image_urls(value, 'additional_images')

    def validate_base_data(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                "base_data должен быть объектом."
            )

        base_data = dict(value)
        autoload_category = str(
            base_data.get("Category") or ""
        ).strip()

        if not autoload_category:
            raise serializers.ValidationError(
                "Укажите категорию для файла автозагрузки Avito."
            )

        base_data["Category"] = autoload_category
        return base_data

    @transaction.atomic
    def create(self, validated_data):
        avito_accounts = validated_data.pop("avito_accounts", [])
        options_data = validated_data.pop("options", [])
        category_value = validated_data.pop("category", None)
        main_image_assets = validated_data.pop("main_image_assets", [])
        additional_image_assets = validated_data.pop("additional_image_assets", [])

        if not validated_data.get("price_randomization_enabled", False):
            validated_data["price_min"] = 0
            validated_data["price_max"] = 0
            validated_data["price_step"] = 0

        validated_data["name"] = validated_data.get("name") or f"Задача {uuid4().hex[:8]}"
        validated_data["url"] = validated_data.get("url") or ""
        validated_data["category"] = self._resolve_category(category_value)
        validated_data["descriptions"] = self._normalize_descriptions(
            validated_data.get("descriptions", [])
        )

        schedule = validated_data.get("schedule")
        normalized_schedule = self._normalize_schedule_for_task(
            schedule,
            validated_data.get("publication_interval_days", 7),
        )
        validated_data["schedule"] = normalized_schedule
        validated_data["publication_interval_days"] = FREQUENCY_TO_INTERVAL_DAYS[
            normalized_schedule["frequency"]
        ]

        task = AdGenerationTask.objects.create(**validated_data)
        task.avito_accounts.set(avito_accounts)
        task.main_image_assets.set(main_image_assets)
        task.additional_image_assets.set(additional_image_assets)

        self._replace_options(task, options_data)
        self._refresh_next_update_time(task)

        return task

    @transaction.atomic
    def update(self, instance, validated_data):
        avito_accounts = validated_data.pop("avito_accounts", None)
        options_data = validated_data.pop("options", None)
        main_image_assets = validated_data.pop("main_image_assets", None)
        additional_image_assets = validated_data.pop("additional_image_assets", None)

        if "category" in validated_data:
            validated_data["category"] = self._resolve_category(validated_data.get("category"))

        if "descriptions" in validated_data:
            validated_data["descriptions"] = self._normalize_descriptions(
                validated_data.get("descriptions", [])
            )

        if "schedule" in validated_data:
            normalized_schedule = self._normalize_schedule_for_task(
                validated_data["schedule"],
                instance.publication_interval_days,
            )
            validated_data["schedule"] = normalized_schedule
            validated_data["publication_interval_days"] = FREQUENCY_TO_INTERVAL_DAYS[
                normalized_schedule["frequency"]
            ]

        if validated_data.get("price_randomization_enabled") is False:
            validated_data["price_min"] = 0
            validated_data["price_max"] = 0
            validated_data["price_step"] = 0

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()

        if main_image_assets is not None:
            instance.main_image_assets.set(main_image_assets)

        if additional_image_assets is not None:
            instance.additional_image_assets.set(additional_image_assets)

        if avito_accounts is not None:
            instance.avito_accounts.set(avito_accounts)

        if options_data is not None:
            self._replace_options(instance, options_data)

        schedule_recalculation_fields = {
            "schedule",
            "schedule_anchor_date",
            "schedule_timezone",
            "is_active",
        }

        if schedule_recalculation_fields.intersection(validated_data.keys()):
            self._refresh_next_update_time(instance)

        return instance

    @staticmethod
    def _to_form_option_value(assignment):
        value = assignment.selected_value or []

        if assignment.option.allow_multiple_options:
            return value if isinstance(value, list) else [str(value)]

        if isinstance(value, list):
            return value[0] if value else ""

        return str(value)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["category"] = instance.category.category if instance.category else ""

        descriptions = instance.descriptions or {}
        if isinstance(descriptions, dict):
            data["descriptions"] = list(descriptions.values())

        try:
            data["schedule"] = normalize_schedule(
                instance.schedule,
                publication_interval_days=instance.publication_interval_days,
            )
        except AdScheduleError:
            data["schedule"] = {
                "frequency": INTERVAL_DAYS_TO_FREQUENCY.get(
                    instance.publication_interval_days,
                    1,
                ),
                "days": [None, None, None, None, None, None, None],
            }

        data["options"] = [
            {
                "option_id": assignment.option_id,
                "value": self._to_form_option_value(assignment),
            }
            for assignment in instance.adgenerationtaskoptionassignment_set.select_related("option")
        ]

        return data


class AvitoAccountSerializer(serializers.ModelSerializer):
    client_secret = serializers.CharField(
        required=False,
        allow_blank=True,
        write_only=True,
        trim_whitespace=True,
    )
    feed_url = serializers.SerializerMethodField()
    has_client_secret = serializers.SerializerMethodField()
    connection_status = serializers.SerializerMethodField()
    connection_error = serializers.SerializerMethodField()
    last_verified_at = serializers.SerializerMethodField()

    class Meta:
        model = AvitoAccount
        fields = [
            "id",
            "name",
            "external_account_id",
            "client_id",
            "client_secret",
            "has_client_secret",
            "is_active",
            "export_status",
            "export_file_path",
            "export_requested_at",
            "export_started_at",
            "last_exported_at",
            "export_error",
            "created_at",
            "updated_at",
            "connection_status",
            "connection_error",
            "last_verified_at",
            "sync_status",
            "sync_requested_at",
            "sync_started_at",
            "last_synced_at",
            "sync_error",
            "last_sync_total_received",
            "last_sync_created_listings",
            "last_sync_updated_listings",
            "feed_url",
        ]
        read_only_fields = [
            "external_account_id",
            "has_client_secret",
            "export_status",
            "export_file_path",
            "export_requested_at",
            "export_started_at",
            "last_exported_at",
            "export_error",
            "created_at",
            "updated_at",
            "sync_status",
            "sync_requested_at",
            "sync_started_at",
            "last_synced_at",
            "sync_error",
            "last_sync_total_received",
            "last_sync_created_listings",
            "last_sync_updated_listings",
            "feed_url",
        ]

    def get_feed_url(self, obj):
        if not obj.feed_token:
            return None

        path = reverse(
            "avito-account-public-csv-feed",
            kwargs={"feed_token": obj.feed_token},
        )

        request = self.context.get("request")

        if request:
            return request.build_absolute_uri(path)

        return path

    def get_has_client_secret(self, obj):
        return bool(obj.client_secret)

    def validate_name(self, value):
        name = value.strip()

        if not name:
            raise serializers.ValidationError("Название проекта обязательно.")

        return name

    def validate_client_id(self, value):
        return value.strip()

    def update(self, instance, validated_data):
        if validated_data.get("client_secret") == "":
            validated_data.pop("client_secret")

        return super().update(instance, validated_data)

    def get_connection_status(self, obj):
        if not obj.client_id or not obj.client_secret:
            return "not_configured"

        try:
            token = obj.oauth_tokens
        except AvitoOAuthToken.DoesNotExist:
            return "not_connected"

        if token.last_error:
            return "error"

        if obj.external_account_id:
            return "connected"

        return "not_connected"

    def get_connection_error(self, obj):
        try:
            return obj.oauth_tokens.last_error
        except AvitoOAuthToken.DoesNotExist:
            return None

    def get_last_verified_at(self, obj):
        try:
            return obj.oauth_tokens.last_verified_at
        except AvitoOAuthToken.DoesNotExist:
            return None


class AvitoListingSerializer(serializers.ModelSerializer):
    option_category_id = serializers.IntegerField(
        read_only=True,
        allow_null=True,
    )
    option_category = serializers.CharField(
        source="option_category.category",
        read_only=True,
        allow_null=True,
    )
    avito_account_name = serializers.CharField(
        source="avito_account.name",
        read_only=True
    )
    publication_row_id = serializers.CharField(
        source="publication.row_id",
        read_only=True,
        allow_null=True
    )
    date_end = serializers.SerializerMethodField()
    date_end_source = serializers.SerializerMethodField()

    class Meta:
        model = AvitoListing
        fields = [
            "id",
            "avito_account",
            "avito_account_name",
            "publication",
            "publication_row_id",

            "source",
            "management_status",
            "desired_status",
            "avito_id",
            "row_id",
            "status",
            "title",
            "description",
            "address",
            "url",

            "sheet_name",
            "category_path",
            "option_category_id",
            "option_category",
            "image_urls",
            "base_data",
            "option_data",
            "unmapped_data",
            "date_end",
            "date_end_source",

            "published_at",
            "last_seen_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "avito_account",
            "avito_account_name",
            "publication",
            "publication_row_id",
            "source",
            "avito_id",
            "created_at",
            "updated_at",
        ]

    def get_date_end(self, instance):
        from avitotask.services.ad_publication_dates import format_avito_date
        from avitotask.services.avito_listing_editing import get_avito_listing_date_end

        return format_avito_date(get_avito_listing_date_end(instance))

    def get_date_end_source(self, instance):
        from avitotask.services.avito_listing_editing import get_avito_listing_date_end_source

        return get_avito_listing_date_end_source(instance)


class AvitoListingUpdateSerializer(serializers.Serializer):
    option_category_id = serializers.PrimaryKeyRelatedField(
        source="option_category",
        queryset=Category.objects.all(),
        required=False,
        allow_null=True,
    )
    title = serializers.CharField(required=False, allow_blank=False, max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    address = serializers.CharField(required=False, allow_blank=True)
    status = serializers.CharField(required=False, allow_blank=True)
    image_urls = serializers.ListField(
        child=serializers.URLField(),
        required=False,
    )
    desired_status = serializers.ChoiceField(
        choices=AvitoListing.DesiredStatus.choices,
        required=False,
    )
    base_data = serializers.DictField(required=False)
    option_data = serializers.DictField(required=False)
    management_status = serializers.ChoiceField(
        choices=AvitoListing.ManagementStatus.choices,
        required=False,
    )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Нет данных для обновления объявления.")

        return attrs


class AvitoListingBulkManagementStatusSerializer(serializers.Serializer):
    listing_ids = serializers.ListField(
        child=serializers.IntegerField(),
        allow_empty=False,
    )
    management_status = serializers.ChoiceField(
        choices=AvitoListing.ManagementStatus.choices,
    )


class AvitoAccountAdsBulkLifecycleItemSerializer(serializers.Serializer):
    entity_type = serializers.ChoiceField(
        choices=["avito_listing", "ad_publication"],
    )
    id = serializers.IntegerField(min_value=1)


class AvitoAccountAdsBulkLifecycleSerializer(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=["publish", "pause", "delete", "extend"],
    )
    items = AvitoAccountAdsBulkLifecycleItemSerializer(
        many=True,
        allow_empty=False,
    )

    def validate_items(self, items):
        seen = set()

        for item in items:
            key = (item["entity_type"], item["id"])

            if key in seen:
                raise serializers.ValidationError(
                    "Список объявлений содержит дубликаты."
                )

            seen.add(key)

        return items


class AdPublicationSerializer(serializers.ModelSerializer):
    avito_account_name = serializers.CharField(
        source="avito_account.name",
        read_only=True
    )
    creative_title = serializers.CharField(
        source="creative.title",
        read_only=True
    )
    avito_listing_id = serializers.IntegerField(
        source="avito_listing.id",
        read_only=True,
        allow_null=True,
    )
    avito_id = serializers.CharField(
        source="avito_listing.avito_id",
        read_only=True,
        allow_null=True,
    )
    avito_listing_url = serializers.URLField(
        source="avito_listing.url",
        read_only=True,
        allow_null=True,
    )

    effective_date_end = serializers.SerializerMethodField()
    date_end_source = serializers.SerializerMethodField()

    class Meta:
        model = AdPublication
        fields = [
            "id",
            "avito_account",
            "avito_account_name",
            "creative",
            "creative_title",
            "task",
            "batch",
            "source",
            "status",
            "row_id",
            "address",
            "overrides",
            "effective_date_end",
            "date_end_source",
            "avito_listing_id",
            "avito_id",
            "avito_listing_url",
            "published_at",
            "last_exported_at",
            "archived_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_effective_date_end(self, instance):
        from avitotask.services.ad_publication_dates import (
            format_avito_date,
            get_publication_effective_date_end,
        )

        return format_avito_date(get_publication_effective_date_end(instance))

    def get_date_end_source(self, instance):
        from avitotask.services.ad_publication_dates import get_publication_date_end_source

        return get_publication_date_end_source(instance)


class AdBatchSerializer(serializers.ModelSerializer):
    task_name = serializers.CharField(
        source="task.name",
        read_only=True,
        allow_null=True
    )
    created_by_email = serializers.EmailField(
        source="created_by.email",
        read_only=True,
        allow_null=True
    )

    class Meta:
        model = AdBatch
        fields = [
            "id",
            "task",
            "task_name",
            "source",
            "status",
            "created_by",
            "created_by_email",
            "total_creatives",
            "total_publications",
            "error_message",
            "created_at",
            "completed_at",
        ]
        read_only_fields = fields


class AdCreativeSerializer(serializers.ModelSerializer):
    option_category_id = serializers.IntegerField(
        read_only=True,
        allow_null=True,
    )
    option_category = serializers.CharField(
        source="option_category.category",
        read_only=True,
        allow_null=True,
    )
    task_name = serializers.CharField(
        source="task.name",
        read_only=True,
        allow_null=True
    )
    batch_source = serializers.CharField(
        source="batch.source",
        read_only=True,
        allow_null=True
    )

    projects = serializers.SerializerMethodField()
    publications_count = serializers.IntegerField(read_only=True)
    effective_date_end = serializers.SerializerMethodField()
    date_end_source = serializers.SerializerMethodField()

    class Meta:
        model = AdCreative
        fields = [
            "id",
            "task",
            "task_name",
            "batch",
            "batch_source",
            "source",
            "option_category_id",
            "option_category",
            "title",
            "description",
            "image_urls",
            "base_data",
            "option_data",
            "identity_hash",
            "publications_count",
            "projects",
            "created_at",
            "updated_at",
            "effective_date_end",
            "date_end_source",
        ]
        read_only_fields = [
            "id",
            "task",
            "task_name",
            "batch",
            "batch_source",
            "source",
            "identity_hash",
            "publications_count",
            "projects",
            "created_at",
            "updated_at",
            "effective_date_end",
            "date_end_source",
        ]

    def get_projects(self, instance):
        projects_by_id = {}

        for publication in instance.publications.all():
            account = publication.avito_account
            projects_by_id[account.id] = {
                "id": account.id,
                "name": account.name,
            }

        return sorted(
            projects_by_id.values(),
            key=lambda project: project["name"].lower(),
        )

    def get_effective_date_end(self, instance):
        from avitotask.services.ad_publication_dates import (
            format_avito_date,
            get_creative_effective_date_end,
        )

        return format_avito_date(get_creative_effective_date_end(instance))

    def get_date_end_source(self, instance):
        from avitotask.services.ad_publication_dates import get_creative_base_date_end

        if get_creative_base_date_end(instance):
            return "creative"

        return "default"


class AdCreativeEditSerializer(serializers.ModelSerializer):
    option_category_id = serializers.IntegerField(
        read_only=True,
        allow_null=True,
    )
    option_category = serializers.CharField(
        source="option_category.category",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = AdCreative
        fields = [
            "id",
            "option_category_id",
            "option_category",
            "title",
            "description",
            "image_urls",
            "base_data",
            "option_data",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "option_category_id",
            "option_category",
            "updated_at",
        ]


class AdCreativeUpdateSerializer(serializers.Serializer):
    option_category_id = serializers.PrimaryKeyRelatedField(
        source="option_category",
        queryset=Category.objects.all(),
        required=False,
        allow_null=True,
    )
    title = serializers.CharField(required=False, allow_blank=False, max_length=255)
    description = serializers.CharField(required=False, allow_blank=False)
    image_urls = serializers.ListField(
        child=serializers.URLField(),
        required=False
    )
    base_data = serializers.DictField(required=False)
    option_data = serializers.DictField(required=False)
    clear_publication_override_fields = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True
    )

    expected_updated_at = serializers.DateTimeField(required=False)

    def validate_base_data(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                "base_data должен быть объектом."
            )

        if "Category" in value:
            autoload_category = str(
                value.get("Category") or ""
            ).strip()

            if not autoload_category:
                raise serializers.ValidationError(
                    "Укажите категорию для файла автозагрузки Avito."
                )

            value = dict(value)
            value["Category"] = autoload_category

        return value

    def validate(self, attrs):
        editable_fields = {
            "option_category",
            "title",
            "description",
            "image_urls",
            "base_data",
            "option_data",
            "clear_publication_override_fields",
        }

        if not any(field in attrs for field in editable_fields):
            raise serializers.ValidationError("Нет данных для обновления креатива")

        return attrs


class AdPublicationUpdateSerializer(serializers.Serializer):
    address = serializers.CharField(required=False, allow_blank=False)
    status = serializers.ChoiceField(
        choices=AdPublication.Status.choices,
        required=False,
    )
    overrides = serializers.DictField(required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Нет данных для обновления публикации.")

        return attrs


class ManualMassPostingSerializer(serializers.Serializer):
    option_category_id = serializers.PrimaryKeyRelatedField(
        source="option_category",
        queryset=Category.objects.all(),
        required=False,
    )
    avito_account_ids = serializers.ListField(
        child=serializers.IntegerField(),
        allow_empty=False,
    )
    addresses = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=False,
    )
    title = serializers.CharField(allow_blank=False, max_length=255)
    description = serializers.CharField(allow_blank=False)
    image_urls = serializers.ListField(
        child=serializers.URLField(),
        required=False,
        allow_empty=True,
    )
    base_data = serializers.DictField(required=False)
    option_data = serializers.DictField(required=False)

    def validate_avito_account_ids(self, value):
        unique_ids = list(dict.fromkeys(value))

        if len(unique_ids) != len(value):
            raise serializers.ValidationError(
                "Список avito_account_ids содержит дубли."
            )

        return unique_ids

    def validate(self, attrs):
        attrs = super().validate(attrs)

        base_data = dict(attrs.get("base_data") or {})
        autoload_category = str(
            base_data.get("Category") or ""
        ).strip()

        if not autoload_category:
            raise serializers.ValidationError({
                "base_data": {
                    "Category": (
                        "Укажите категорию для файла автозагрузки Avito."
                    )
                }
            })

        base_data["Category"] = autoload_category
        attrs["base_data"] = base_data

        if attrs.get("option_category") is not None:
            return attrs

        # Временная совместимость со старым frontend. После обновления
        # frontend option_category_id будет приходить явно.
        legacy_category_name = autoload_category

        option_category = (
            Category.objects
            .filter(category__iexact=legacy_category_name)
            .first()
        )

        if option_category is not None:
            attrs["option_category"] = option_category
            return attrs

        raise serializers.ValidationError({
            "option_category_id": (
                "Выберите категорию для отбора опций."
            )
        })


def serialize_avito_excel_preview(result, rows_limit=20):
    return {
        "total_sheets": result.total_sheets,
        "total_rows": result.total_rows,
        "rows_with_errors": result.rows_with_errors,
        "categories": result.categories,
        "unmapped_columns": result.unmapped_columns,
        "rows": [
            {
                "sheet_name": row.sheet_name,
                "category_path": row.category_path,
                "row_number": row.row_number,
                "row_id": row.row_id,
                "avito_id": row.avito_id,
                "title": row.title,
                "status": row.status,
                "mapped_data": row.mapped_data,
                "unmapped_data": row.unmapped_data,
                "errors": row.errors,
            }
            for row in result.rows[:rows_limit]
        ],
    }
