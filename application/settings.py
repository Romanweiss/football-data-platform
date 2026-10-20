"""Local API settings: no ORM, sessions, admin, authentication or template UI."""
import os
import secrets
from django.core.exceptions import ImproperlyConfigured

PRODUCTION = os.environ.get("API_SERVING_MODE", "development") == "production"
if PRODUCTION and os.environ.get("DJANGO_SECRET_KEY", "") in ("", "set_me", "change_me"):
    raise ImproperlyConfigured("Production API requires a runtime DJANGO_SECRET_KEY")
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or secrets.token_urlsafe(48)
DEBUG = False
ALLOWED_HOSTS = os.environ.get("API_ALLOWED_HOSTS", "localhost,127.0.0.1,football-api").split(",")
ROOT_URLCONF = "application.urls"
WSGI_APPLICATION = "application.wsgi.application"
INSTALLED_APPS = []
DATABASES = {}
MIDDLEWARE = ["application.transport.ApiMiddleware", "django.middleware.security.SecurityMiddleware"]
APPEND_SLASH = False
USE_TZ = True
TIME_ZONE = "UTC"
DATA_UPLOAD_MAX_MEMORY_SIZE = 16384
# Only the internal production API trusts the sole browser-facing HTTP proxy.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if PRODUCTION else None
# Never send raw driver/Django exceptions or SQL to logs. The transport emits
# bounded status/class diagnostics, not request parameters or exception text.
LOGGING = {
    "version": 1, "disable_existing_loggers": False,
    "handlers": {"null": {"class": "logging.NullHandler"}, "console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "django": {"handlers": ["null"], "propagate": False},
        "clickhouse_connect": {"handlers": ["null"], "propagate": False},
        "football_api": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
