"""Django settings for the AgniDrishti prototype."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = os.getenv("DEBUG", "True").lower() in ("1", "true", "yes")
ALLOWED_HOSTS = ["*"] if DEBUG else os.getenv("ALLOWED_HOSTS", "").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "hotspots",
    "classification",
    "dashboard",
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

ROOT_URLCONF = "core.urls"

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

WSGI_APPLICATION = "core.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Argon2id is the preferred hasher, as documented in the security section.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- AgniDrishti configuration -------------------------------------------------

FIRMS_MAP_KEY = os.getenv("FIRMS_MAP_KEY", "")

DATA_DIR = BASE_DIR / "data"


def _bbox(name: str, default: str) -> tuple[float, float, float, float]:
    """Parse a 'lon_min,lat_min,lon_max,lat_max' env var into a tuple."""
    raw = os.getenv(name, default)
    parts = [float(p.strip()) for p in raw.split(",")]
    if len(parts) != 4:
        raise ValueError(f"{name} must have 4 comma-separated values, got {raw!r}")
    return tuple(parts)  # type: ignore[return-value]


# Where the system runs.
INGEST_BBOX = _bbox("INGEST_BBOX", "68.9,20.0,73.5,23.6")
# Where it is validated: the Hazira-Dahej-Bharuch-Ankleshwar corridor.
VALIDATION_BBOX = _bbox("VALIDATION_BBOX", "72.4,21.0,73.2,22.0")

# Detections within this grid cell size are treated as one persistent site.
# 0.005 degrees is roughly 550 m, chosen to absorb VIIRS geolocation jitter
# (375 m nominal pixel) without merging genuinely separate facilities.
SITE_GRID_DEG = 0.005

# Rolling window used for recurrence statistics.
RECURRENCE_WINDOW_DAYS = 90
