import json
import os
import re

from django.template import Engine, Context, Template
from datetime import datetime, timedelta
from collections import defaultdict
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
import string

from system import settings
from .models import Product1, Product, ProductOptions, ProductOptionAssignment, Project
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import random
import pandas as pd


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


def product_random(request, product_id):
    start_time = datetime.now()
    product = get_object_or_404(Product, id=product_id)
    product_id = product.id
    product_address = product.addresses  # Возможно, это список, как в вашем примере
    products1 = Product1.objects.filter(task_id=product_id)

    projects = product.projects.all()  # Предположим, это QuerySet связанных проектов

    # Получаем записи за последние 31 день с указанным task_id
    cutoff_date = datetime.now().date() - timedelta(days=29)
    existing_records = Product1.objects.filter(
        Q(task_id=product_id) & Q(created_date__gte=cutoff_date)
    )

    print(existing_records.count())

    date_end = (datetime.now() + timedelta(days=29)).strftime('%Y-%m-%d')
    date_create = datetime.now().strftime('%Y-%m-%d')
    # Если лимит вариантов исчерпан
    if existing_records.count() >= len(product.titles):
        return JsonResponse(
            {'error': 'Все возможные комбинации уже созданы.'},
            status=400,
            json_dumps_params={'ensure_ascii': False}
        )

    # Основной цикл генерации
    while True:

        # Генерация случайных данных
        product_title = product.random_title()
        product_descriptions = product.random_description()
        product_project = product.projects
        product_images = [
            product.random_main_image(),
            *product.random_additional_image(),
        ]

        product_title_list = [title.title for title in existing_records]

        if product_title in product_title_list:
            continue

        matches = 0

        # Проверка на совпадения
        for product1 in existing_records:

            matches = 0

            # 1. Проверка пересечения URL (проверяем количество совпадений)
            unique_urls_in_first = len(set(product1.urls).intersection(set(product_images)))
            if unique_urls_in_first >= 10:
                matches += 1
                if matches == 2:
                    break

            # 2. Совпадение по описанию
            if product1.description == product_descriptions:
                matches += 1
                if matches >= 2:
                    break

        # Если совпадений меньше 2 — создаём новый продукт
        if matches < 2:

            template = Template(process_dynamic_text(product_descriptions))

            context = Context({
                "TITLE": product_title,
                "SKU": generate_random_id()
            })

            rendered_description = template.render(context)

            print(rendered_description)

            assignments = product.productoptionassignment_set.select_related('option').all()
            # Собираем словарь вида {"Название опции": "Выбранное значение"}
            selected_options_data = {
                assignment.option.option_title: assignment.selected_value
                for assignment in assignments
            }

            projects = product.projects.all()

            new_product = Product1.objects.create(
                title=product_title,
                urls=product_images,
                description=rendered_description,
                task_id=product_id,
                selected_option=selected_options_data,
                project_name=[project.project_name for project in projects]

            )

            for project in projects:
                print(project.project_name)

            # Подготовка данных для CSV
            data_to_write = defaultdict(list)  # ключ — проект, значение — список словарей (строк)

            # Собираем строки для каждого адреса
            for addr in product_address:
                # Базовая часть строки
                row_data = {
                    "Id": generate_random_id(),
                    "TaskId": product_id,
                    "CreatDate": date_create,
                    "DateEnd": date_end,
                    "Title": product_title,
                    "ImageUrls": " | ".join(product_images),
                    "Description": rendered_description,
                    "Category": product.category,
                    "Price": product.price,
                    "ListingFee": product.listingfee,
                    "EMail": product.email,
                    "ContactPhone": int(product.contactphone),
                    "ManagerName": product.managername,
                    "AvitoStatus": product.avitostatus,
                    "CompanyName": product.companyname,
                    "ContactMethod": product.contactmethod,
                    "AdType": product.adtype,
                    "Availability": product.availability,
                    "Address": addr,
                }

                # Подтягиваем динамические опции
                assignments = product.productoptionassignment_set.select_related('option').all()
                product_options = {
                    assignment.option.option_title: assignment.selected_value
                    for assignment in assignments
                }
                row_data.update(product_options)

                # Сохраняем данные для каждого проекта
                for project in projects:
                    data_to_write[project].append(row_data)

            # Блок сохранения в CSV
            # ------------------------------------------
            for project, rows in data_to_write.items():
                file_name = f"{project}_avito_autoload.csv"
                file_path = os.path.join(settings.STATIC_ROOT, file_name)

                # Превращаем наши данные в DataFrame
                new_df = pd.DataFrame(rows)

                if os.path.exists(file_path):
                    # Если CSV уже существует — читаем его
                    existing_df = pd.read_csv(file_path, sep=';', dtype=str)

                    # Собираем все колонки — старые и новые
                    all_columns = list(set(existing_df.columns.tolist() + new_df.columns.tolist()))

                    # Расширяем существующий и новый датафреймы до полного набора колонок
                    existing_df = existing_df.reindex(columns=all_columns)
                    new_df = new_df.reindex(columns=all_columns)

                    # Объединяем
                    final_df = pd.concat([existing_df, new_df], ignore_index=True)
                else:
                    # Если файла нет, просто создаём из новых данных
                    final_df = new_df

                # Сохраняем результат в файл
                final_df.to_csv(file_path, sep=';', index=False, encoding='utf-8')

            # Обновляем дату следующего обновления
            product.update_next_update_time()

            # Отдаём результат
            return JsonResponse({
                'execution_time': (datetime.now() - start_time).total_seconds(),
                'matches': matches,
                'random_title': product_title,
                'product_images': product_images,
                'product_descriptions': rendered_description,
                'product_category': product.category,
            }, json_dumps_params={'ensure_ascii': False})


def adv_list(request, product_id):
    adv = Product1.objects.filter(task_id=product_id)

    context = {
        'adv': adv,
    }

    return render(request, 'adv_list.html', context=context)


def adv_edit(request, adv_id):
    adv = Product1.objects.get(id=adv_id)

    context = {
        'adv': adv,
    }

    return render(request, 'adv_edit.html', context=context)


def product_add(request):
    """
    Рендерит многоэтапную форму для добавления или редактирования продукта.
    """
    # Передаём продукт и флаг редактирования в шаблон

    projects = Project.objects.all()

    hours = [f"{hour:02}:00" for hour in range(24)]
    days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

    context = {
        'projects': projects,
        'hours': hours,
        'days': days
    }

    return render(request, 'add_product.html', context=context)


def product_edit(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    product.addresses = "\n".join([address.strip() for address in product.addresses])
    assignments = product.productoptionassignment_set.select_related('option').all()
    options = [
        {
            'option_id': assignment.option.id,
            'option_title': assignment.option.option_title,
            'option_values': assignment.option.option_value,
            'selected_value': assignment.selected_value,
        }
        for assignment in assignments
    ]
    return render(request, 'edit_product.html', {
        'product_id': product.id,
        'product': product,
        'options': options,
        'days': ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"],  # Дни недели
    })


def product_list(request):
    """
    Рендерит список всех задач.
    """
    products = Product.objects.prefetch_related('projects').all()

    return render(request, 'product_list.html', {'products': products})


@csrf_exempt
def toggle_product_active(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'activate':
            product.activate = True
        elif action == 'deactivate':
            product.activate = False
        product.save()
        return JsonResponse({'status': 'success', 'active': product.activate})
    return JsonResponse({'status': 'error'}, status=400)


def get_product_options(request):
    """
    Возвращает список доступных опций и их значений.
    """
    options = ProductOptions.objects.all().values('id', 'option_title', 'option_value')
    return JsonResponse(list(options), safe=False)


@csrf_exempt
def finalize_product_form(request):
    """
    Обрабатывает сохранение продукта (создание или обновление).
    """
    if request.method == 'POST':
        try:
            data = json.loads(request.POST.get('product_data'))
            product_id = data.get('product_id')  # Получаем ID продукта, если передан

            if product_id:  # Обновляем существующий продукт
                product = get_object_or_404(Product, id=product_id)
                product.titles = data['titles']
                product.main_images = data['main_images']
                product.additional_images = data['additional_images']
                product.descriptions = data['descriptions']
                product.addresses = data['addresses']
                product.category = data['category']
                product.listingfee = data['listingfee']
                product.email = data['email']
                product.contactphone = data['contactphone']
                product.managername = data['managername']
                product.avitostatus = data['avitostatus']
                product.companyname = data['companyname']
                product.contactmethod = data['contactmethod']
                product.adtype = data['adtype']
                product.availability = data['availability']
                product.price = data['price']
                product.price_max = data['price_max']
                product.price_min = data['price_min']
                product.price_step = data['price_step']
                product.schedule = data.get('schedule', {})
                product.save()

                # Обновляем опции
                ProductOptionAssignment.objects.filter(product=product).delete()
                for option_data in data.get('options', []):
                    option = ProductOptions.objects.get(id=option_data['option_id'])
                    ProductOptionAssignment.objects.create(
                        product=product,
                        option=option,
                        selected_value=option_data['value']
                    )
            else:  # Создаем новый продукт
                selected_projects = data['projects']
                projects = Project.objects.filter(id__in=selected_projects)

                product = Product.objects.create(
                    name=f"Задача {random.randint(0, 20000000000)}",
                    titles=data['titles'],
                    main_images=data['main_images'],
                    additional_images=data['additional_images'],
                    descriptions=data['descriptions'],
                    addresses=data['addresses'],
                    category=data['category'],
                    listingfee=data['listingfee'],
                    email=data['email'],
                    contactphone=data['contactphone'],
                    managername=data['managername'],
                    avitostatus=data['avitostatus'],
                    companyname=data['companyname'],
                    contactmethod=data['contactmethod'],
                    adtype=data['adtype'],
                    availability=data['availability'],
                    price=data['price'],
                    price_max=data['price_max'],
                    price_min=data['price_min'],
                    price_step=data['price_step'],
                    possible_combinations=data['possible_combinations'],
                    schedule=data.get('schedule', {}),
                )
                product.update_next_update_time()
                product.projects.set(projects)

                for option_data in data.get('options', []):
                    try:
                        option = ProductOptions.objects.get(id=option_data['option_id'])
                        ProductOptionAssignment.objects.create(
                            product=product,
                            option=option,
                            selected_value=option_data['value']
                        )
                    except ProductOptions.DoesNotExist:
                        print(f"Опция с ID {option_data['option_id']} не найдена.")

            return JsonResponse({'message': 'Продукт успешно сохранён!'})

        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)


@csrf_exempt
def remove_selected_option(request, adv_id):
    if request.method == 'POST':
        data = json.loads(request.body)
        option_key = data.get('option_key')
        try:
            adv = Product1.objects.get(pk=adv_id)
            if option_key in adv.selected_option:
                # Удаляем ключ из словаря
                adv.selected_option.pop(option_key)
                adv.save()
                return JsonResponse({'success': True})
            else:
                return JsonResponse({'success': False, 'error': 'Опция не найдена'})
        except Product1.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Объявление не найдено'})
    return JsonResponse({'success': False, 'error': 'Неподходящий метод запроса'})


def update_option_csv(adv_id):
    """
    Функция для обновления опций в CSV-файлах по уже существующим записям.
    Ищет строки по TaskId, Title и CreatDate, затем обновляет столбцы по ключам selected_option.
    """
    # 1. Получаем объект Product1
    from .models import \
        Product1  # Импортируйте модель, если она в том же приложении (скорее всего cworker или avitotask и т.п.)
    adv = Product1.objects.get(pk=adv_id)

    # Преобразуем дату создания в ту же строку, что использовалась при записи CSV
    # (в product_random используется формат '%Y-%m-%d' для CreatDate)
    create_date_str = adv.created_date.strftime('%Y-%m-%d')

    # 2. Проходим по списку проектов, записанных в adv.project_name
    for project_name in adv.project_name:
        # Формируем путь к CSV-файлу
        file_name = f"{project_name}_avito_autoload.csv"
        file_path = os.path.join(settings.STATIC_ROOT, file_name)

        # Если файла нет — пропускаем
        if not os.path.exists(file_path):
            continue

        # 3. Читаем CSV в DataFrame (сохранённый ранее с разделителем ';')
        df = pd.read_csv(file_path, sep=';', dtype=str)

        # Убедимся, что в CSV есть нужные колонки: TaskId, Title, CreatDate
        required_cols = {'TaskId', 'Title', 'CreatDate'}
        if not required_cols.issubset(df.columns):
            # Если каких-то из нужных столбцов нет, можно либо пропустить,
            # либо вывести предупреждение. Здесь пропустим.
            continue

        # 4. Фильтруем строки, у которых совпадают TaskId, Title, CreatDate
        mask = (
                (df['TaskId'] == str(adv.task_id)) &
                (df['Title'] == adv.title) &
                (df['CreatDate'] == create_date_str)
        )

        # Если подходящих строк нет, тоже можно пропустить
        if not mask.any():
            continue

        # 5. Убедимся, что для каждого ключа из adv.selected_option у нас есть столбец
        # Если нет — создаём пустой столбец.
        for key in adv.selected_option.keys():
            if key not in df.columns:
                df[key] = ""

        # 6. Обновляем значения в найденных строках
        for key, val in adv.selected_option.items():
            df.loc[mask, key] = val

        # 7. Сохраняем обновлённую таблицу обратно
        df.to_csv(file_path, sep=';', index=False, encoding='utf-8')


@csrf_exempt
def save_adv_options(request, adv_id):
    """
    Пример вьюхи, которая принимает JSON с "selected_options"
    и сохраняет в Product1.selected_option
    """
    if request.method == 'POST':
        try:
            body = json.loads(request.body)
            new_options = body.get('selected_options', [])
            adv = Product1.objects.get(pk=adv_id)

            # Если у вас new_options = [{'option_id': 'Цвет', 'value': 'Красный'}, ...]
            # то можно преобразовать в словарь:
            updated_dict = {}
            for item in new_options:
                # Здесь item['option_id'] может быть либо название, либо числовой ID
                # В зависимости от вашей логики, делайте map из ID → title
                updated_dict[item['option_id']] = item['value']

            adv.selected_option = updated_dict
            adv.save()

            update_option_csv(adv_id)

            return JsonResponse({'message': 'Опции обновлены!'})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)

    return JsonResponse({'error': 'Неверный метод'}, status=405)


def get_product_data(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    data = {
        'titles': product.titles,
        'main_images': product.main_images,
        'additional_images': product.additional_images,
        'descriptions': product.descriptions,
        'addresses': product.addresses,
        'options': [
            {
                'option_title': assignment.option.option_title,
                'selected_value': assignment.selected_value,
            }
            for assignment in product.productoptionassignment_set.select_related('option')
        ],
    }
    return JsonResponse(data)
