"""
Pure per-question evaluator (Phase 2E.2).

``evaluate_question`` is deterministic and side-effect free: identical
``QuestionEvaluationInput`` always yields an identical ``QuestionOutcome``.

Failure taxonomy:
- class A (expected ungradable configuration) -> ``UNGRADED`` / ``UNDECIDED``
  with an ``ungraded_reason``; never an exception.
- pending manual -> ``PENDING_MANUAL`` / ``UNDECIDED``.
- any unexpected programming error is *not* caught here; it propagates and the
  caller's transaction rolls back.
"""
from decimal import Decimal

from .canonical import (
    CANONICALIZATION_VERSION,
    CanonicalizationError,
    answer_payload_hash,
    evaluation_config_hash,
)
from .dto import (
    ANSWER_ABSENT,
    ANSWER_PRESENT,
    DISPOSITION_EXCLUDED,
    DISPOSITION_SCORED,
    DISPOSITION_UNDECIDED,
    OUTCOME_PENDING_MANUAL,
    OUTCOME_UNANSWERED,
    OUTCOME_UNGRADED,
    REASON_CONFIG_INVALID,
    REASON_STRATEGY_UNSUPPORTED,
    QuestionEvaluationInput,
    QuestionOutcome,
)
from .policy import EVALUATOR_VERSION, quantize_weight
from .strategies import UngradableConfigurationError, get_strategy


def _max_points(weight: Decimal) -> Decimal:
    return quantize_weight(weight)


def _ungraded(inp: QuestionEvaluationInput, reason: str, message: str = '') -> QuestionOutcome:
    return QuestionOutcome(
        attempt_question_id=inp.attempt_question_id,
        outcome=OUTCOME_UNGRADED,
        disposition=DISPOSITION_UNDECIDED,
        awarded_fraction=None,
        awarded_points=None,
        max_points=_max_points(inp.weight),
        grading_strategy=inp.grading_strategy,
        ungraded_reason=reason,
        answer_presence=inp.answer_presence,
        absence_reason=inp.absence_reason,
        answer_canonicalization_version=CANONICALIZATION_VERSION,
        details={'message': message} if message else {},
    )


def _pending_manual(inp: QuestionEvaluationInput, reason: str) -> QuestionOutcome:
    return QuestionOutcome(
        attempt_question_id=inp.attempt_question_id,
        outcome=OUTCOME_PENDING_MANUAL,
        disposition=DISPOSITION_UNDECIDED,
        awarded_fraction=None,
        awarded_points=None,
        max_points=_max_points(inp.weight),
        grading_strategy=inp.grading_strategy,
        ungraded_reason=reason,
        answer_presence=inp.answer_presence,
        absence_reason=inp.absence_reason,
        answer_canonicalization_version=CANONICALIZATION_VERSION,
    )


def evaluate_question(inp: QuestionEvaluationInput) -> QuestionOutcome:
    max_points = _max_points(inp.weight)

    # Redacted content can never be graded (defence in depth; the service refuses first).
    if inp.answer_redacted:
        return _ungraded(inp, REASON_CONFIG_INVALID, 'Answer content has been redacted.')

    # Answer absence is a decided fact: UNANSWERED, scored at zero (D-03a).
    if inp.answer_presence != ANSWER_PRESENT or inp.answer_payload in (None, {}, []):
        return QuestionOutcome(
            attempt_question_id=inp.attempt_question_id,
            outcome=OUTCOME_UNANSWERED,
            disposition=DISPOSITION_SCORED,
            awarded_fraction=Decimal('0.0000'),
            awarded_points=Decimal('0.000000'),
            max_points=max_points,
            grading_strategy=inp.grading_strategy,
            answer_presence=inp.answer_presence or ANSWER_ABSENT,
            absence_reason=inp.absence_reason,
            answer_canonicalization_version=CANONICALIZATION_VERSION,
        )

    try:
        payload_hash = answer_payload_hash(inp.answer_payload)
    except CanonicalizationError as exc:
        return _ungraded(inp, REASON_CONFIG_INVALID, str(exc))

    config_hash = ''
    try:
        config_hash = evaluation_config_hash(
            inp.grading_strategy,
            inp.correct_payload,
            inp.scoring_rubric,
            EVALUATOR_VERSION,
        )
    except CanonicalizationError:
        config_hash = ''

    try:
        decision = get_strategy(inp.grading_strategy)(
            inp.question_type,
            inp.answer_payload,
            inp.correct_payload,
            inp.scoring_rubric,
        )
    except UngradableConfigurationError as exc:
        if exc.reason == REASON_STRATEGY_UNSUPPORTED:
            return _ungraded(inp, REASON_STRATEGY_UNSUPPORTED, exc.message)
        return _ungraded(inp, exc.reason, exc.message)

    if decision.outcome == OUTCOME_PENDING_MANUAL:
        return QuestionOutcome(
            attempt_question_id=inp.attempt_question_id,
            outcome=OUTCOME_PENDING_MANUAL,
            disposition=DISPOSITION_UNDECIDED,
            awarded_fraction=None,
            awarded_points=None,
            max_points=max_points,
            grading_strategy=inp.grading_strategy,
            ungraded_reason=decision.ungraded_reason or 'MANUAL_REQUIRED',
            answer_presence=inp.answer_presence,
            absence_reason=inp.absence_reason,
            answer_payload_hash=payload_hash,
            evaluation_config_hash=config_hash,
            details=dict(decision.details),
        )

    if decision.fraction is None:
        # A strategy that returns neither a fraction nor PENDING_MANUAL is a bug.
        raise ValueError(
            f"Strategy '{inp.grading_strategy}' returned no fraction for a decided outcome."
        )

    fraction = Decimal(decision.fraction).quantize(Decimal('0.0001'))
    if fraction < 0 or fraction > 1:
        raise ValueError(f"Strategy '{inp.grading_strategy}' produced an out-of-range fraction.")

    # D-03b: negative marking is disabled; fractions are never below zero.
    awarded_points = quantize_weight(max_points * fraction)

    disposition = DISPOSITION_SCORED
    excluded_reason = decision.excluded_reason

    # An UNANSWERED outcome can only be EXCLUDED under an approved exclusion policy,
    # which is not enabled in this milestone; the evaluator never emits EXCLUDED.
    if excluded_reason:
        disposition = DISPOSITION_EXCLUDED

    return QuestionOutcome(
        attempt_question_id=inp.attempt_question_id,
        outcome=decision.outcome,
        disposition=disposition,
        awarded_fraction=fraction,
        awarded_points=awarded_points,
        max_points=max_points,
        grading_strategy=inp.grading_strategy,
        excluded_reason=excluded_reason,
        answer_presence=inp.answer_presence,
        absence_reason=inp.absence_reason,
        answer_payload_hash=payload_hash,
        answer_canonicalization_version=CANONICALIZATION_VERSION,
        evaluation_config_hash=config_hash,
        details=dict(decision.details),
    )
