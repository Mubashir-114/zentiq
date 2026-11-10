"""
Assessment Execution Services for ZENTIQ (Milestone 4A - Phase 2D.2).
Authoritative domain service layer governing composition, attempts, answers,
navigation, and lifecycle.
"""
from .answer_service import (
    AssessmentAnswerService,
    validate_answer_payload_for_type,
)
from .attempt_service import (
    AssessmentAttemptService,
    build_attempt_summary,
)
from .composition_service import (
    AssessmentCompositionService,
    lock_assessment_and_version,
    normalize_question_weight,
)
from .concurrency import (
    DEFAULT_INITIAL_DELAY_SECONDS,
    DEFAULT_MAX_DEADLOCK_RETRIES,
    is_deadlock_exception,
    is_lock_timeout_exception,
    with_deadlock_retry,
)
from .dto import (
    AttemptSummaryDTO,
    CandidateQuestionDTO,
    sanitize_candidate_content_payload,
)
from .exceptions import (
    ActiveAttemptExistsError,
    AnswerValidationError,
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
)
from .navigation_service import (
    AssessmentNavigationService,
    build_candidate_question_dto,
)
from .permissions import (
    can_access_attempt,
    can_cancel_attempt,
    can_manage_assessment,
    can_start_attempt,
    check_authenticated_and_active,
    check_can_access_attempt,
    check_can_cancel_attempt,
    check_can_manage_assessment,
    check_can_start_attempt,
)

__all__ = [
    # Services
    'AssessmentCompositionService',
    'AssessmentAttemptService',
    'AssessmentAnswerService',
    'AssessmentNavigationService',
    # DTOs & Helpers
    'CandidateQuestionDTO',
    'AttemptSummaryDTO',
    'sanitize_candidate_content_payload',
    'build_attempt_summary',
    'build_candidate_question_dto',
    'normalize_question_weight',
    'lock_assessment_and_version',
    'validate_answer_payload_for_type',
    # Concurrency
    'with_deadlock_retry',
    'is_deadlock_exception',
    'is_lock_timeout_exception',
    'DEFAULT_MAX_DEADLOCK_RETRIES',
    'DEFAULT_INITIAL_DELAY_SECONDS',
    # Permissions
    'can_manage_assessment',
    'check_can_manage_assessment',
    'can_start_attempt',
    'check_can_start_attempt',
    'can_access_attempt',
    'check_can_access_attempt',
    'can_cancel_attempt',
    'check_can_cancel_attempt',
    'check_authenticated_and_active',
    # Exceptions
    'AssessmentServiceError',
    'AssessmentNotFoundError',
    'AssessmentVersionNotFoundError',
    'AssessmentDeprecatedError',
    'AssessmentNoActiveVersionError',
    'AssessmentVersionImmutabilityError',
    'InvalidAssessmentStateError',
    'InvalidVersionTransitionError',
    'DuplicateCanonicalQuestionError',
    'InvalidQuestionOrderError',
    'InvalidQuestionWeightError',
    'QuestionNotPublishedError',
    'QuestionDeprecatedError',
    'IncompleteAssessmentVersionError',
    'AttemptNotFoundError',
    'ActiveAttemptExistsError',
    'AttemptExpiredError',
    'AttemptTerminalError',
    'BacktrackingNotAllowedError',
    'InvalidNavigationError',
    'AnswerValidationError',
    'AssessmentPermissionDeniedError',
    'ConcurrencyConflictError',
    'LockTimeoutError',
    'AssessmentValidationError',
]

