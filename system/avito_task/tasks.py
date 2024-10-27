from celery import shared_task
from .models import Task

@shared_task
def print_message(task_id):
    try:
        task = Task.objects.get(id=task_id)
        if task.is_active:
            print(f"Сообщение от задачи '{task.name}': {task.message}")
    except Task.DoesNotExist:
        print("Задача не найдена")