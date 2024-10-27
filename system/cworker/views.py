from django.shortcuts import render


def notification_page_view(request):
    return render(request, 'notification_page.html')
