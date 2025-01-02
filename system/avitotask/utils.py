import os
from datetime import datetime
from django.http import JsonResponse

from django.views.decorators.csrf import csrf_exempt

from system import settings
from .models import Product, ProductImage


@csrf_exempt
def upload_images(request, product_id):
    """
    Обработчик для загрузки изображений
    """
    if request.method == 'POST' and request.FILES:
        try:
            # Проверяем существование продукта
            product = Product.objects.get(id=product_id)
            uploaded_files = []

            # Обрабатываем файлы
            for file_key in request.FILES:
                file = request.FILES[file_key]

                # Проверяем тип файла
                if not file.content_type in ['image/jpeg', 'image/jpg']:
                    return JsonResponse({'error': 'Можно загружать только файлы JPEG.'}, status=400)

                # Формируем путь к файлу
                today = datetime.now().strftime('%d-%m-%y')
                folder_path = os.path.join(settings.MEDIA_ROOT, 'uploads', today)
                os.makedirs(folder_path, exist_ok=True)

                filename = f"{product.id}_{file.name}"
                file_path = os.path.join(folder_path, filename)

                # Сохраняем файл
                with open(file_path, 'wb+') as destination:
                    for chunk in file.chunks():
                        destination.write(chunk)

                # Добавляем путь к файлу в список
                uploaded_files.append(os.path.join('uploads', today, filename))

            return JsonResponse({'uploaded_files': uploaded_files}, status=200)

        except Product.DoesNotExist:
            return JsonResponse({'error': 'Продукт не найден.'}, status=404)

    return JsonResponse({'error': 'Некорректный запрос.'}, status=400)


