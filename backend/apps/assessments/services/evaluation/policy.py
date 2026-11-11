"""
Scoring policy and status derivation (Phase 2E.2).

Approved product decisions implemented here:
- D-03a: unanswered questions earn zero points and remain in the total assessment
  weight (they are SCORED at fraction 0, never EXCLUDED).
- D-03b: negative marking is disabled; no fraction below zero is representable.
- D-06: weights are Decimal(5,2), fractions Decimal(5,4), aggregates
  Decimal(12,6), scores Decimal(5,2) with ROUND_HALF_UP.

Exclusions: D-23 (whether exclusions are approvable at all) is unresolved, so
``ALLOW_APPROVED_EXCLUSIONS`` is False and any EXCLUDED outcome forces a
PROVISIONAL / INCOMPLETE_COVERAGE result. The derivation accepts an explicit
override so the approved-exclusion branch remains testable without changing the
default policy.
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from .dto import (
    DISPOSITION_EXCLUDED,
    DISPOSITION_SCORED,
    DISPOSITION_UNDECIDED,
    EVAL_AWAITING_MANUAL,
    EVAL_COMPLETE,
    EVAL_CONFIG_UNGRADABLE,
    EVAL_INCOMPLETE_COVERAGE,
    OUTCOME_CORRECT,
    OUTCOME_INCORRECT,
    OUTCOME_PARTIALLY_CORRECT,
    OUTCOME_PENDING_MANUAL,
    OUTCOME_UNANSWERED,
    OUTCOME_UNGRADED,
    RESULT_FINAL,
    RESULT_PROVISIONAL,
    QuestionOutcome,
)

SCORE_QUANTUM = Decimal('0.01')
ROUNDING_MODE = ROUND_HALF_UP
SIX_DP = Decimal('0.000001')
POLICY_VERSION = '2e2-policy-v1'
EVALUATOR_VERSION = '2e.2'

#: D-23 is unresolved: exclusions are not approvable yet.
ALLOW_APPROVED_EXCLUSIONS = False


@dataclass(frozen=True)
class EvaluationTotals:
    total_weight: Decimal
    graded_weight: Decimal
    excluded_weight: Decimal
    earned_weight: Decimal
    question_count: int
    answered_count: int
    correct_count: int
    incorrect_count: int
    partially_correct_count: int
    unanswered_count: int
    ungraded_count: int
    pending_manual_count: int
    status: str
    evaluation_status: str
    final_score: Decimal | None
    provisional_score: Decimal | None


def quantize_weight(value: Decimal) -> Decimal:
    """Normalizes a weight to the 6-decimal aggregate precision without loss."""
    return Decimal(value).quantize(SIX_DP)


def compute_score(earned_weight: Decimal, graded_weight: Decimal) -> Decimal | None:
    """
    Returns 100 * earned / graded rounded once to 2dp, or None when undefined.

    No floating point is used anywhere in the authoritative path.
    """
    if graded_weight is None or graded_weight <= 0:
        return None
    ratio = earned_weight / graded_weight
    return (ratio * Decimal('100')).quantize(SCORE_QUANTUM, rounding=ROUNDING_MODE)


def derive_totals(
    outcomes: Iterable[QuestionOutcome],
    *,
    allow_approved_exclusions: bool | None = None,
) -> EvaluationTotals:
    """
    Aggregates immutable per-question outcomes into the revision-level numbers
    and derives the result status / evaluation status using the frozen matrix.
    """
    exclusion_policy = (
        ALLOW_APPROVED_EXCLUSIONS
        if allow_approved_exclusions is None
        else allow_approved_exclusions
    )

    rows = list(outcomes)
    total_weight = Decimal('0')
    graded_weight = Decimal('0')
    excluded_weight = Decimal('0')
    earned_weight = Decimal('0')

    counts = {
        OUTCOME_CORRECT: 0,
        OUTCOME_INCORRECT: 0,
        OUTCOME_PARTIALLY_CORRECT: 0,
        OUTCOME_UNANSWERED: 0,
        OUTCOME_UNGRADED: 0,
        OUTCOME_PENDING_MANUAL: 0,
    }

    for row in rows:
        weight = quantize_weight(row.max_points)
        total_weight += weight
        counts[row.outcome] = counts.get(row.outcome, 0) + 1
        if row.disposition == DISPOSITION_SCORED:
            graded_weight += weight
            earned_weight += quantize_weight(row.awarded_points or Decimal('0'))
        elif row.disposition == DISPOSITION_EXCLUDED:
            excluded_weight += weight

    answered_count = len(rows) - counts[OUTCOME_UNANSWERED]
    score = compute_score(earned_weight, graded_weight)

    has_undecided = any(row.disposition == DISPOSITION_UNDECIDED for row in rows)

    if has_undecided:
        status = RESULT_PROVISIONAL
        if counts[OUTCOME_UNGRADED] > 0:
            evaluation_status = EVAL_CONFIG_UNGRADABLE
        else:
            evaluation_status = EVAL_AWAITING_MANUAL
    elif graded_weight == 0:
        status = RESULT_PROVISIONAL
        evaluation_status = EVAL_INCOMPLETE_COVERAGE
    elif excluded_weight > 0 and not exclusion_policy:
        status = RESULT_PROVISIONAL
        evaluation_status = EVAL_INCOMPLETE_COVERAGE
    else:
        status = RESULT_FINAL
        evaluation_status = EVAL_COMPLETE

    return EvaluationTotals(
        total_weight=total_weight,
        graded_weight=graded_weight,
        excluded_weight=excluded_weight,
        earned_weight=earned_weight,
        question_count=len(rows),
        answered_count=answered_count,
        correct_count=counts[OUTCOME_CORRECT],
        incorrect_count=counts[OUTCOME_INCORRECT],
        partially_correct_count=counts[OUTCOME_PARTIALLY_CORRECT],
        unanswered_count=counts[OUTCOME_UNANSWERED],
        ungraded_count=counts[OUTCOME_UNGRADED],
        pending_manual_count=counts[OUTCOME_PENDING_MANUAL],
        status=status,
        evaluation_status=evaluation_status,
        final_score=score if status == RESULT_FINAL else None,
        provisional_score=score if status == RESULT_PROVISIONAL else None,
    )


def resolve_terminal_flags(terminal_status: str) -> dict[str, bool]:
    """
    Independent eligibility flags for a terminal transition.

    D-02a (evaluate EXPIRED/CANCELLED), D-02b (mastery eligibility) and
    D-02c / D-11 (XP eligibility) are unresolved, so only SUBMITTED evaluation is
    enabled and mastery/XP eligibility remain False. The flags are recorded on the
    immutable terminal snapshot; enabling them later requires a new policy version.
    """
    return {
        'evaluate_eligible': terminal_status == 'SUBMITTED',
        'mastery_eligible': False,
        'xp_eligible': False,
    }
