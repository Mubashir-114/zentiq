"""
Evaluation configuration inspection and publishing gate support (Phase 2E.2).

Two modes over one rule set:
- ``inspect(..., strict=False)`` is advisory: it never blocks a draft save and
  reports missing configuration rather than raising.
- ``inspect(..., strict=True)`` fails closed and raises
  ``EvaluationConfigurationError``. Publication must use strict mode.

Phase 2E.2 exposes the validator; wiring it into the Arena publication path is
deferred because legacy published configurations (D-19) are unresolved and must
not be retroactively invalidated. Runtime evaluation never trusts configuration:
anything that cannot be verified degrades to ``UNGRADED``.
"""
from dataclasses import dataclass, field
from typing import Any

from ..exceptions import EvaluationConfigurationError
from .strategies import (
    ALLOWED_STRATEGIES,
    STRATEGY_EXACT_MATCH,
    STRATEGY_NUMERIC_TOLERANCE,
    STRATEGY_SET_MATCH,
    STRATEGY_STDOUT_MATCH,
)

#: G1: approved question-type <-> grading-strategy compatibility matrix.
TYPE_STRATEGY_MATRIX: dict[str, tuple[str, ...]] = {
    'SINGLE_CHOICE': (STRATEGY_EXACT_MATCH,),
    'TRUE_FALSE': (STRATEGY_EXACT_MATCH,),
    'MULTIPLE_CHOICE': (STRATEGY_SET_MATCH,),
    'NUMERICAL': (STRATEGY_NUMERIC_TOLERANCE,),
    'SHORT_TEXT': (STRATEGY_EXACT_MATCH,),
    'CODE_OUTPUT': (STRATEGY_STDOUT_MATCH,),
}

REQUIRED_CORRECT_PAYLOAD_KEYS: dict[str, tuple[str, ...]] = {
    STRATEGY_EXACT_MATCH: ('correct_option_id', 'option_id', 'value', 'expected_value', 'expected'),
    STRATEGY_SET_MATCH: ('correct_option_ids', 'option_ids', 'value'),
    STRATEGY_NUMERIC_TOLERANCE: ('value', 'target_value', 'correct_value'),
    STRATEGY_STDOUT_MATCH: ('expected_output', 'value', 'output'),
}


@dataclass
class ConfigReport:
    errors: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and not self.missing


class EvaluationConfigValidator:
    """Validates one QuestionVersion's confidential evaluation configuration."""

    @classmethod
    def inspect(
        cls,
        *,
        question_type: str,
        grading_strategy: str,
        correct_payload: Any,
        scoring_rubric: Any,
        strict: bool = False,
    ) -> ConfigReport:
        report = ConfigReport()

        # G1 — type/strategy compatibility
        allowed_for_type = TYPE_STRATEGY_MATRIX.get(question_type, ())
        if not allowed_for_type:
            report.errors.append(f"Unknown question type '{question_type}'.")
        elif grading_strategy not in allowed_for_type:
            report.errors.append(
                f"Grading strategy '{grading_strategy}' is not compatible with question type "
                f"'{question_type}'. Allowed: {', '.join(allowed_for_type)}."
            )

        # G5 — strategy enabled in this milestone
        if grading_strategy not in ALLOWED_STRATEGIES:
            report.errors.append(
                f"Grading strategy '{grading_strategy}' is disabled in this milestone."
            )

        # G2 — correct-answer payload schema
        if not isinstance(correct_payload, dict):
            report.errors.append('correct_payload must be a JSON object.')
        else:
            required = REQUIRED_CORRECT_PAYLOAD_KEYS.get(grading_strategy, ())
            if required and not any(
                key in correct_payload and correct_payload[key] is not None for key in required
            ):
                report.missing.append(
                    f"correct_payload requires one of: {', '.join(required)}."
                )
            if grading_strategy == STRATEGY_SET_MATCH:
                candidate = next(
                    (correct_payload[k] for k in ('correct_option_ids', 'option_ids', 'value')
                     if k in correct_payload),
                    None,
                )
                if candidate is not None and not isinstance(candidate, (list, tuple)):
                    report.errors.append('SET_MATCH correct option ids must be a list.')

        # G3 — rubric schema version
        rubric = scoring_rubric if isinstance(scoring_rubric, dict) else {}
        rubric_version = rubric.get('rubric_version')
        if rubric_version is None:
            report.missing.append("scoring_rubric requires a 'rubric_version'.")
        elif not isinstance(rubric_version, str) or not rubric_version.strip():
            report.errors.append("scoring_rubric['rubric_version'] must be a non-empty string.")

        # G4 — required configuration
        if grading_strategy == STRATEGY_NUMERIC_TOLERANCE:
            has_tolerance = (
                isinstance(correct_payload, dict) and 'tolerance' in correct_payload
            ) or ('tolerance' in rubric and rubric.get('tolerance') is not None)
            if not has_tolerance:
                report.missing.append(
                    'NUMERIC_TOLERANCE requires an explicit tolerance (no default exists).'
                )
            tolerance_type = (
                correct_payload.get('tolerance_type', 'absolute')
                if isinstance(correct_payload, dict) else 'absolute'
            )
            if tolerance_type != 'absolute':
                report.warnings.append(
                    f"Tolerance type '{tolerance_type}' is not approved; evaluation will mark "
                    'this question UNGRADED.'
                )

        if strict and (report.errors or report.missing):
            raise EvaluationConfigurationError(
                'Evaluation configuration is incomplete or invalid for publication.',
                details={
                    'errors': report.errors,
                    'missing': report.missing,
                    'warnings': report.warnings,
                },
            )

        return report
