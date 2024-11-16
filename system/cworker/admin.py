from django.contrib import admin

from django import forms
from .models import Notification, Record


class SendNotificationForm(forms.Form):
    message = forms.CharField(label="Notification Message", max_length=200, widget=forms.Textarea)


@admin.register(Record)
class RecordAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'interval')
    list_editable = ('interval',)
    search_fields = ('title',)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    add_form = "admin/custom_add_form.html"
