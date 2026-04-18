from rest_framework import viewsets, status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.shortcuts import get_object_or_404
from django.db.models import Q
from datetime import datetime, timedelta
import random
import string
import json

from .models import Product, Product1, ProductOptions, Project, ProductOptionAssignment
from .serializers import (
    ProductSerializer,
    Product1Serializer,
    ProjectSerializer,
    ProductOptionsSerializer,
)


class ProductViewSet(viewsets.ModelViewSet):
    """ API endpoint для управления задачами"""
    queryset = Product.objects.prefetch_related('projects', 'productoptionassignment_set').all()
    serializer_class = ProductSerializer
    permission_classes = [AllowAny]


class Product1ViewSet(viewsets.ModelViewSet):
    """ API endpoint для управления объектами Product1"""
    queryset = Product1.objects.all()
    serializer_class = Product1Serializer
    permission_classes = [AllowAny]


class ProjectViewSet(viewsets.ModelViewSet):
    """ API endpoint для управления проектами"""
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer
    permission_classes = [AllowAny]


class ProductOptionsViewSet(viewsets.ModelViewSet):
    """ API endpoint для управления опциями продуктов"""
    queryset = ProductOptions.objects.all()
    serializer_class = ProductOptionsSerializer
    permission_classes = [AllowAny]


@api_view(['POST'])
def product_random(request, product_id):
    """
    Генерация случайного продукта (объявления)
    Аналог product_random из views.py
    """

    start_time = datetime.now()
    product = get_object_or_404(Product, pk=product_id)

    # Получаем записи за последние 31 день
    cutoff_date = datetime.now().date() - timedelta(days=29)
    existing_records = Product1.objects.filter(
        Q(task_id=product_id) & Q(created_at__gte=cutoff_date)
    )

    # Если лимит вариантов исчерпан
    if existing_records.count() >= len(product.titles):
        return Response(
            {'error': 'Все возможные комбинации уже созданы!'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Генерация случайных данных

    product_title = product.random_title()
    product_description = product.random_description()
    product_images = [
        product.random_main_image(),
        *product.random_additional_image(),
    ]
    product_title_list = [title.title for title in existing_records]

    if product_title in product_title_list:
        return Response(
            {'error': 'Такой заголовок уже существует'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Проверка совпадения

    matches = 0

    for product1 in existing_records:
        matches = 0
        unique_urls_in_first = len(set(product1.urls).intersection(set(product_images)))
        if unique_urls_in_first >= 10:
            matches += 1
        if product1.description == product_description:
            matches += 1
        if matches >= 2:
            break

    if matches < 2:
        # Создаём новый продукт
        projects = product.projects.all()

        new_product = Product1.objects.create(
            title=product_title,
            urls=product_images,
            description=product_description,
            task_id=product_id,
            selected_option={},
            project_name=[project.project_name for project in projects]
        )

        product.update_next_update_time()

        serializer = Product1Serializer(new_product)
        return Response({
            'execution_time': (datetime.now() - start_time).total_seconds(),
            'data': serializer.data,
        })
    return Response(
        {'error': 'Не удалось создать уникальную комбинацию.'},
        status=status.HTTP_400_BAD_REQUEST

    )


@api_view(['POST'])
def toggle_product_active(request, product_id):
    """
    Активация/деактивация продукта
    """
    product = get_object_or_404(Product, pk=product_id)
    action = request.data.get('action')

    if action == 'activate':
        product.activate = True
    elif action == 'deactivate':
        product.activate = False
    else:
        return Response(
            {'error': 'Неверное действие'},
            status=status.HTTP_400_BAD_REQUEST
        )
    product.save()
    return Response({'status': 'success', 'active': product.activate})


@api_view(['GET'])
def get_product_options(request):
    """
    Получение списка доступных опций
    """
    options = ProductOptions.objects.all().values('id', 'option_title', 'option_value')
    return Response(list(options))
