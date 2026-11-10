"""
Domain authorization guards for ZENTIQ Assessments (Milestone 4A - Phase 2D.2).
Enforces backend-side access control for assessment authoring, attempts, answers, and lifecycle actions.
"""
from typing import Any, Optional

from django.contrib.auth import get_user_model

from .exceptions import AssessmentPermissionDeniedError

User = get_user_model()


def check_authenticated_and_active(user: Any) -> None:
    """
    Ensures that the user instance is authenticated and has an active account.
    """
    if user is None or not getattr(user, 'is_authenticated', False):
        raise AssessmentPermissionDeniedError("Authentication required.")
    if not getattr(user, 'is_active', False):
        raise AssessmentPermissionDeniedError("User account is inactive.")


def can_manage_assessment(user: Any, assessment: Optional[Any] = None) -> bool:
    """
    Evaluates whether a user can author or modify an assessment series / draft version.
    Privilege granted to staff, superusers, users with assessment permissions,
    or the creator of the assessment.
    """
    if user is None or not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_active', False):
        return False

    if getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False):
        return True

    if user.has_perm('assessments.change_assessment') or user.has_perm('assessments.add_assessment'):
        return True

    if assessment and getattr(assessment, 'created_by_id', None) == user.pk:
        return True

    return False


def check_can_manage_assessment(user: Any, assessment: Optional[Any] = None) -> None:
    """
    Raises AssessmentPermissionDeniedError if user cannot manage the assessment.
    """
    check_authenticated_and_active(user)
    if not can_manage_assessment(user, assessment):
        raise AssessmentPermissionDeniedError(
            "You do not have permission to manage this assessment."
        )


def can_start_attempt(user: Any, assessment: Any) -> bool:
    """
    Evaluates whether a user can start or resume an attempt on the assessment.
    Candidate must be authenticated and active.
    """
    if user is None or not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_active', False):
        return False
    return True


def check_can_start_attempt(user: Any, assessment: Any) -> None:
    """
    Raises AssessmentPermissionDeniedError if user cannot start an attempt.
    """
    check_authenticated_and_active(user)
    if not can_start_attempt(user, assessment):
        raise AssessmentPermissionDeniedError(
            "You do not have permission to attempt this assessment."
        )


def can_access_attempt(user: Any, attempt: Any) -> bool:
    """
    Evaluates whether a user can access, navigate, or submit answers for an attempt.
    Allowed for the candidate owner or staff/superusers.
    """
    if user is None or not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_active', False):
        return False

    if getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False):
        return True

    attempt_user_id = getattr(attempt, 'user_id', None)
    return attempt_user_id == user.pk


def check_can_access_attempt(user: Any, attempt: Any) -> None:
    """
    Raises AssessmentPermissionDeniedError if user cannot access the attempt.
    """
    check_authenticated_and_active(user)
    if not can_access_attempt(user, attempt):
        raise AssessmentPermissionDeniedError(
            "You do not have permission to access this assessment attempt."
        )


def can_cancel_attempt(user: Any, attempt: Any) -> bool:
    """
    Evaluates whether a user can cancel an in-progress attempt.
    Allowed for candidate owner or staff/superusers.
    """
    return can_access_attempt(user, attempt)


def check_can_cancel_attempt(user: Any, attempt: Any) -> None:
    """
    Raises AssessmentPermissionDeniedError if user cannot cancel the attempt.
    """
    check_authenticated_and_active(user)
    if not can_cancel_attempt(user, attempt):
        raise AssessmentPermissionDeniedError(
            "You do not have permission to cancel this assessment attempt."
        )

