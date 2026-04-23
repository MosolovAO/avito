from uuid import uuid4

from django.db import transaction
from rest_framework import serializers
from .models import Project, Product, Product1, ProductOptions, ProductOptionAssignment, Category

DAY_KEYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']


class ProjectSerializer(serializers.ModelSerializer):
    """Serializer for the Project model."""

    class Meta:
        model = Project
        fields = ['id', 'project_name']


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


class ProductOptionAssignmentSerializer(serializers.Serializer):
    """Serializer for the ProductOptionAssignment model."""
    option = ProductOptionsSerializer(read_only=True)
    value = serializers.ListField(source='selected_values', child=serializers.CharField(), read_only=True)

    class Meta:
        model = ProductOptionAssignment
        fields = ['id', 'option', 'option_id', 'value']


class ProductSerializer(serializers.ModelSerializer):
    """"Serializer для создания, редактирования и чтения Product через DRF API."""
    name = serializers.CharField(required=False, allow_blank=True)
    url = serializers.URLField(required=False, allow_blank=True)

    projects = serializers.PrimaryKeyRelatedField(
        queryset=Project.objects.all(),
        many=True,
        required=False,
    )
    category = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    descriptions = serializers.JSONField(required=False)
    options = ProductOptionInputSerializer(many=True, write_only=True, required=False)

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'url', 'price', 'price_randomization_enabled', 'activate',
            'price_min', 'price_max', 'price_step',
            'possible_combinations', 'schedule', 'next_update_time',
            'titles', 'main_images', 'additional_images',
            'descriptions', 'addresses', 'selected_options',
            'category', 'listingfee', 'email', 'contactphone',
            'managername', 'avitostatus', 'companyname',
            'contactmethod', 'adtype', 'availability',
            'projects', 'options',
        ]
        read_only_fields = ['possible_combinations', 'next_update_time', 'selected_options']

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

    def _resolve_category(self, value):
        if not value:
            return None
        category_name = str(value).strip()
        category, _ = Category.objects.get_or_create(category=category_name)
        return category

    def _replace_options(self, product, options_data):
        ProductOptionAssignment.objects.filter(product=product).delete()

        assignments = [
            ProductOptionAssignment(
                product=product,
                option=item['option'],
                selected_value=item['value']
            )
            for item in options_data
        ]
        ProductOptionAssignment.objects.bulk_create(assignments)

        product.selected_options = {
            item['option'].option_title_en: item['value']
            for item in options_data
        }

        product.save(update_fields=['selected_options'])

    def _refresh_next_update_time(self, product):
        if product.schedule:
            product.update_next_update_time()
        else:
            product.next_update_time = None
            product.save(update_fields=['next_update_time'])

    @transaction.atomic
    def create(self, validated_data):
        """Создает Product и связанные данные."""
        projects = validated_data.pop('projects', [])
        options_data = validated_data.pop('options', [])
        category_value = validated_data.pop('category', None)

        if not validated_data.get('price_randomization_enabled', False):
            validated_data['price_min'] = 0
            validated_data['price_max'] = 0
            validated_data['price_step'] = 0

        validated_data['name'] = validated_data.get('name') or f'Задача {uuid4().hex[:8]}'
        validated_data['url'] = validated_data.get('url') or ''
        validated_data['category'] = self._resolve_category(category_value)
        validated_data['descriptions'] = self._normalize_descriptions(validated_data.get('descriptions', []))
        validated_data['schedule'] = self._normalize_schedule(validated_data.get('schedule', {}))

        product = Product.objects.create(**validated_data)
        product.projects.set(projects)

        self._replace_options(product, options_data)
        self._refresh_next_update_time(product)

        return product

    @transaction.atomic
    def update(self, instance, validated_data):
        """Обновляет Product и связанные many-to-many/through данные."""
        projects = validated_data.pop('projects', None)
        options_data = validated_data.pop('options', None)

        if 'category' in validated_data:
            validated_data['category'] = self._resolve_category(validated_data.get('category'))

        if 'descriptions' in validated_data:
            validated_data['descriptions'] = self._normalize_descriptions(validated_data.get('descriptions', []))
        if 'schedule' in validated_data:
            validated_data['schedule'] = self._normalize_schedule(validated_data.get('schedule', {}))

        if validated_data.get('price_randomization_enabled') is False:
            validated_data['price_min'] = 0
            validated_data['price_max'] = 0
            validated_data['price_step'] = 0

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()

        if projects is not None:
            instance.projects.set(projects)

        if options_data is not None:
            self._replace_options(instance, options_data)
        if 'schedule' in validated_data:
            self._refresh_next_update_time(instance)

        return instance

    @staticmethod
    def _to_form_option_value(assignment):
        value = assignment.selected_value or []

        if assignment.option.allow_multiple_options:
            return value if isinstance(value, list) else [str(value)]

        if isinstance(value, list):
            return value[0] if value else ''

        return str(value)

    def to_representation(self, instance):
        """Преобразует Product из backend-формата в формат, удобный React-форме."""
        data = super().to_representation(instance)
        data['projects'] = ProjectSerializer(instance.projects.all(), many=True).data
        data['category'] = instance.category.category if instance.category else ''

        descriptions = instance.descriptions or {}
        if isinstance(descriptions, dict):
            data['descriptions'] = list(descriptions.values())
            data['descriptions'] = list(descriptions.values())

        schedule = instance.schedule or {}
        days = [None] * 7
        for index, day_key in enumerate(DAY_KEYS):
            days[index] = schedule.get(day_key)

        data['schedule'] = {
            'frequency': 1,
            'days': days,
        }
        data['options'] = [
            {
                'option_id': assignment.option_id,
                'value': self._to_form_option_value(assignment),
            }

            for assignment in instance.productoptionassignment_set.select_related('option')
        ]

        return data


class Product1Serializer(serializers.ModelSerializer):
    """Serializer для Product1 (созданные объявления)"""

    class Meta:
        model = Product1
        fields = [
            'id', 'title', 'urls', 'description',
            'created_date', 'task_id', 'selected_option', 'project_name'
        ]
        read_only_fields = ['created_date']
