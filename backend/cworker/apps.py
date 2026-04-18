from django.apps import AppConfig


class CworkerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'cworker'

    def ready(self):
        import cworker.signals  # Импортируем файл signals
