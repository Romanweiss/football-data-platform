"""Local/dev synchronous Superset. All credentials come from environment."""

import os
import re
from urllib.parse import quote


def required(name):
    value = os.environ.get(name, "")
    if not value.strip():
        raise ValueError(f"Missing required environment variable: {name}")
    return value


SECRET_KEY = required("SUPERSET_SECRET_KEY")
if len(SECRET_KEY) < 32 or SECRET_KEY.lower() in {"change_me", "your_secret_key", "this_is_not_a_secret_key"}:
    raise ValueError("SUPERSET_SECRET_KEY must be a private random value of at least 32 characters")

_database = required("SUPERSET_DB_NAME")
if _database == "football_metadata":
    raise ValueError("Superset requires its own metadata database")
if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", _database):
    raise ValueError("SUPERSET_DB_NAME must be a simple PostgreSQL identifier")
_user = required("SUPERSET_DB_USER")
_password = required("SUPERSET_DB_PASSWORD")
_host = required("SUPERSET_DB_HOST")
if _host != "football-superset-db":
    raise ValueError("SUPERSET_DB_HOST must be the dedicated football-superset-db service")
SQLALCHEMY_DATABASE_URI = (
    f"postgresql+psycopg2://{quote(_user, safe='')}:{quote(_password, safe='')}"
    f"@{_host}:5432/{quote(_database, safe='')}"
)
SQLALCHEMY_TRACK_MODIFICATIONS = False
WTF_CSRF_ENABLED = True
# Local loopback HTTP only. A production deployment needs TLS and secure cookies.
TALISMAN_ENABLED = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
FEATURE_FLAGS = {"ALERT_REPORTS": False, "GLOBAL_ASYNC_QUERIES": False}
# No Redis/Celery service: requests and chart queries execute synchronously.
THUMBNAILS = False
