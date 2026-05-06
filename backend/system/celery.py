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
app.set_default()

# Автоматически обнаруживаем задачи в приложениях
app.autodiscover_tasks()

app.conf.beat_schedule = {
    'export_dirty_avito_accounts_csv_every_minute': {
        'task': 'avitotask.tasks.export_dirty_avito_accounts_csv_task',
        'schedule': crontab(minute='*'),
        'args': (20,),
    },
    'run_due_ad_generation_tasks_every_minute': {
        'task': 'avitotask.tasks.run_due_ad_generation_tasks',
        'schedule': crontab(minute='*'),
        'args': (50,),
    },
    'archive_stale_publications_daily': {
        'task': 'avitotask.tasks.archive_stale_publications_task',
        'schedule': crontab(hour=3, minute=30),
        'args': (60, 1000),
    },
}
