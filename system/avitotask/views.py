from django.shortcuts import render, redirect, get_object_or_404
from .models import Product
from .forms import ProductForm


def product_create_or_update(request, pk=None):
    product = get_object_or_404(Product, pk=pk) if pk else None
    if request.method == 'POST':
        name = request.POST.get('name')
        price = request.POST.get('price')
        titles = request.POST.getlist('titles[]')  # Заголовки приходят в виде списка

        if product:
            product.name = name
            product.price = price
            product.titles = titles
        else:
            product = Product(name=name, price=price, titles=titles)
        product.save()
        return redirect('product_list')  # Перенаправляем на список продуктов

    return render(request, 'add_product.html', {'product': product})


def product_list(request):
    products = Product.objects.all()
    return render(request, 'product_list.html', {'products': products})
