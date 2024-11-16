from celery import Celery
from celery.schedules import crontab
from .models import Record
from .tasks import print_random_title

app = Celery()


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    records = Record.objects.all()
    for record in records:
        sender.add_periodic_task(record.interval, print_random_title.s(record.id), name=f'Task for {record.id}')
