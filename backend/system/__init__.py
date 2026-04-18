from __future__ import absolute_import, unicode_literals

# Подключаем celery, чтобы он инициализировался при старте Django
from .celery import app as celery_app

__all__ = ('celery_app',)