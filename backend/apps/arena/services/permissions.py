"""
Reusable authorization checks for ZENTIQ Arena domain services.
Enforces permissions based strictly on Django's native authentication model,
standard RBAC permissions, and author ownership.
"""
from typing import Any, Optional

from apps.arena.models import QuestionVersion
from .exceptions import QuestionPermissionDeniedError, SelfPublicationNotAllowedError


def can_modify_draft(user: Optional[Any], question_version: QuestionVersion) -> bool:
    """
    Evaluates whether a user is authorized to edit a draft QuestionVersion and its composition.

    Rules:
    - User must be authenticated and active.
    - Superuser: Granted administrative editing privileges (user.is_superuser).
    - Author: The version author (question_version.created_by_id == user.pk) or parent question author
      (if question_version.created_by_id is None and question_version.question.created_by_id == user.pk).
    - User with explicit permission: Requires the Django model permission 'arena.change_questionversion'.
    - Crucially: is_staff alone DOES NOT grant draft modification without the explicit permission.
    - Separation of duties: Editing permissions never grant publication privileges.
    """
    if not user or not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_active', False):
        return False

    if getattr(user, 'is_superuser', False):
        return True

    # Author of the version
    if question_version.created_by_id and question_version.created_by_id == user.pk:
        return True

    # Author of the parent question if version author is not set
    if not question_version.created_by_id:
        question = getattr(question_version, 'question', None)
        if question and question.created_by_id == user.pk:
            return True

    # Explicit Django model permission check
    if user.has_perm('arena.change_questionversion'):
        return True

    # is_staff alone does NOT grant modification permission
    return False


def check_can_modify_draft(user: Optional[Any], question_version: QuestionVersion) -> None:
    """
    Validates that the user is authorized to modify the draft question version.
    Raises QuestionPermissionDeniedError if authorization fails.
    """
    if not can_modify_draft(user, question_version):
        raise QuestionPermissionDeniedError(
            "User is not authorized to modify this draft question version."
        )


def can_view_evaluation_data(user: Optional[Any], question_version: QuestionVersion) -> bool:
    """
    Evaluates whether a user is authorized to inspect confidential evaluation criteria and answer keys.

    Rules:
    - User must be authenticated and active.
    - Superuser: Granted access (user.is_superuser).
    - Author: The version author (question_version.created_by_id == user.pk) or parent question author.
    - User with explicit permission: Requires 'arena.view_questionevaluationdata'.
    - is_staff alone DOES NOT grant access to confidential evaluation data without permission.
    """
    if not user or not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_active', False):
        return False

    if getattr(user, 'is_superuser', False):
        return True

    # Author of the version
    if question_version.created_by_id and question_version.created_by_id == user.pk:
        return True

    # Author of the parent question if version author is not set
    if not question_version.created_by_id:
        question = getattr(question_version, 'question', None)
        if question and question.created_by_id == user.pk:
            return True

    # Explicit Django model permission check
    if user.has_perm('arena.view_questionevaluationdata'):
        return True

    return False


def check_can_view_evaluation_data(user: Optional[Any], question_version: QuestionVersion) -> None:
    """
    Validates that the user is authorized to view confidential evaluation data.
    Raises QuestionPermissionDeniedError if authorization fails.
    """
    if not can_view_evaluation_data(user, question_version):
        raise QuestionPermissionDeniedError(
            "User is not authorized to view confidential evaluation data."
        )


def check_authenticated_and_active(user: Optional[Any]) -> None:
    """
    Validates that the user is authenticated and active.
    Raises QuestionPermissionDeniedError if the check fails.
    Executed before any permission or superuser evaluation.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        raise QuestionPermissionDeniedError("Authentication required.")
    if not getattr(user, 'is_active', False):
        raise QuestionPermissionDeniedError("User account is inactive.")


def can_create_question(user: Optional[Any]) -> bool:
    """
    Evaluates whether a user is authorized to create a canonical Question series.

    Rules:
    - User must be authenticated and active.
    - Superuser: Granted creation privileges (user.is_superuser).
    - User with explicit permission: Requires 'arena.add_question'.
    - is_staff alone DOES NOT grant creation privileges.
    """
    if not user or not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_active', False):
        return False

    if getattr(user, 'is_superuser', False):
        return True

    if user.has_perm('arena.add_question'):
        return True

    return False


def check_can_create_question(user: Optional[Any]) -> None:
    """
    Validates that the user is authorized to create questions.
    Raises QuestionPermissionDeniedError if authorization fails.
    """
    check_authenticated_and_active(user)
    if not can_create_question(user):
        raise QuestionPermissionDeniedError(
            "User lacks required permission 'arena.add_question' to create questions."
        )


def can_view_question(user: Optional[Any], question: Any) -> bool:
    """
    Evaluates whether a user is authorized to inspect a canonical Question series.

    Rules:
    - User must be authenticated and active.
    - Superuser: Granted viewing privileges (user.is_superuser).
    - Author: The question author (question.created_by_id == user.pk).
    - User with explicit permission: Requires 'arena.view_question'.
    - is_staff alone DOES NOT grant viewing privileges.
    """
    if not user or not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_active', False):
        return False

    if getattr(user, 'is_superuser', False):
        return True

    if question and getattr(question, 'created_by_id', None) and question.created_by_id == user.pk:
        return True

    if user.has_perm('arena.view_question'):
        return True

    return False


def check_can_view_question(user: Optional[Any], question: Any) -> None:
    """
    Validates that the user is authorized to view the question.
    Raises QuestionPermissionDeniedError if authorization fails.
    """
    check_authenticated_and_active(user)
    if not can_view_question(user, question):
        raise QuestionPermissionDeniedError("User is not authorized to view this question.")


def can_deprecate_question(user: Optional[Any], question: Any) -> bool:
    """
    Evaluates whether a user is authorized to deprecate a canonical Question series.

    Rules:
    - User must be authenticated and active.
    - Superuser: Granted deprecation privileges (user.is_superuser).
    - User with explicit permission: Requires 'arena.change_question'.
    - Crucially: Question author ownership ALONE does NOT grant deprecation privileges.
    - is_staff alone DOES NOT grant deprecation privileges.
    """
    if not user or not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_active', False):
        return False

    if getattr(user, 'is_superuser', False):
        return True

    if user.has_perm('arena.change_question'):
        return True

    return False


def check_can_deprecate_question(user: Optional[Any], question: Any) -> None:
    """
    Validates that the user is authorized to deprecate the question.
    Raises QuestionPermissionDeniedError if authorization fails.
    """
    check_authenticated_and_active(user)
    if not can_deprecate_question(user, question):
        raise QuestionPermissionDeniedError(
            "User lacks required permission 'arena.change_question' to deprecate questions."
        )


def can_create_draft_version(user: Optional[Any]) -> bool:
    """
    Evaluates whether a user is authorized to create a new draft QuestionVersion.
    Requires 'arena.add_questionversion' or active superuser.
    """
    if not user or not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_active', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    return user.has_perm('arena.add_questionversion')


def check_can_create_draft_version(user: Optional[Any]) -> None:
    """Validates that user can create question drafts."""
    check_authenticated_and_active(user)
    if not can_create_draft_version(user):
        raise QuestionPermissionDeniedError(
            "User lacks required permission 'arena.add_questionversion' to create question drafts."
        )


def can_update_draft_version(user: Optional[Any], version: QuestionVersion) -> bool:
    """
    Evaluates whether a user is authorized to edit a draft QuestionVersion.
    Requires version author (created_by_id == user.pk), 'arena.change_questionversion', or superuser.
    Parent Question ownership alone does not grant editing rights.
    """
    if not user or not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_active', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    if version.created_by_id and version.created_by_id == user.pk:
        return True
    return user.has_perm('arena.change_questionversion')


def check_can_update_draft_version(user: Optional[Any], version: QuestionVersion) -> None:
    """Validates that user can update the question draft."""
    check_authenticated_and_active(user)
    if not can_update_draft_version(user, version):
        raise QuestionPermissionDeniedError("User is not authorized to edit this question draft.")


def can_submit_for_review(user: Optional[Any], version: QuestionVersion) -> bool:
    """Evaluates whether a user is authorized to submit a draft QuestionVersion for review."""
    return can_update_draft_version(user, version)


def check_can_submit_for_review(user: Optional[Any], version: QuestionVersion) -> None:
    """Validates that user can submit the draft for review."""
    check_authenticated_and_active(user)
    if not can_submit_for_review(user, version):
        raise QuestionPermissionDeniedError("User is not authorized to submit this question draft for review.")


def is_version_author(user: Optional[Any], version: QuestionVersion) -> bool:
    """Returns True if the user is the author of the version or parent question if unset."""
    if not user:
        return False
    if version.created_by_id and version.created_by_id == user.pk:
        return True
    if not version.created_by_id:
        question = getattr(version, 'question', None)
        if question and question.created_by_id == user.pk:
            return True
    return False


def can_publish_version(user: Optional[Any], version: QuestionVersion) -> bool:
    """
    Evaluates whether a user is authorized to publish a QuestionVersion.
    Strict separation: Authors (even superusers) can NEVER publish their own versions.
    Requires 'arena.publish_questionversion' or non-author superuser.
    """
    if not user or not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_active', False):
        return False
    if is_version_author(user, version):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    return user.has_perm('arena.publish_questionversion')


def check_can_publish_version(user: Optional[Any], version: QuestionVersion) -> None:
    """Validates that user can publish the question version, enforcing separation of duties."""
    check_authenticated_and_active(user)
    if is_version_author(user, version):
        raise SelfPublicationNotAllowedError(
            "Authors are strictly prohibited from publishing their own question versions."
        )
    if not can_publish_version(user, version):
        raise QuestionPermissionDeniedError(
            "User lacks required permission 'arena.publish_questionversion' to publish question versions."
        )


def can_return_to_draft(user: Optional[Any], version: QuestionVersion) -> bool:
    """
    Evaluates whether a reviewer/administrator is authorized to reject an in-review version to draft.
    Requires 'arena.publish_questionversion', 'arena.change_questionversion', or non-author superuser.
    Authors cannot reject their own submissions via this path.
    """
    if not user or not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_active', False):
        return False
    if is_version_author(user, version):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    return user.has_perm('arena.publish_questionversion') or user.has_perm('arena.change_questionversion')


def check_can_return_to_draft(user: Optional[Any], version: QuestionVersion) -> None:
    """Validates reviewer return-to-draft authorization."""
    check_authenticated_and_active(user)
    if is_version_author(user, version):
        raise QuestionPermissionDeniedError(
            "Authors cannot reject their own submissions; use withdraw_from_review() instead."
        )
    if not can_return_to_draft(user, version):
        raise QuestionPermissionDeniedError(
            "User is not authorized to return this question version to draft."
        )


def check_can_withdraw_from_review(user: Optional[Any], version: QuestionVersion) -> None:
    """
    Validates author withdrawal authorization.
    Strictly restricted to the version author. Non-author superusers are rejected.
    """
    check_authenticated_and_active(user)
    if not version.created_by_id or version.created_by_id != user.pk:
        raise QuestionPermissionDeniedError(
            "Only the author of the question version may withdraw it from review."
        )


def can_archive_or_deprecate_version(user: Optional[Any]) -> bool:
    """
    Evaluates administrative authorization to archive or deprecate a QuestionVersion.
    Requires 'arena.change_questionversion' or active superuser. Author ownership alone is insufficient.
    """
    if not user or not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_active', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    return user.has_perm('arena.change_questionversion')


def check_can_archive_or_deprecate_version(user: Optional[Any]) -> None:
    """Validates administrative authorization to archive or deprecate a version."""
    check_authenticated_and_active(user)
    if not can_archive_or_deprecate_version(user):
        raise QuestionPermissionDeniedError(
            "User lacks required permission 'arena.change_questionversion' to archive or deprecate question versions."
        )


