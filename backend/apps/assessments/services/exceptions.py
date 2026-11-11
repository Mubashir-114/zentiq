"""
Domain-specific service exceptions for ZENTIQ Assessments (Milestone 4A - Phase 2D.2).
Provides a structured exception hierarchy for application and service layers.
"""
from typing import Any, Optional


class AssessmentServiceError(Exception):
    """Base exception for all Assessment domain service errors."""
    code = 'assessment_error'
    default_message = "An error occurred in the assessment service."

    def __init__(self, message: Optional[str] = None, details: Optional[dict[str, Any]] = None):
        self.message = message or self.default_message
        self.details = details or {}
        super().__init__(self.message)


class AssessmentNotFoundError(AssessmentServiceError):
    """Raised when a requested Assessment entity does not exist."""
    code = 'assessment_not_found'
    default_message = "The requested assessment was not found."


class AssessmentVersionNotFoundError(AssessmentServiceError):
    """Raised when a requested AssessmentVersion entity does not exist."""
    code = 'assessment_version_not_found'
    default_message = "The requested assessment version was not found."


class AssessmentDeprecatedError(AssessmentServiceError):
    """Raised when an operation targets a deprecated Assessment."""
    code = 'assessment_deprecated'
    default_message = "The assessment is deprecated and cannot accept new attempts or revisions."


class AssessmentNoActiveVersionError(AssessmentServiceError):
    """Raised when attempting to start an attempt on an assessment with no active published version."""
    code = 'no_active_version'
    default_message = "The assessment does not have an active published version."


class AssessmentVersionImmutabilityError(AssessmentServiceError):
    """Raised when attempting to modify a published or archived AssessmentVersion."""
    code = 'version_immutable'
    default_message = "Published or archived assessment versions cannot be modified."


class InvalidAssessmentStateError(AssessmentServiceError):
    """Raised when an entity is in an invalid state for the requested operation."""
    code = 'invalid_state'
    default_message = "The assessment or attempt is not in a valid state for this operation."


class InvalidVersionTransitionError(AssessmentServiceError):
    """Raised when a lifecycle status transition violates the state machine."""
    code = 'invalid_lifecycle_transition'
    default_message = "The requested assessment version lifecycle transition is invalid."


class DuplicateCanonicalQuestionError(AssessmentServiceError):
    """Raised when attempting to add a QuestionVersion whose canonical Question is already in the assessment."""
    code = 'duplicate_canonical_question'
    default_message = "Another version of this canonical Question is already included in this assessment version."


class InvalidQuestionOrderError(AssessmentServiceError):
    """Raised when question ordering is invalid (e.g. gaps, non-positive, or duplicates)."""
    code = 'invalid_question_order'
    default_message = "The question order index is invalid."


class InvalidQuestionWeightError(AssessmentServiceError):
    """Raised when a question weight is non-positive or malformed."""
    code = 'invalid_question_weight'
    default_message = "The question weight must be a positive decimal."


class QuestionNotPublishedError(AssessmentServiceError):
    """Raised when attempting to add a QuestionVersion that is not in PUBLISHED status."""
    code = 'question_not_published'
    default_message = "Only published QuestionVersions can be included in an assessment."


class QuestionDeprecatedError(AssessmentServiceError):
    """Raised when attempting to include a QuestionVersion whose parent Question is deprecated."""
    code = 'question_deprecated'
    default_message = "The parent Question is deprecated and cannot be included in an assessment."


class IncompleteAssessmentVersionError(AssessmentServiceError):
    """Raised when an AssessmentVersion fails completeness validation prior to publication."""
    code = 'incomplete_version'
    default_message = "The assessment version does not meet completeness requirements for publication."


class AttemptNotFoundError(AssessmentServiceError):
    """Raised when a requested AssessmentAttempt entity does not exist."""
    code = 'attempt_not_found'
    default_message = "The requested assessment attempt was not found."


class ActiveAttemptExistsError(AssessmentServiceError):
    """Raised when a user attempts to start a new attempt while an active attempt is already in progress."""
    code = 'active_attempt_exists'
    default_message = "An active assessment attempt is already in progress for this user and assessment."


class AttemptExpiredError(AssessmentServiceError):
    """Raised when an operation is attempted on an attempt whose deadline has passed."""
    code = 'attempt_expired'
    default_message = "The assessment attempt time limit has expired."


class AttemptTerminalError(AssessmentServiceError):
    """Raised when an operation is attempted on an attempt already in a terminal state."""
    code = 'attempt_terminal'
    default_message = "The assessment attempt has concluded and cannot be modified."


class BacktrackingNotAllowedError(AssessmentServiceError):
    """Raised when a candidate attempts backward navigation on an attempt with backtracking disabled."""
    code = 'backtracking_not_allowed'
    default_message = "Backtracking to previous questions is not permitted for this assessment."


class InvalidNavigationError(AssessmentServiceError):
    """Raised when a navigation target order index is out of bounds or skips unvisited questions."""
    code = 'invalid_navigation'
    default_message = "The navigation target is invalid."


class AnswerValidationError(AssessmentServiceError):
    """Raised when submitted answer payload does not match expected schema or choices for the question type."""
    code = 'invalid_answer_payload'
    default_message = "The submitted answer payload is invalid."


class AssessmentPermissionDeniedError(AssessmentServiceError):
    """Raised when a user lacks required permissions for an assessment or attempt action."""
    code = 'permission_denied'
    default_message = "You do not have permission to perform this action."


class ConcurrencyConflictError(AssessmentServiceError):
    """Raised when a concurrency conflict or lock acquisition failure occurs."""
    code = 'concurrency_conflict'
    default_message = "A concurrent modification conflict occurred."


class LockTimeoutError(AssessmentServiceError):
    """Raised when a database lock wait timeout occurs (MySQL 1205) to fail fast with 503."""
    code = 'lock_timeout'
    default_message = "A database lock wait timeout occurred. Please retry shortly."


class AssessmentValidationError(AssessmentServiceError):
    """Raised when general validation fails on assessment operations."""
    code = 'validation_error'
    default_message = "The assessment operation failed validation."


# ---------------------------------------------------------------------------
# Phase 2E.2 — Scoring & Evaluation foundation
# ---------------------------------------------------------------------------

class ResultRevisionConflictError(AssessmentServiceError):
    """Raised when a result revision request is stale or competes with another writer."""
    code = 'result_revision_conflict'
    default_message = "The result revision request conflicts with the current authoritative result."


class ResultRevisionIntegrityError(AssessmentServiceError):
    """Raised when a revision/head relationship would violate attempt ownership."""
    code = 'result_revision_integrity_error'
    default_message = "The result revision violates attempt integrity constraints."


class AttemptRedactedError(AssessmentServiceError):
    """Raised when an attempt with redacted answer content is submitted for evaluation."""
    code = 'attempt_redacted'
    default_message = "This attempt contains redacted answer content and cannot be evaluated or regraded."


class TerminalSnapshotConflictError(AssessmentServiceError):
    """Raised when a terminal snapshot already exists with a different terminal status."""
    code = 'terminal_snapshot_conflict'
    default_message = "A conflicting terminal policy snapshot already exists for this attempt."


class EvaluationConfigurationError(AssessmentServiceError):
    """Raised by strict evaluation-configuration validation (publication gate)."""
    code = 'evaluation_configuration_error'
    default_message = "The question evaluation configuration is incomplete or invalid."

