from __future__ import absolute_import, unicode_literals
import os
from celery import Celery
from celery.schedules import crontab, schedule

# Установим модуль настроек Django для Celery
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'system.settings')

# Создаем экземпляр приложения Celery
app = Celery('system')

# Загружаем конфигурацию из settings.py
app.config_from_object('django.conf:settings', namespace='CELERY')

# Автоматически обнаруживаем задачи в приложениях
app.autodiscover_tasks()

app.conf.beat_schedule = {
    'schedule_price_updates_every_second': {
        'task': 'avitotask.tasks.schedule_price_updates',
        'schedule': schedule(10.0),  # Запуск каждую секунду
    },
}
