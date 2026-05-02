from django.urls import path
from .api_views import CookieLoginView, CookieLogoutView, CookieRefreshView, MeView, RegisterView

urlpatterns = [
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("login/", CookieLoginView.as_view(), name="auth-login"),
    path("refresh/", CookieRefreshView.as_view(), name="auth-refresh"),
    path("logout/", CookieLogoutView.as_view(), name="auth-logout"),
    path("me/", MeView.as_view(), name="auth-me"),
]
