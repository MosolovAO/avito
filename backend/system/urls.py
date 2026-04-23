from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from cworker.consumers import NotificationConsumer

from avitotask.api_views import (
    ProductViewSet,
    Product1ViewSet,
    ProjectViewSet,
    ProductOptionsViewSet,
    get_product_categories,
    product_random as product_random_api,
    toggle_product_active as toggle_product_active_api,
)

router = DefaultRouter()
router.register(r'products', ProductViewSet, basename='product-api')
router.register(r'product1', Product1ViewSet, basename='product1-api')
router.register(r'projects', ProjectViewSet, basename='project-api')
router.register(r'options', ProductOptionsViewSet, basename='options-api')

urlpatterns = [
    path('admin/', admin.site.urls),

    path('api/product-random/<int:product_id>/', product_random_api, name='product-random-api'),
    path('api/toggle-product-active/<int:product_id>/', toggle_product_active_api, name='toggle-product-active-api'),
    path('api/categories/', get_product_categories, name='categories-api'),
    path('api/', include(router.urls)),
]

websocket_urlpatterns = [
    path("ws/notifications/", NotificationConsumer.as_asgi()),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
