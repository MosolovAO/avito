import os
from datetime import datetime
from django.http import JsonResponse

from django.views.decorators.csrf import csrf_exempt

from system import settings
from .models import Product, ProductImage

from django.http import JsonResponse
from django.conf import settings


@csrf_exempt
def upload_images(request, product_id):
    """
    Обработчик для загрузки изображений и добавления их в main_images или additional_images.
    """
    if request.method == 'POST' and request.FILES:
        try:
            product = Product.objects.get(id=product_id)
            uploaded_files = []

            for file_key in request.FILES:
                file = request.FILES[file_key]

                # Проверка типа файла
                if not file.content_type in ['image/jpeg', 'image/jpg']:
                    return JsonResponse({'error': 'Можно загружать только файлы JPEG.'}, status=400)

                # Сохранение файла
                today = datetime.now().strftime('%d-%m-%y')
                folder_path = os.path.join(settings.MEDIA_ROOT, 'uploads', today)
                os.makedirs(folder_path, exist_ok=True)

                filename = f"{product.id}_{file.name}"
                file_path = os.path.join(folder_path, filename)

                with open(file_path, 'wb+') as destination:
                    for chunk in file.chunks():
                        destination.write(chunk)

                # Формирование полного URL
                relative_url = os.path.join('uploads', today, filename)
                full_url = request.build_absolute_uri(settings.MEDIA_URL + relative_url)

                uploaded_files.append(full_url)

            # Добавление ссылок в main_images или additional_images
            product.main_images.extend(uploaded_files)  # или product.additional_images.extend(uploaded_files)
            product.save()

            return JsonResponse({'uploaded_files': uploaded_files}, status=200)

        except Product.DoesNotExist:
            return JsonResponse({'error': 'Продукт не найден.'}, status=404)

    return JsonResponse({'error': 'Некорректный запрос.'}, status=400)
