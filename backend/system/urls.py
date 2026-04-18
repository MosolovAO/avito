from django.contrib import admin
from rest_framework.routers import DefaultRouter
from django.urls import path, include

from avitotask.utils import upload_images
from cworker import views
from cworker.consumers import NotificationConsumer
from django.conf.urls.static import static
from django.conf import settings
from avitotask.views import product_list, finalize_product_form, product_add, get_product_options, product_edit, \
    get_product_data, product_random, toggle_product_active, adv_list, adv_edit, remove_selected_option, \
    save_adv_options

from avitotask.api_views import (
    ProductViewSet,
    Product1ViewSet,
    ProjectViewSet,
    ProductOptionsViewSet,
    product_random,
    toggle_product_active,
    get_product_options,
)

# DRF Router

router = DefaultRouter()
router.register(r'api/products', ProductViewSet, basename='product-api')
router.register(r'api/product1', Product1ViewSet, basename='product1-api')
router.register(r'api/projects', ProjectViewSet, basename='project-api')
router.register(r'api/options', ProductOptionsViewSet, basename='options-api')

urlpatterns = [
    path('admin/', admin.site.urls),

    # Web views (старые)
    path('', views.home, name='home'),
    path('add/', views.add_post, name='add_post'),
    path('edit/<int:pk>/', views.edit_post, name='edit_post'),
    path('delete/<int:pk>/', views.delete_post, name='delete_post'),
    path('start/<int:pk>/', views.start_post, name='start_post'),
    path('stop/<int:pk>/', views.stop_post, name='stop_post'),
    path('products/', product_list, name='product_list'),
    path('products/add/', product_add, name='product_add'),
    path('products/finish/', finalize_product_form, name='finalize_product_form'),
    path('products/<int:product_id>/upload-images/', upload_images, name='upload_images'),
    path('options/', get_product_options, name='get_product_options'),
    path('products/edit/<int:product_id>/', product_edit, name='product_edit'),
    path('products/edit/adv-list/<int:product_id>', adv_list, name='adv_list'),
    path('products/edit/adv-edit/<int:adv_id>', adv_edit, name='adv_edit'),
    path('products/random/<int:product_id>/', product_random, name='product_random'),
    path('products/toggle-active/<int:product_id>/', toggle_product_active, name='toggle_product_active'),

    path('products/edit/adv-edit/remove-option/<int:adv_id>/', remove_selected_option, name='remove_selected_option'),

    path('products/edit/adv-edit/save/<int:adv_id>/', save_adv_options, name='save_adv_options'),

    # API endpoints (DRF)
    path('api/product-random/<int:product_id>/', product_random, name='product-random-api'),
    path('api/toggle-product-active/<int:product_id>/', toggle_product_active, name='toggle-product-active-api'),
    path('api/get-product-options/', get_product_options, name='get-product-options-api'),

    # DRF router URLs
    path('', include(router.urls)),

]

websocket_urlpatterns = [
    path("ws/notifications/", NotificationConsumer.as_asgi())
]

if settings.DEBUG:
    # Обслуживание статических файлов
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Обслуживание медиафайлов
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
