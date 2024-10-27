from django.db import models
from django_celery_beat.models import PeriodicTask, IntervalSchedule, CrontabSchedule
from django.utils import timezone

class Task(models.Model):
    name = models.CharField(max_length=200)
    message = models.TextField()
    run_at = models.TimeField()
    day_of_week = models.CharField(max_length=10, default='monday')  # День недели, например 'monday'
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name
