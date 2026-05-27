import re

import string

from .models import ProductOptions
from django.http import JsonResponse

import random


def generate_random_id(length=16):
    """Генерирует случайный ID из букв и цифр."""
    characters = string.ascii_letters + string.digits
    return ''.join(random.choices(characters, k=length)).upper()


def process_dynamic_text(template_text):
    # Функция для замены конструкции [ A | B | C ] случайным значением
    def replace_choices(match):
        choices = match.group(1).split('|')  # Получаем список вариантов
        return random.choice(choices).strip()  # Возвращаем случайный элемент, убирая пробелы

    # Ищем конструкции [ ... ] и заменяем их
    processed_text = re.sub(r'\[([^\]]+)\]', replace_choices, template_text)
    return processed_text


def get_product_options(request):
    """
    Возвращает список доступных опций и их значений.
    """
    options = ProductOptions.objects.all().values('id', 'option_title', 'option_value')
    return JsonResponse(list(options), safe=False)
