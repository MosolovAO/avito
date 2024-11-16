from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Record
from .tasks import print_random_title


@receiver(post_save, sender=Record)
def update_task_interval(sender, instance, **kwargs):
    print_random_title.apply_async((instance.id,), countdown=instance.interval)
