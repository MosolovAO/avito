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
    upload_product_image,
)

router = DefaultRouter()
router.register(r'products', ProductViewSet, basename='product-api')
router.register(r'product1', Product1ViewSet, basename='product1-api')
router.register(r'projects', ProjectViewSet, basename='project-api')
router.register(r'options', ProductOptionsViewSet, basename='options-api')

urlpatterns = [
    path('admin/', admin.site.urls),

    path('api/categories/', get_product_categories, name='categories-api'),
    path('api/product-images/upload/', upload_product_image, name='product-image-upload-api'),
    path('api/', include(router.urls)),

    path('api/auth/', include('accounts.urls')),
    path('api/workspaces/', include('accounts.workspace_urls')),
    path('api/workspace-invites/', include('accounts.invitation_urls')),

    # UR: для работы с API Avito
    path('api/avito/', include('avitotask.avito_urls')),
]

websocket_urlpatterns = [
    path("ws/notifications/", NotificationConsumer.as_asgi()),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
