"""
Domain-specific service exceptions for ZENTIQ Arena.
Provides a structured exception hierarchy for application and service layers.
"""
from typing import Any, Optional


class ArenaServiceError(Exception):
    """Base exception for all Arena domain service errors."""
    code = 'arena_error'
    default_message = "An error occurred in the arena domain."

    def __init__(self, message: Optional[str] = None, details: Optional[dict[str, Any]] = None):
        self.message = message or self.default_message
        self.details = details or {}
        super().__init__(self.message)


class QuestionNotFoundError(ArenaServiceError):
    """Raised when a requested Question entity does not exist."""
    code = 'question_not_found'
    default_message = "The requested question was not found."


class QuestionVersionNotFoundError(ArenaServiceError):
    """Raised when a requested QuestionVersion entity does not exist."""
    code = 'question_version_not_found'
    default_message = "The requested question version was not found."


class CompetencyNotFoundError(ArenaServiceError):
    """Raised when a requested Competency entity does not exist or has been deleted."""
    code = 'competency_not_found'
    default_message = "The requested competency was not found."


class TagNotFoundError(ArenaServiceError):
    """Raised when one or more requested Tag entities do not exist."""
    code = 'tag_not_found'
    default_message = "One or more requested tags were not found."


class InvalidLifecycleTransitionError(ArenaServiceError):
    """Raised when a lifecycle status transition violates the state machine."""
    code = 'invalid_lifecycle_transition'
    default_message = "The requested lifecycle transition is invalid."


class QuestionPermissionDeniedError(ArenaServiceError):
    """Raised when a user lacks required permissions or ownership to mutate a question."""
    code = 'permission_denied'
    default_message = "You do not have permission to perform this action on the question."


class QuestionImmutabilityError(ArenaServiceError):
    """Raised when attempting to modify a question version or sub-entity that is immutable."""
    code = 'version_immutable'
    default_message = "The question version is immutable in its current status."


class EvaluationDataMissingError(ArenaServiceError):
    """Raised when evaluation data is expected but has not been configured."""
    code = 'evaluation_data_missing'
    default_message = "No evaluation data has been configured for this question version."


class CompetencyMappingInvalidError(ArenaServiceError):
    """Raised when competency mappings violate uniqueness, primary, or aggregate weight rules."""
    code = 'competency_mapping_invalid'
    default_message = "The competency mapping is invalid."


class ConcurrencyConflictError(ArenaServiceError):
    """Raised when an optimistic concurrency check or lock acquisition fails."""
    code = 'concurrency_conflict'
    default_message = "A concurrent modification conflict occurred."


class InactiveCompetencyError(ArenaServiceError):
    """Raised when attempting to create a question referencing an inactive Competency."""
    code = 'inactive_competency'
    default_message = "The referenced competency is inactive."


class QuestionValidationError(ArenaServiceError):
    """Raised when model full_clean() validation fails during question creation."""
    code = 'question_validation_error'
    default_message = "The question data failed validation."


class QuestionCodeGenerationError(ArenaServiceError):
    """Raised when unique canonical code generation exceeds collision retry limit."""
    code = 'code_generation_failed'
    default_message = "Failed to generate a unique question code after maximum retries."


class QuestionAlreadyDeprecatedError(ArenaServiceError):
    """Raised when deprecate_question(strict=True) encounters an already deprecated question."""
    code = 'question_already_deprecated'
    default_message = "The question is already deprecated."


class QuestionDeprecatedError(ArenaServiceError):
    """Raised when an assessment selection attempts to retrieve a deprecated question."""
    code = 'question_deprecated'
    default_message = "The requested question is deprecated and cannot be used in assessments."


class QuestionNoActiveVersionError(ArenaServiceError):
    """Raised when an assessment selection attempts to retrieve a question with no active version."""
    code = 'question_no_active_version'
    default_message = "The question does not have an active published version."


class ActiveVersionIntegrityError(ArenaServiceError):
    """Raised when active version fails integrity checks (status not PUBLISHED or parent mismatch)."""
    code = 'active_version_integrity_error'
    default_message = "The active version violates domain integrity constraints."


class SelfPublicationNotAllowedError(QuestionPermissionDeniedError):
    """Raised when an author attempts to publish their own question version."""
    code = 'self_publication_not_allowed'
    default_message = "Authors are strictly prohibited from publishing their own question versions."


class IncompleteQuestionVersionError(ArenaServiceError):
    """Raised when a question version fails completeness validation upon submission or publication."""
    code = 'incomplete_question_version'
    default_message = "The question version does not meet completeness requirements for review or publication."


class SourceVersionMismatchError(ArenaServiceError):
    """Raised when an explicit source_version_id does not belong to the requested parent Question."""
    code = 'source_version_mismatch'
    default_message = "The specified source version does not belong to the target question series."


class MissingRequiredDraftFieldsError(QuestionValidationError):
    """Raised when creating a draft without a source and mandatory canonical fields are missing."""
    code = 'missing_required_draft_fields'
    default_message = "Draft creation without a source requires title, prompt, question_type, and primary_competency."


class RejectionReasonRequiredError(QuestionValidationError):
    """Raised when a reviewer returns a version to draft without providing a non-empty rejection reason."""
    code = 'rejection_reason_required'
    default_message = "A non-empty rejection reason is required to return a version to draft."


