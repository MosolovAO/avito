from celery.schedules import crontab

from system.settings import CELERY_BEAT_SCHEDULE


def schedule_tasks():
    from .models import TaskSchedule
    schedules = TaskSchedule.objects.all()
    for schedule in schedules:
        task = schedule.task
        if task.is_active:
            day_of_week = schedule.day_of_week.lower()
            hour = schedule.hour
            task_name = f'execute_task_{task.id}_{day_of_week}_{hour}'
            CELERY_BEAT_SCHEDULE[task_name] = {
                'task': 'avitotask.tasks.execute_task',
                'schedule': crontab(day_of_week=day_of_week, hour=hour),
                'args': (task.id,),
            }
