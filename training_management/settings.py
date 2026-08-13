from pathlib import Path

from decouple import config
from dotenv import load_dotenv


# =============================================================================
# Environment
# =============================================================================

load_dotenv()


# =============================================================================
# Base Directory
# =============================================================================

BASE_DIR = Path(__file__).resolve().parent.parent


# =============================================================================
# Groq / AI Configuration
# =============================================================================

GROQ_API_KEY = config("GROQ_API_KEY", default="")
GROQ_MODEL = config(
    "GROQ_MODEL",
    default="openai/gpt-oss-120b",
)


# =============================================================================
# Core / Security
# =============================================================================

SECRET_KEY = config(
    "SECRET_KEY",
    default="django-insecure-change-me-in-production",
)

DEBUG = config(
    "DEBUG",
    default=False,
    cast=bool,
)


# Hosts allowed to access Django
ALLOWED_HOSTS = [
    "tms-pvc.vercel.app",
    "localhost",
    "127.0.0.1",
]


# Trusted origins for Django CSRF protection
CSRF_TRUSTED_ORIGINS = [
    "https://tms-pvc.vercel.app",
]


# =============================================================================
# Applications
# =============================================================================

INSTALLED_APPS = [
    # Django applications
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Project applications
    "core",
]


# =============================================================================
# Middleware
# =============================================================================

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",

    # WhiteNoise serves static files in production
    "whitenoise.middleware.WhiteNoiseMiddleware",

    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


# =============================================================================
# URL / WSGI Configuration
# =============================================================================

ROOT_URLCONF = "training_management.urls"

WSGI_APPLICATION = "training_management.wsgi.application"


# =============================================================================
# Templates
# =============================================================================

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",

        "DIRS": [
            BASE_DIR / "templates",
        ],

        "APP_DIRS": True,

        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


# =============================================================================
# Database
# =============================================================================
#
# Local development:
#
#     DB_ENGINE=sqlite
#
# Production / Vercel:
#
#     DB_ENGINE=postgres
#     DB_NAME=...
#     DB_USER=...
#     DB_PASSWORD=...
#     DB_HOST=...
#     DB_PORT=5432
#
# =============================================================================

DB_ENGINE = config(
    "DB_ENGINE",
    default="sqlite",
).lower()


if DB_ENGINE == "postgres":

    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",

            "NAME": config("DB_NAME"),

            "USER": config("DB_USER"),

            "PASSWORD": config("DB_PASSWORD"),

            "HOST": config("DB_HOST"),

            "PORT": config(
                "DB_PORT",
                default="5432",
            ),

            "CONN_MAX_AGE": 60,

            "OPTIONS": {
                "connect_timeout": 10,
            },
        }
    }

else:

    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


# =============================================================================
# Password Validation
# =============================================================================

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME":
        "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME":
        "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME":
        "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME":
        "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# =============================================================================
# Internationalization
# =============================================================================

LANGUAGE_CODE = "en-us"

TIME_ZONE = "Africa/Kigali"

USE_I18N = True

USE_TZ = True


# =============================================================================
# Static Files
# =============================================================================
#
# Source:
#     static/
#
# Collected files:
#     staticfiles/
#
# WhiteNoise serves the collected files in production.
#
# =============================================================================

STATIC_URL = "/static/"

STATICFILES_DIRS = [
    BASE_DIR / "static",
]

STATIC_ROOT = BASE_DIR / "staticfiles"


# Django 6 static-file storage configuration
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },

    "staticfiles": {
        "BACKEND":
        "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}


# =============================================================================
# Media Files
# =============================================================================

MEDIA_URL = "/media/"

MEDIA_ROOT = BASE_DIR / "media"


# =============================================================================
# Authentication / Login
# =============================================================================

LOGIN_URL = "login"

LOGIN_REDIRECT_URL = "dashboard"

LOGOUT_REDIRECT_URL = "landing"


# =============================================================================
# Default Primary Key
# =============================================================================

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# =============================================================================
# Security Settings
# =============================================================================
#
# These are appropriate when DEBUG=False in production.
#
# =============================================================================

SECURE_BROWSER_XSS_FILTER = True

SECURE_CONTENT_TYPE_NOSNIFF = True

X_FRAME_OPTIONS = "DENY"


# HTTPS-related settings
#
# Enable these only when your production site is definitely being served
# through HTTPS and Vercel is correctly forwarding the HTTPS request.
#

SECURE_PROXY_SSL_HEADER = (
    "HTTP_X_FORWARDED_PROTO",
    "https",
)


# =============================================================================
# Logging
# =============================================================================

LOGGING = {
    "version": 1,

    "disable_existing_loggers": False,

    "formatters": {
        "verbose": {
            "format":
            "{levelname} {asctime} {name} {message}",
            "style": "{",
        },

        "simple": {
            "format":
            "{levelname} {message}",
            "style": "{",
        },
    },

    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
    },

    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },

    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },

        "core": {
            "handlers": ["console"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
    },
}
