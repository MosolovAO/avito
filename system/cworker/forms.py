# myapp/forms.py
from django import forms
from .models import Post


class PostForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = ['title', 'headings', 'interval', 'is_running']
        widgets = {
            'headings': forms.Textarea(attrs={'placeholder': 'Заголовок1, Заголовок2, Заголовок3...'}),
        }
