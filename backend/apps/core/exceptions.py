"""
Centralized DRF Exception Handling for ZENTIQ.
Normalizes all API error responses into a consistent, predictable structure.
"""
import logging
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger('apps.core')

def custom_exception_handler(exc, context):
    """
    Custom exception handler that wraps DRF error responses in a standardized format:
    {
        "error": {
            "code": "error_code",
            "message": "Human readable message",
            "details": {...}
        }
    }
    """
    response = exception_handler(exc, context)

    if response is not None:
        # Standardize NotAuthenticated and AuthenticationFailed to 401 (DRF defaults to 403 when no WWW-Authenticate header is present)
        if isinstance(exc, (exceptions.NotAuthenticated, exceptions.AuthenticationFailed)):
            response.status_code = status.HTTP_401_UNAUTHORIZED

        # Extract specific error code if set on exc.detail or exc, falling back to default_code
        detail_code = getattr(getattr(exc, 'detail', None), 'code', None)
        error_code = detail_code or getattr(exc, 'code', None) or getattr(exc, 'default_code', 'error')
        error_message = 'An error occurred while processing your request.'

        if isinstance(response.data, dict) and 'detail' in response.data:
            error_message = str(response.data['detail'])
            details = None
        else:
            details = response.data

        response.data = {
            'error': {
                'code': str(error_code),
                'message': error_message,
                'details': details,
            }
        }
    else:
        # Unhandled server errors (500)
        logger.exception("Unhandled server exception encountered: %s", exc)
        response = Response(
            {
                'error': {
                    'code': 'internal_server_error',
                    'message': 'An unexpected error occurred. Please try again later.',
                    'details': None,
                }
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return response

