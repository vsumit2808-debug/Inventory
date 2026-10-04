"""
Django settings for StockWise.

Cross-OS design rules
---------------------
* Every machine-specific value comes from environment variables (or a .env
  file placed next to manage.py). The same code runs unmodified on
  macOS, Windows and Linux.
* Database defaults to MySQL (the required stack) using the pure-Python
  PyMySQL driver - no compiler needed on any OS.
* Set DB_ENGINE=sqlite for a zero-setup demo run.
"""
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

# Optional .env support (python-dotenv). Safe to miss on any OS.
try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:  # pragma: no cover
    pass

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [
    h.strip()
    for h in os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",")
    if h.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "inventory.apps.InventoryConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "stockwise.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "stockwise.wsgi.application"

# ---------------------------------------------------------------------------
# Database - MySQL first (required stack), SQLite as instant demo fallback
# ---------------------------------------------------------------------------
DB_ENGINE = os.getenv("DB_ENGINE", "mysql").lower()

if DB_ENGINE == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / os.getenv("SQLITE_NAME", "stockwise_demo.sqlite3"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": os.getenv("DB_NAME", "stockwise"),
            "USER": os.getenv("DB_USER", "root"),
            "PASSWORD": os.getenv("DB_PASSWORD", ""),
            "HOST": os.getenv("DB_HOST", "127.0.0.1"),
            "PORT": os.getenv("DB_PORT", "3306"),
            "OPTIONS": {
                "charset": "utf8mb4",
            },
        }
    }

# ---------------------------------------------------------------------------
# Internationalisation / static
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("TIME_ZONE", "Asia/Kolkata")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# StockWise specific
# ---------------------------------------------------------------------------
# Currency symbol used in reports and pages. ASCII-safe by default so the
# console/text reports never crash a Windows code page.
CURRENCY_SYMBOL = os.getenv("CURRENCY_SYMBOL", "$")

# Where the daily restock reports (TXT/CSV) are written.
REPORT_DIR = Path(os.getenv("REPORT_DIR", str(BASE_DIR / "reports")))

# ---------------------------------------------------------------------------
# Optional e-mail delivery of the daily report (all vars must be set)
# ---------------------------------------------------------------------------
if os.getenv("EMAIL_HOST"):
    EMAIL_HOST = os.getenv("EMAIL_HOST")
    EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
    EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "1") == "1"
    STOCK_ALERT_EMAIL_TO = os.getenv("STOCK_ALERT_EMAIL_TO", "")
