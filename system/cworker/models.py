import random
import json
from django.db import models
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django_celery_beat.models import PeriodicTask, IntervalSchedule


class Notification(models.Model):
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.message


class Record(models.Model):
    title = models.CharField(max_length=200, help_text="Заголовок записи")
    interval = models.PositiveIntegerField(
        help_text="Интервал в секундах между выполнениями задачи"
    )

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        schedule, created = IntervalSchedule.objects.get_or_create(
            every=self.interval, period=IntervalSchedule.SECONDS
        )
        task_name = f"print_random_title_{self.id}"
        task, created = PeriodicTask.objects.get_or_create(
            interval=schedule, name=task_name,
            task='cworker.tasks.print_random_title',
            args=json.dumps([self.id])
        )
        if not created:
            task.interval = schedule
            task.save()

    def delete(self, *args, **kwargs):
        PeriodicTask.objects.filter(name=f"print_random_title_{self.id}").delete()
        super().delete(*args, **kwargs)

    def __str__(self):
        return self.title


class Post(models.Model):
    title = models.CharField(max_length=255)
    headings = models.TextField(help_text="Введите список заголовков, разделённых запятыми")
    is_running = models.BooleanField(default=False)
    interval = models.IntegerField(default=10, help_text="Интервал выполнения в секундах")

    def get_headings(self):
        return self.headings.split(',')

    def display_random_heading(self):
        if self.is_running and self.headings:
            headings_list = self.get_headings()
            print(random.choice(headings_list))

    def __str__(self):
        return self.title
