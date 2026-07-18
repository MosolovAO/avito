from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from cworker.consumers import NotificationConsumer

from avitotask.api_views import (
    ProductViewSet,
    ProductOptionsViewSet,
    AdPublicationViewSet,
    AvitoAccountViewSet,
    AvitoListingViewSet,
    get_product_categories,
    upload_product_image,
    AdBatchViewSet,
    AdCreativeViewSet,
    ManualMassPostingView,
    toggle_product_active,
    product_random
)

router = DefaultRouter()
router.register(r'products', ProductViewSet, basename='product-api')
router.register(r'options', ProductOptionsViewSet, basename='options-api')
router.register(r'avito-accounts', AvitoAccountViewSet, basename='avito-account-api')
router.register(r'avito-listings', AvitoListingViewSet, basename='avito-listing-api')
router.register(r'ad-publications', AdPublicationViewSet, basename='ad-publication-api')
router.register(r'ad-batches', AdBatchViewSet, basename='ad-batch-api')
router.register(r'ad-creatives', AdCreativeViewSet, basename='ad-creative-api')

urlpatterns = [
    path('admin/', admin.site.urls),

    path('api/categories/', get_product_categories, name='categories-api'),
    path(
        'api/manual-mass-posting/',
        ManualMassPostingView.as_view(),
        name='manual-mass-posting-api',
    ),
    path('api/product-images/upload/', upload_product_image, name='product-image-upload-api'),
    path('api/toggle-product-active/<int:product_id>/', toggle_product_active, name='toggle-product-active-api', ),

    path(
        'api/product-random/<int:product_id>/',
        product_random,
        name='product-random-api',
    ),

    path('api/', include(router.urls)),

    path('api/auth/', include('accounts.urls')),
    path('api/workspaces/', include('accounts.workspace_urls')),
    path('api/workspace-invites/', include('accounts.invitation_urls')),

    # UR: для работы с API Avito
    path('api/avito/', include('avitotask.avito_urls')),
    path('api/analytics/', include('analytics.urls')),
]

websocket_urlpatterns = [
    path("ws/notifications/", NotificationConsumer.as_asgi()),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
