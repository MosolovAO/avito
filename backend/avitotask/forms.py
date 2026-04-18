from django import forms
from django.forms import inlineformset_factory
from .models import Product


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['name', 'price']

