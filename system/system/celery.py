from __future__ import absolute_import, unicode_literals
import os
from celery import Celery

# Установим модуль настроек Django для Celery
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'system.settings')

# Создаем экземпляр приложения Celery
app = Celery('system')

# Загружаем конфигурацию из settings.py
app.config_from_object('django.conf:settings', namespace='CELERY')

@app.task
def add_number():
    return

# Автоматически обнаруживаем задачи в приложениях
app.autodiscover_tasks()
