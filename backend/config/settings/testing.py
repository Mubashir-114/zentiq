"""
Testing Settings for ZENTIQ.
Provides an isolated, fast testing environment using SQLite in-memory or file database.
"""
from .base import *

DEBUG = False

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

# Faster testing without real network/console logs
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

# Relax throttle rates for testing suite; specific rate-limiting tests override explicitly
REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'] = {
    'anon': '10000/minute',
    'user': '10000/minute',
    'auth_login': '10000/minute',
    'auth_register': '10000/minute',
}


