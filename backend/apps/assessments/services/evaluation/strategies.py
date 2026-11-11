"""
Deterministic grading strategies for Phase 2E.2.

Each strategy is a pure function of (question_type, answer_payload,
correct_payload, scoring_rubric). Strategies never touch the database and never
mutate their inputs.

Scope notes (unresolved product decisions are NOT invented here):
- SET_MATCH is all-or-nothing because partial-credit rules are unresolved (D-04).
- NUMERIC_TOLERANCE requires an explicitly configured absolute tolerance; no
  default tolerance exists (D-07 unresolved). Relative tolerance is rejected.
- NORMALIZED_STRING is disabled because the normalization pipeline is unresolved
  (D-08).
- REGEX_MATCH is disabled (D-17b); regex compilation alone is not sufficient
  ReDoS protection.
- STDOUT_MATCH compares textual output only. ``source_code`` answers require
  execution or manual grading and resolve to PENDING_MANUAL (D-15 unresolved).
"""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Optional

from .dto import (
    OUTCOME_CORRECT,
    OUTCOME_INCORRECT,
    OUTCOME_PENDING_MANUAL,
    REASON_CONFIG_INVALID,
    REASON_EXECUTION_REQUIRED,
    REASON_MANUAL_REQUIRED,
    REASON_MISSING_CORRECT_PAYLOAD,
    REASON_STRATEGY_UNSUPPORTED,
)

STRATEGY_EXACT_MATCH = 'EXACT_MATCH'
STRATEGY_SET_MATCH = 'SET_MATCH'
STRATEGY_NUMERIC_TOLERANCE = 'NUMERIC_TOLERANCE'
STRATEGY_NORMALIZED_STRING = 'NORMALIZED_STRING'
STRATEGY_REGEX_MATCH = 'REGEX_MATCH'
STRATEGY_STDOUT_MATCH = 'STDOUT_MATCH'

ALL_STRATEGIES = (
    STRATEGY_EXACT_MATCH,
    STRATEGY_SET_MATCH,
    STRATEGY_NUMERIC_TOLERANCE,
    STRATEGY_NORMALIZED_STRING,
    STRATEGY_REGEX_MATCH,
    STRATEGY_STDOUT_MATCH,
)

#: Strategies permitted to grade in this milestone.
ALLOWED_STRATEGIES = (
    STRATEGY_EXACT_MATCH,
    STRATEGY_SET_MATCH,
    STRATEGY_NUMERIC_TOLERANCE,
    STRATEGY_STDOUT_MATCH,
)


class UngradableConfigurationError(Exception):
    """Expected class-A failure: the configuration cannot produce a decision."""

    def __init__(self, reason: str, message: str = ''):
        self.reason = reason
        self.message = message or reason
        super().__init__(self.message)


@dataclass(frozen=True)
class StrategyDecision:
    outcome: str
    fraction: Optional[Decimal] = None
    ungraded_reason: str = ''
    excluded_reason: str = ''
    details: dict = field(default_factory=dict)


def _correct() -> StrategyDecision:
    return StrategyDecision(outcome=OUTCOME_CORRECT, fraction=Decimal('1.0000'))


def _incorrect() -> StrategyDecision:
    return StrategyDecision(outcome=OUTCOME_INCORRECT, fraction=Decimal('0.0000'))


def _require_mapping(payload: Any, strategy: str) -> dict:
    if not isinstance(payload, dict):
        raise UngradableConfigurationError(
            REASON_MISSING_CORRECT_PAYLOAD,
            f'{strategy} requires an object correct_payload.',
        )
    return payload


def _first_present(payload: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def _submitted_value(question_type: str, answer_payload: Any) -> Any:
    if not isinstance(answer_payload, dict):
        return None
    if question_type == 'SINGLE_CHOICE':
        return answer_payload.get('selected_option_id')
    if question_type == 'MULTIPLE_CHOICE':
        return answer_payload.get('selected_option_ids')
    if question_type == 'TRUE_FALSE':
        return answer_payload.get('selected_value')
    if question_type == 'NUMERICAL':
        return answer_payload.get('value')
    if question_type == 'CODE_OUTPUT':
        if 'output' in answer_payload:
            return answer_payload.get('output')
        return answer_payload.get('text')
    return answer_payload.get('text', answer_payload.get('value'))


def _as_decimal(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, Decimal):
            return value
        if isinstance(value, (int, str)):
            return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return None


def exact_match(
    question_type: str,
    answer_payload: Any,
    correct_payload: Any,
    scoring_rubric: Any,
) -> StrategyDecision:
    config = _require_mapping(correct_payload, STRATEGY_EXACT_MATCH)
    expected = _first_present(
        config,
        ('correct_option_id', 'option_id', 'value', 'expected_value', 'expected'),
    )
    if expected is None:
        raise UngradableConfigurationError(
            REASON_MISSING_CORRECT_PAYLOAD,
            'EXACT_MATCH requires one of correct_option_id/option_id/value/expected_value.',
        )
    submitted = _submitted_value(question_type, answer_payload)

    if question_type == 'NUMERICAL':
        left, right = _as_decimal(submitted), _as_decimal(expected)
        if left is None or right is None:
            return _incorrect()
        return _correct() if left == right else _incorrect()

    return _correct() if submitted == expected else _incorrect()


def set_match(
    question_type: str,
    answer_payload: Any,
    correct_payload: Any,
    scoring_rubric: Any,
) -> StrategyDecision:
    config = _require_mapping(correct_payload, STRATEGY_SET_MATCH)
    expected = _first_present(config, ('correct_option_ids', 'option_ids', 'value'))
    if not isinstance(expected, (list, tuple)) or not expected:
        raise UngradableConfigurationError(
            REASON_MISSING_CORRECT_PAYLOAD,
            'SET_MATCH requires a non-empty correct_option_ids list.',
        )
    submitted = _submitted_value(question_type, answer_payload)
    if not isinstance(submitted, (list, tuple)):
        return _incorrect()
    # All-or-nothing: partial credit policy is unresolved (D-04).
    return _correct() if set(submitted) == set(expected) else _incorrect()


def numeric_tolerance(
    question_type: str,
    answer_payload: Any,
    correct_payload: Any,
    scoring_rubric: Any,
) -> StrategyDecision:
    config = _require_mapping(correct_payload, STRATEGY_NUMERIC_TOLERANCE)
    expected = _as_decimal(_first_present(config, ('value', 'target_value', 'correct_value')))
    if expected is None:
        raise UngradableConfigurationError(
            REASON_MISSING_CORRECT_PAYLOAD,
            'NUMERIC_TOLERANCE requires a numeric value/target_value/correct_value.',
        )

    rubric = scoring_rubric if isinstance(scoring_rubric, dict) else {}
    tolerance = _as_decimal(
        _first_present(config, ('tolerance',))
        if 'tolerance' in config
        else _first_present(rubric, ('tolerance',))
    )
    if tolerance is None:
        raise UngradableConfigurationError(
            REASON_CONFIG_INVALID,
            'NUMERIC_TOLERANCE requires an explicit tolerance; no default exists (D-07).',
        )
    if tolerance < 0:
        raise UngradableConfigurationError(REASON_CONFIG_INVALID, 'Tolerance cannot be negative.')

    tolerance_type = config.get('tolerance_type', 'absolute')
    if tolerance_type != 'absolute':
        raise UngradableConfigurationError(
            REASON_CONFIG_INVALID,
            f"Tolerance type '{tolerance_type}' is not approved; only absolute is supported (D-07).",
        )

    submitted = _as_decimal(_submitted_value(question_type, answer_payload))
    if submitted is None:
        return _incorrect()
    return _correct() if abs(submitted - expected) <= tolerance else _incorrect()


def stdout_match(
    question_type: str,
    answer_payload: Any,
    correct_payload: Any,
    scoring_rubric: Any,
) -> StrategyDecision:
    payload = answer_payload if isinstance(answer_payload, dict) else {}
    if payload.get('source_code'):
        # Execution is out of scope for Phase 2E; a human must resolve this.
        return StrategyDecision(
            outcome=OUTCOME_PENDING_MANUAL,
            ungraded_reason=REASON_MANUAL_REQUIRED,
            details={'requires': 'manual_grading', 'reason': REASON_EXECUTION_REQUIRED},
        )

    config = _require_mapping(correct_payload, STRATEGY_STDOUT_MATCH)
    expected = _first_present(config, ('expected_output', 'value', 'output'))
    if not isinstance(expected, str):
        raise UngradableConfigurationError(
            REASON_MISSING_CORRECT_PAYLOAD,
            'STDOUT_MATCH requires a string expected_output/value/output.',
        )
    submitted = payload.get('output', payload.get('text'))
    if not isinstance(submitted, str):
        return _incorrect()
    # Exact textual comparison: normalization policy is unresolved (D-08).
    return _correct() if submitted == expected else _incorrect()


_DISABLED_MESSAGES = {
    STRATEGY_NORMALIZED_STRING: 'NORMALIZED_STRING is disabled pending the text-normalization policy (D-08).',
    STRATEGY_REGEX_MATCH: 'REGEX_MATCH is disabled pending an approved ReDoS-safe mechanism (D-17b).',
}


def _disabled_strategy(reason_message: str) -> Callable[..., StrategyDecision]:
    def _strategy(question_type, answer_payload, correct_payload, scoring_rubric):
        raise UngradableConfigurationError(REASON_STRATEGY_UNSUPPORTED, reason_message)
    return _strategy


_REGISTRY: dict[str, Callable[..., StrategyDecision]] = {
    STRATEGY_EXACT_MATCH: exact_match,
    STRATEGY_SET_MATCH: set_match,
    STRATEGY_NUMERIC_TOLERANCE: numeric_tolerance,
    STRATEGY_STDOUT_MATCH: stdout_match,
    STRATEGY_NORMALIZED_STRING: _disabled_strategy(_DISABLED_MESSAGES[STRATEGY_NORMALIZED_STRING]),
    STRATEGY_REGEX_MATCH: _disabled_strategy(_DISABLED_MESSAGES[STRATEGY_REGEX_MATCH]),
}


def get_strategy(name: str) -> Callable[..., StrategyDecision]:
    strategy = _REGISTRY.get(name)
    if strategy is None:
        raise UngradableConfigurationError(
            REASON_STRATEGY_UNSUPPORTED,
            f"Unknown grading strategy '{name}'.",
        )
    return strategy


def is_allowed(name: str) -> bool:
    return name in ALLOWED_STRATEGIES
