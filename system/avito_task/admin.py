from django.contrib import admin
from .models import Task
from django_celery_beat.models import CrontabSchedule, PeriodicTask
from .tasks import print_message

@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    actions = ['create_periodic_task']

    def create_periodic_task(self, request, queryset):
        for task in queryset:
            if task.is_active:
                schedule, _ = CrontabSchedule.objects.get_or_create(
                    minute=task.run_at.minute,
                    hour=task.run_at.hour,
                    day_of_week=task.day_of_week,
                    day_of_month='*',
                    month_of_year='*'
                )
                PeriodicTask.objects.create(
                    crontab=schedule,
                    name=f"Task_{task.id}",
                    task='myapp.tasks.print_message',
                    args=[task.id]
                )
        self.message_user(request, "Периодическая задача создана")
