import random
from celery import Celery, shared_task
from .models import Post
from .models import Record
app = Celery()


@shared_task
def display_random_heading_task(post_id):
    try:
        post = Post.objects.get(id=post_id)
        if post.is_running:
            headings_list = post.get_headings()
            print(random.choice(headings_list))
    except Post.DoesNotExist:
        print(f"Post with ID {post_id} does not exist.")


@shared_task
def print_random_title(record_id):
    try:
        record = Record.objects.get(id=record_id)
        titles = record.title.split()  # Предполагая, что заголовок можно разбить на слова
        print(random.choice(titles))
    except Record.DoesNotExist:
        print("Record not found")


