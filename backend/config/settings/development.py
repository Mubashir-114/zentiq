"""
Development Settings for ZENTIQ.
Configured for seamless local development:
- Defaults to local SQLite (BASE_DIR / 'db.sqlite3') when no MySQL credentials are provided.
- Selects MySQL 8.4 when DB_PASSWORD is provided or DB_ENGINE is explicitly 'django.db.backends.mysql'.
- Raises ImproperlyConfigured if MySQL is explicitly selected but credentials are missing.
"""
from .base import *
import os
from django.core.exceptions import ImproperlyConfigured

DEBUG = True

# Database engine selection logic
# 1. Explicit SQLite toggle via existing switches
use_explicit_sqlite = (
    os.getenv('USE_SQLITE_TEST_DB', '').lower() in ('true', '1', 't')
    or os.getenv('USE_SQLITE_DEV_DB', '').lower() in ('true', '1', 't')
    or os.getenv('DB_ENGINE', '') == 'django.db.backends.sqlite3'
)

# 2. Check if MySQL is explicitly requested
db_engine_env = os.getenv('DB_ENGINE', '').strip()
is_explicit_mysql = db_engine_env in ('django.db.backends.mysql', 'mysql')

# 3. Read MySQL configuration from environment
db_name = os.getenv('DB_NAME', 'zentiq_dev')
db_user = os.getenv('DB_USER', 'zentiq_user')
db_password = os.getenv('DB_PASSWORD', '')
db_host = os.getenv('DB_HOST', '127.0.0.1')
db_port = os.getenv('DB_PORT', '3306')

if use_explicit_sqlite:
    # Explicitly requested SQLite via environment switch
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
elif is_explicit_mysql:
    # Developer explicitly requested MySQL: enforce that credentials are provided
    if not db_password:
        raise ImproperlyConfigured(
            "DB_ENGINE is explicitly set to MySQL ('django.db.backends.mysql'), but DB_PASSWORD is missing or empty. "
            "Please provide DB_PASSWORD in your environment / .env file, or set DB_ENGINE=django.db.backends.sqlite3 "
            "(or USE_SQLITE_TEST_DB=True) to use the local SQLite database."
        )
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': db_name,
            'USER': db_user,
            'PASSWORD': db_password,
            'HOST': db_host,
            'PORT': db_port,
            'OPTIONS': {
                'charset': 'utf8mb4',
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }
elif db_password:
    # MySQL credentials are provided even if DB_ENGINE was not explicitly stated
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': db_name,
            'USER': db_user,
            'PASSWORD': db_password,
            'HOST': db_host,
            'PORT': db_port,
            'OPTIONS': {
                'charset': 'utf8mb4',
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }
else:
    # Default to local SQLite when no MySQL credentials or explicit DB_ENGINE are provided
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# Development Email Backend
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} [{name}:{lineno}] {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'apps': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}

