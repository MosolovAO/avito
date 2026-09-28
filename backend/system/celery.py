from __future__ import absolute_import, unicode_literals
import os
from celery import Celery
from celery.schedules import crontab, schedule

# Установим модуль настроек Django для Celery
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'system.settings_local')

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
    'sync_last_completed_avito_autoload_reports_hourly': {
        'task': 'avitotask.tasks.sync_last_completed_avito_autoload_reports_task',
        'schedule': crontab(minute=20),
        'args': (20,),
    },
    "enqueue_daily_avito_stats_syncs": {
        "task": "analytics.tasks.enqueue_daily_avito_stats_syncs_task",
        "schedule": crontab(hour=4, minute=10),
    },
    "recover_automation_runs_every_ten_minutes": {
        "task": "automations.tasks.recover_automation_runs_task",
        "schedule": crontab(
            minute="5,15,25,35,45,55",
        ),
    },
    "enqueue_calls_sync_hourly": {
        "task": "calls.tasks.enqueue_calls_sync_task",
        "schedule": crontab(minute=35),
    },
}
