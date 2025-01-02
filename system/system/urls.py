from django.contrib import admin
from django.urls import path

from avitotask.utils import upload_images
from cworker import views
from cworker.consumers import NotificationConsumer
from django.conf.urls.static import static
from django.conf import settings
from avitotask.views import product_list, finalize_product_form, product_add, get_product_options, product_edit, \
    get_product_data, product_random

urlpatterns = [
    path('admin/', admin.site.urls),
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
    path('products/random/<int:product_id>/', product_random, name='product_random'),

]

websocket_urlpatterns = [
    path("ws/notifications/", NotificationConsumer.as_asgi())
]

if settings.DEBUG:
    # Обслуживание статических файлов
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

    # Обслуживание медиафайлов
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)