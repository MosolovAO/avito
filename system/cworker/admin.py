from django.contrib import admin

from django import forms
from .models import Notification


class SendNotificationForm(forms.Form):
    message = forms.CharField(label="Notification Message", max_length=200, widget=forms.Textarea)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    pass
