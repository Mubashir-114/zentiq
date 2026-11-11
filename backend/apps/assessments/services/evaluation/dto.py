"""
Evaluation DTOs and vocabulary for ZENTIQ Phase 2E.2.

Pure data structures only: no Django imports, no database access, no mutation.
The three orthogonal axes of an answer are modelled explicitly:

- answer presence : PRESENT / ABSENT (a fact about the candidate's submission)
- outcome         : what the grading pipeline concluded (six approved values)
- disposition     : how the conclusion enters the arithmetic (SCORED / EXCLUDED /
                    UNDECIDED)
"""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

# --- Answer presence -------------------------------------------------------
ANSWER_PRESENT = 'PRESENT'
ANSWER_ABSENT = 'ABSENT'

ABSENCE_SKIPPED = 'SKIPPED'
ABSENCE_NOT_REACHED = 'NOT_REACHED'
ABSENCE_EMPTY_SUBMISSION = 'EMPTY_SUBMISSION'

# --- Outcomes --------------------------------------------------------------
OUTCOME_CORRECT = 'CORRECT'
OUTCOME_PARTIALLY_CORRECT = 'PARTIALLY_CORRECT'
OUTCOME_INCORRECT = 'INCORRECT'
OUTCOME_UNANSWERED = 'UNANSWERED'
OUTCOME_UNGRADED = 'UNGRADED'
OUTCOME_PENDING_MANUAL = 'PENDING_MANUAL'

# --- Dispositions ----------------------------------------------------------
DISPOSITION_SCORED = 'SCORED'
DISPOSITION_EXCLUDED = 'EXCLUDED'
DISPOSITION_UNDECIDED = 'UNDECIDED'

# --- Result / evaluation statuses ------------------------------------------
RESULT_PROVISIONAL = 'PROVISIONAL'
RESULT_FINAL = 'FINAL'

EVAL_COMPLETE = 'COMPLETE'
EVAL_AWAITING_MANUAL = 'AWAITING_MANUAL_GRADING'
EVAL_INCOMPLETE_COVERAGE = 'INCOMPLETE_COVERAGE'
EVAL_CONFIG_UNGRADABLE = 'CONFIGURATION_UNGRADABLE'

# --- Ungraded / excluded reasons -------------------------------------------
REASON_CONFIG_INVALID = 'CONFIG_INVALID'
REASON_CONFIG_UNVERIFIED = 'CONFIG_UNVERIFIED'
REASON_STRATEGY_UNSUPPORTED = 'STRATEGY_UNSUPPORTED'
REASON_MISSING_CORRECT_PAYLOAD = 'MISSING_CORRECT_PAYLOAD'
REASON_RUBRIC_SCHEMA_INVALID = 'RUBRIC_SCHEMA_INVALID'
REASON_EXECUTION_REQUIRED = 'EXECUTION_REQUIRED'
REASON_MANUAL_REQUIRED = 'MANUAL_REQUIRED'

EXCLUDED_POLICY_UNANSWERED = 'POLICY_UNANSWERED_EXCLUDED'
EXCLUDED_POLICY_QUESTION = 'POLICY_QUESTION_EXCLUDED'


@dataclass(frozen=True)
class QuestionEvaluationInput:
    """Everything the pure evaluator needs about one attempt question."""
    attempt_question_id: Any
    weight: Decimal
    question_type: str
    grading_strategy: str
    correct_payload: Any
    scoring_rubric: Any
    answer_payload: Optional[Any]
    answer_presence: str = ANSWER_ABSENT
    absence_reason: str = ''
    answer_redacted: bool = False


@dataclass(frozen=True)
class QuestionOutcome:
    """Immutable per-question conclusion, ready for persistence."""
    attempt_question_id: Any
    outcome: str
    disposition: str
    awarded_fraction: Optional[Decimal]
    awarded_points: Optional[Decimal]
    max_points: Decimal
    grading_strategy: str
    ungraded_reason: str = ''
    excluded_reason: str = ''
    answer_presence: str = ANSWER_ABSENT
    absence_reason: str = ''
    answer_payload_hash: str = ''
    answer_canonicalization_version: str = 'answer_canon_v1'
    evaluation_config_hash: str = ''
    details: dict = field(default_factory=dict)
