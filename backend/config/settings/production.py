"""
Production Settings for ZENTIQ.
Enforces strict security, HTTPS, and environment-driven secrets.
"""
from .base import *
import os
from django.core.exceptions import ImproperlyConfigured

DEBUG = False

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    raise ImproperlyConfigured("Production environment error: 'DJANGO_SECRET_KEY' is required.")

allowed_hosts_raw = os.environ.get('DJANGO_ALLOWED_HOSTS')
if not allowed_hosts_raw:
    raise ImproperlyConfigured("Production environment error: 'DJANGO_ALLOWED_HOSTS' is required.")
ALLOWED_HOSTS = [host.strip() for host in allowed_hosts_raw.split(',') if host.strip()]

# Production strictly requires MySQL 8.4; SQLite is strictly forbidden
db_engine = os.getenv('DB_ENGINE', 'django.db.backends.mysql')
if 'sqlite' in db_engine.lower():
    raise ImproperlyConfigured(
        "SQLite is strictly forbidden in production. ZENTIQ production requires MySQL 8.4."
    )

for required_var in ('DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_HOST'):
    if required_var not in os.environ or not os.environ[required_var]:
        raise ImproperlyConfigured(
            f"Production database configuration error: '{required_var}' environment variable is missing or empty. "
            f"MySQL 8.4 credentials are mandatory in production."
        )

# Database (Production requires explicit MySQL environment credentials)
DATABASES = {
    'default': {
        'ENGINE': db_engine,
        'NAME': os.environ['DB_NAME'],
        'USER': os.environ['DB_USER'],
        'PASSWORD': os.environ['DB_PASSWORD'],
        'HOST': os.environ['DB_HOST'],
        'PORT': os.getenv('DB_PORT', '3306'),
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}

# Production Security Headers & Cookies
SECURE_SSL_REDIRECT = os.getenv('SECURE_SSL_REDIRECT', 'True').lower() in ('true', '1', 't')
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {
            'format': '%(asctime)s %(levelname)s %(name)s %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'json',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
        'apps': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

