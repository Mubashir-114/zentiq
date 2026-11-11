"""
Assessment-Scoped Exception Adapter for ZENTIQ (Phase 2D.3).
Normalizes domain service exceptions into the standard API error response envelope
and delegates unrelated DRF exceptions to the global custom_exception_handler.
"""
import logging
from typing import Any

from rest_framework import status
from rest_framework.response import Response

from apps.core.exceptions import custom_exception_handler
from apps.assessments.services.exceptions import (
    ActiveAttemptExistsError,
    AnswerValidationError,
    AttemptRedactedError,
    AssessmentDeprecatedError,
    AssessmentNoActiveVersionError,
    AssessmentNotFoundError,
    AssessmentPermissionDeniedError,
    AssessmentServiceError,
    AssessmentValidationError,
    AssessmentVersionImmutabilityError,
    AssessmentVersionNotFoundError,
    AttemptExpiredError,
    AttemptNotFoundError,
    AttemptTerminalError,
    BacktrackingNotAllowedError,
    ConcurrencyConflictError,
    DuplicateCanonicalQuestionError,
    IncompleteAssessmentVersionError,
    InvalidAssessmentStateError,
    InvalidNavigationError,
    InvalidQuestionOrderError,
    InvalidQuestionWeightError,
    InvalidVersionTransitionError,
    LockTimeoutError,
    QuestionDeprecatedError,
    QuestionNotPublishedError,
    ResultRevisionConflictError,
    ResultRevisionIntegrityError,
    TerminalSnapshotConflictError,
)

logger = logging.getLogger('apps.assessments')

# Authoritative mapping of domain exceptions to HTTP status codes
EXCEPTION_STATUS_MAP: dict[type[AssessmentServiceError], int] = {
    # 404 Not Found
    AssessmentNotFoundError: status.HTTP_404_NOT_FOUND,
    AssessmentVersionNotFoundError: status.HTTP_404_NOT_FOUND,
    AttemptNotFoundError: status.HTTP_404_NOT_FOUND,

    # 403 Forbidden
    AssessmentPermissionDeniedError: status.HTTP_403_FORBIDDEN,

    # 409 Conflict
    ActiveAttemptExistsError: status.HTTP_409_CONFLICT,
    AttemptTerminalError: status.HTTP_409_CONFLICT,
    ConcurrencyConflictError: status.HTTP_409_CONFLICT,
    AssessmentVersionImmutabilityError: status.HTTP_409_CONFLICT,
    InvalidAssessmentStateError: status.HTTP_409_CONFLICT,
    InvalidVersionTransitionError: status.HTTP_409_CONFLICT,
    DuplicateCanonicalQuestionError: status.HTTP_409_CONFLICT,
    AssessmentDeprecatedError: status.HTTP_409_CONFLICT,
    AssessmentNoActiveVersionError: status.HTTP_409_CONFLICT,
    ResultRevisionConflictError: status.HTTP_409_CONFLICT,
    ResultRevisionIntegrityError: status.HTTP_409_CONFLICT,
    AttemptRedactedError: status.HTTP_409_CONFLICT,
    TerminalSnapshotConflictError: status.HTTP_409_CONFLICT,

    # 410 Gone
    AttemptExpiredError: status.HTTP_410_GONE,

    # 503 Service Unavailable (MySQL lock wait timeout 1205)
    LockTimeoutError: status.HTTP_503_SERVICE_UNAVAILABLE,

    # 400 Bad Request
    BacktrackingNotAllowedError: status.HTTP_400_BAD_REQUEST,
    InvalidNavigationError: status.HTTP_400_BAD_REQUEST,
    AnswerValidationError: status.HTTP_400_BAD_REQUEST,
    AssessmentValidationError: status.HTTP_400_BAD_REQUEST,
    InvalidQuestionOrderError: status.HTTP_400_BAD_REQUEST,
    InvalidQuestionWeightError: status.HTTP_400_BAD_REQUEST,
    QuestionNotPublishedError: status.HTTP_400_BAD_REQUEST,
    QuestionDeprecatedError: status.HTTP_400_BAD_REQUEST,
    IncompleteAssessmentVersionError: status.HTTP_400_BAD_REQUEST,
    AssessmentServiceError: status.HTTP_400_BAD_REQUEST,
}


def assessment_exception_handler(exc: Exception, context: dict[str, Any]) -> Response:
    """
    Assessment-scoped exception adapter.

    Intercepts domain-specific AssessmentServiceError exceptions and formats them
    using the standardized ZENTIQ error envelope:
    {
        "error": {
            "code": "<error_code>",
            "message": "<human_readable_message>",
            "details": {...} or null
        }
    }

    Delegates all other exceptions (standard DRF authentication/permission/validation,
    Django 404, etc.) directly to apps.core.exceptions.custom_exception_handler.
    """
    if isinstance(exc, AssessmentServiceError):
        # Resolve HTTP status code
        http_status = getattr(exc, 'status_code', None)
        if http_status is None:
            for exc_cls, mapped_status in EXCEPTION_STATUS_MAP.items():
                if isinstance(exc, exc_cls):
                    http_status = mapped_status
                    break
        if http_status is None:
            http_status = status.HTTP_400_BAD_REQUEST

        error_code = getattr(exc, 'code', 'assessment_error')
        error_message = getattr(exc, 'message', str(exc))
        details = getattr(exc, 'details', None) or None

        return Response(
            {
                'error': {
                    'code': str(error_code).lower(),
                    'message': str(error_message),
                    'details': details,
                }
            },
            status=http_status,
        )

    # Delegate all other exceptions to the centralized core handler
    return custom_exception_handler(exc, context)

