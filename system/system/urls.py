"""
URL configuration for system project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from cworker import views
from cworker.consumers import NotificationConsumer
from django.conf.urls.static import static
from django.conf import settings
from avitotask.views import product_create_or_update, product_list

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.home, name='home'),
    path('add/', views.add_post, name='add_post'),
    path('edit/<int:pk>/', views.edit_post, name='edit_post'),
    path('delete/<int:pk>/', views.delete_post, name='delete_post'),
    path('start/<int:pk>/', views.start_post, name='start_post'),
    path('stop/<int:pk>/', views.stop_post, name='stop_post'),
    path('products/', product_list, name='product_list'),
    path('product/add/', product_create_or_update, name='product_add'),
    path('product/<int:pk>/edit/', product_create_or_update, name='product_edit'),

]

websocket_urlpatterns = [
    path("ws/notifications/", NotificationConsumer.as_asgi())
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
