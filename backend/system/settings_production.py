from .settings import *

DEBUG = False

SECRET_KEY = required_env("SECRET_KEY")

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS")
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("ALLOWED_HOSTS is required in production")

SITE_URL = required_env("SITE_URL")
FRONTEND_URL = required_env("FRONTEND_URL")

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

AUTH_REFRESH_COOKIE_SECURE = env_bool("AUTH_REFRESH_COOKIE_SECURE", default=False)
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", default=False)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", default=False)

SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", default=False)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
REFERRER_POLICY = "same-origin"

SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False)
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", default=False)

DATABASES["default"].update({
    "NAME": required_env("POSTGRES_DB"),
    "USER": required_env("POSTGRES_USER"),
    "PASSWORD": required_env("POSTGRES_PASSWORD"),
    "HOST": required_env("DB_HOST"),
    "PORT": required_env("DB_PORT"),
})
