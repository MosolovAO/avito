from rest_framework import serializers
from .models import Project, Product, Product1, ProductOptions, ProductOptionAssignment


class ProjectSerializer(serializers.ModelSerializer):
    """Serializer for the Project model."""

    class Meta:
        model = Project
        fields = ['id', 'project_name']


class ProductOptionsSerializer(serializers.ModelSerializer):
    """Serializer for the ProductOptions model."""""

    class Meta:
        model = ProductOptions
        fields = ['id', 'option_title', 'option_value']


class ProductOptionAssignmentSerializer(serializers.ModelSerializer):
    """Serializer for the ProductOptionAssignment model."""
    option = ProductOptionsSerializer(read_only=True)
    option_id = serializers.PrimaryKeyRelatedField(
        queryset=ProductOptions.objects.all(),
        source='option',
        write_only=True,
    )

    class Meta:
        model = ProductOptionAssignment
        fields = ['id', 'option', 'option_id', 'selected_value']


class ProductSerializer(serializers.ModelSerializer):
    """"Serializer for the Product model."""
    projects = ProjectSerializer(many=True, read_only=True)
    projects_ids = serializers.PrimaryKeyRelatedField(
        queryset=Project.objects.all(),
        source='projects',
        many=True,
        write_only=True,
    )
    options = ProductOptionAssignmentSerializer(many=True, read_only=True, source='productoptionassignment_set')

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'url', 'price', 'activate',
            'price_min', 'price_max', 'price_step',
            'possible_combinations', 'schedule', 'next_update_time',
            'titles', 'main_images', 'additional_images',
            'descriptions', 'addresses', 'selected_options',
            'category', 'listingfee', 'email', 'contactphone',
            'managername', 'avitostatus', 'companyname',
            'contactmethod', 'adtype', 'availability',
            'projects', 'project_ids', 'options',
        ]
        read_only_fields = ['possible_combinations', 'next_update_time']


class Product1Serializer(serializers.ModelSerializer):
    """Serializer для Product1 (созданные объявления)"""

    class Meta:
        model = Product1
        fields = [
            'id', 'title', 'urls', 'description',
            'created_date', 'task_id', 'selected_option', 'project_name'
        ]
        read_only_fields = ['created_date']
