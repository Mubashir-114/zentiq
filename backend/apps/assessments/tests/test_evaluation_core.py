"""
Pure unit tests for the Phase 2E.2 evaluation core.

No database is touched: canonicalization, strategies, scoring policy, status
derivation, and configuration validation are all pure functions.
"""
import sys
from decimal import Decimal
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest

from apps.assessments.services.evaluation.canonical import (
    CanonicalizationError,
    answer_payload_hash,
    canonical_dumps,
    contains_redaction_marker,
    evaluation_config_hash,
)
from apps.assessments.services.evaluation.config import EvaluationConfigValidator
from apps.assessments.services.evaluation.dto import (
    ANSWER_PRESENT,
    DISPOSITION_EXCLUDED,
    DISPOSITION_SCORED,
    DISPOSITION_UNDECIDED,
    OUTCOME_CORRECT,
    OUTCOME_INCORRECT,
    OUTCOME_PARTIALLY_CORRECT,
    OUTCOME_PENDING_MANUAL,
    OUTCOME_UNANSWERED,
    OUTCOME_UNGRADED,
    RESULT_FINAL,
    RESULT_PROVISIONAL,
    EVAL_AWAITING_MANUAL,
    EVAL_COMPLETE,
    EVAL_CONFIG_UNGRADABLE,
    EVAL_INCOMPLETE_COVERAGE,
    QuestionEvaluationInput,
    QuestionOutcome,
)
from apps.assessments.services.evaluation.evaluator import evaluate_question
from apps.assessments.services.evaluation.policy import (
    compute_score,
    derive_totals,
)
from apps.assessments.services.evaluation.strategies import (
    UngradableConfigurationError,
    numeric_tolerance,
    set_match,
    stdout_match,
)
from apps.assessments.services.exceptions import EvaluationConfigurationError

D = Decimal


def outcome(
    *,
    outcome_kind: str,
    disposition: str,
    fraction,
    weight: str,
) -> QuestionOutcome:
    weight_dec = D(weight).quantize(D('0.000001'))
    points = None
    if fraction is not None:
        points = (weight_dec * D(str(fraction))).quantize(D('0.000001'))
    return QuestionOutcome(
        attempt_question_id=object(),
        outcome=outcome_kind,
        disposition=disposition,
        awarded_fraction=None if fraction is None else D(str(fraction)),
        awarded_points=points,
        max_points=weight_dec,
        grading_strategy='EXACT_MATCH',
    )


# ---------------------------------------------------------------------------
# Canonical JSON / hashing
# ---------------------------------------------------------------------------

class TestCanonicalization:
    def test_key_order_does_not_matter(self):
        assert canonical_dumps({'b': 1, 'a': 2}) == canonical_dumps({'a': 2, 'b': 1})

    def test_numeric_equivalence_is_canonical(self):
        assert canonical_dumps(D('5.00')) == canonical_dumps(5) == '5'
        assert canonical_dumps(D('1.50')) == canonical_dumps(D('1.5')) == '1.5'
        assert canonical_dumps(D('0.00001')) == '0.00001'
        assert canonical_dumps(D('-0')) == '0'

    def test_string_and_number_are_distinct(self):
        assert canonical_dumps('5') == '"5"'
        assert canonical_dumps(5) == '5'
        assert canonical_dumps('5') != canonical_dumps(5)

    def test_bool_is_not_int(self):
        assert canonical_dumps(True) == 'true'
        assert canonical_dumps(False) == 'false'
        assert canonical_dumps(True) != canonical_dumps(1)

    def test_list_order_is_semantic(self):
        assert canonical_dumps([1, 2]) != canonical_dumps([2, 1])

    def test_floats_are_rejected(self):
        with pytest.raises(CanonicalizationError):
            canonical_dumps(1.5)

    def test_non_string_keys_rejected(self):
        with pytest.raises(CanonicalizationError):
            canonical_dumps({1: 'a'})

    def test_hash_is_stable_and_equivalent_payloads_match(self):
        left = {'selected_option_ids': ['opt_1', 'opt_2'], 'value': D('2.50')}
        right = {'value': D('2.5'), 'selected_option_ids': ['opt_1', 'opt_2']}
        assert answer_payload_hash(left) == answer_payload_hash(right)
        assert len(answer_payload_hash(left)) == 64

    def test_config_hash_changes_with_configuration(self):
        base = evaluation_config_hash('EXACT_MATCH', {'value': 'a'}, {}, '2e.2')
        changed = evaluation_config_hash('EXACT_MATCH', {'value': 'b'}, {}, '2e.2')
        assert base != changed

    def test_redaction_marker_detection(self):
        assert contains_redaction_marker({'a': [{'__redacted__': True}]}) is True
        assert contains_redaction_marker({'a': 1}) is False


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

class TestStrategies:
    def test_set_match_is_all_or_nothing(self):
        decision = set_match(
            'MULTIPLE_CHOICE',
            {'selected_option_ids': ['opt_1', 'opt_2']},
            {'correct_option_ids': ['opt_2', 'opt_1']},
            {},
        )
        assert decision.outcome == OUTCOME_CORRECT
        assert decision.fraction == D('1.0000')

        partial = set_match(
            'MULTIPLE_CHOICE',
            {'selected_option_ids': ['opt_1']},
            {'correct_option_ids': ['opt_1', 'opt_2']},
            {},
        )
        assert partial.outcome == OUTCOME_INCORRECT
        assert partial.fraction == D('0.0000')

    def test_numeric_tolerance_requires_explicit_tolerance(self):
        with pytest.raises(UngradableConfigurationError):
            numeric_tolerance('NUMERICAL', {'value': 10}, {'value': 10}, {})

    def test_numeric_tolerance_within_and_outside(self):
        config = {'value': '10', 'tolerance': '0.5'}
        assert numeric_tolerance('NUMERICAL', {'value': '10.5'}, config, {}).outcome == OUTCOME_CORRECT
        assert numeric_tolerance('NUMERICAL', {'value': '10.6'}, config, {}).outcome == OUTCOME_INCORRECT

    def test_relative_tolerance_is_not_approved(self):
        config = {'value': '10', 'tolerance': '0.1', 'tolerance_type': 'relative'}
        with pytest.raises(UngradableConfigurationError):
            numeric_tolerance('NUMERICAL', {'value': '10.1'}, config, {})

    def test_stdout_match_textual_output(self):
        assert stdout_match(
            'CODE_OUTPUT',
            {'output': '42\n'},
            {'expected_output': '42\n'},
            {},
        ).outcome == OUTCOME_CORRECT
        assert stdout_match(
            'CODE_OUTPUT',
            {'output': '41'},
            {'expected_output': '42\n'},
            {},
        ).outcome == OUTCOME_INCORRECT

    def test_stdout_match_source_code_pends_manual(self):
        decision = stdout_match(
            'CODE_OUTPUT',
            {'source_code': 'print(42)'},
            {'expected_output': '42\n'},
            {},
        )
        assert decision.outcome == OUTCOME_PENDING_MANUAL
        assert decision.ungraded_reason == 'MANUAL_REQUIRED'


# ---------------------------------------------------------------------------
# Evaluator (pure)
# ---------------------------------------------------------------------------

class TestEvaluator:
    def _input(self, **overrides) -> QuestionEvaluationInput:
        defaults = dict(
            attempt_question_id='aq-1',
            weight=D('1.00'),
            question_type='SINGLE_CHOICE',
            grading_strategy='EXACT_MATCH',
            correct_payload={'correct_option_id': 'opt_a'},
            scoring_rubric={'rubric_version': '1'},
            answer_payload={'selected_option_id': 'opt_a'},
            answer_presence=ANSWER_PRESENT,
        )
        defaults.update(overrides)
        return QuestionEvaluationInput(**defaults)

    def test_correct_answer(self):
        result = evaluate_question(self._input())
        assert result.outcome == OUTCOME_CORRECT
        assert result.disposition == DISPOSITION_SCORED
        assert result.awarded_fraction == D('1.0000')
        assert result.awarded_points == D('1.000000')
        assert result.answer_payload_hash

    def test_incorrect_answer_scores_zero_not_negative(self):
        result = evaluate_question(self._input(answer_payload={'selected_option_id': 'opt_b'}))
        assert result.outcome == OUTCOME_INCORRECT
        assert result.awarded_fraction == D('0.0000')

    def test_unanswered_is_decided_and_scores_zero(self):
        result = evaluate_question(
            self._input(answer_payload=None, answer_presence='ABSENT', absence_reason='SKIPPED')
        )
        assert result.outcome == OUTCOME_UNANSWERED
        assert result.disposition == DISPOSITION_SCORED
        assert result.awarded_fraction == D('0.0000')
        assert result.absence_reason == 'SKIPPED'

    def test_missing_evaluation_data_is_ungraded_not_zero(self):
        result = evaluate_question(
            self._input(grading_strategy='', correct_payload=None, scoring_rubric=None)
        )
        assert result.outcome == OUTCOME_UNGRADED
        assert result.disposition == DISPOSITION_UNDECIDED
        assert result.awarded_fraction is None
        assert result.ungraded_reason

    def test_disabled_regex_is_ungraded(self):
        result = evaluate_question(self._input(grading_strategy='REGEX_MATCH'))
        assert result.outcome == OUTCOME_UNGRADED
        assert result.ungraded_reason == 'STRATEGY_UNSUPPORTED'

    def test_redacted_answer_is_ungraded(self):
        result = evaluate_question(self._input(answer_redacted=True))
        assert result.outcome == OUTCOME_UNGRADED
        assert result.awarded_fraction is None


# ---------------------------------------------------------------------------
# Scoring policy and status matrix
# ---------------------------------------------------------------------------

class TestScoringPolicy:
    def test_golden_vector_33_33(self):
        rows = [
            outcome(outcome_kind=OUTCOME_CORRECT, disposition=DISPOSITION_SCORED, fraction='1', weight='1.00'),
            outcome(outcome_kind=OUTCOME_PARTIALLY_CORRECT, disposition=DISPOSITION_SCORED, fraction='0.5', weight='2.00'),
            outcome(outcome_kind=OUTCOME_INCORRECT, disposition=DISPOSITION_SCORED, fraction='0', weight='3.00'),
        ]
        totals = derive_totals(rows)
        assert totals.total_weight == D('6.000000')
        assert totals.graded_weight == D('6.000000')
        assert totals.earned_weight == D('2.000000')
        assert totals.status == RESULT_FINAL
        assert totals.evaluation_status == EVAL_COMPLETE
        assert str(totals.final_score) == '33.33'
        assert totals.provisional_score is None

    def test_rounding_is_half_up(self):
        assert compute_score(D('1'), D('6')) == D('16.67')

    def test_unanswered_counts_zero_and_stays_in_denominator(self):
        rows = [
            outcome(outcome_kind=OUTCOME_CORRECT, disposition=DISPOSITION_SCORED, fraction='1', weight='1.00'),
            outcome(outcome_kind=OUTCOME_UNANSWERED, disposition=DISPOSITION_SCORED, fraction='0', weight='2.00'),
        ]
        totals = derive_totals(rows)
        assert totals.total_weight == D('3.000000')
        assert totals.graded_weight == D('3.000000')
        assert totals.unanswered_count == 1
        assert totals.answered_count == 1
        assert totals.status == RESULT_FINAL
        assert str(totals.final_score) == '33.33'

    def test_ungraded_forces_provisional_and_blocks_final_score(self):
        rows = [
            outcome(outcome_kind=OUTCOME_CORRECT, disposition=DISPOSITION_SCORED, fraction='1', weight='1.00'),
            outcome(outcome_kind=OUTCOME_UNGRADED, disposition=DISPOSITION_UNDECIDED, fraction=None, weight='2.00'),
        ]
        totals = derive_totals(rows)
        assert totals.status == RESULT_PROVISIONAL
        assert totals.evaluation_status == EVAL_CONFIG_UNGRADABLE
        assert totals.final_score is None
        assert totals.provisional_score is not None
        assert totals.graded_weight == D('1.000000')

    def test_pending_manual_status(self):
        rows = [
            outcome(outcome_kind=OUTCOME_CORRECT, disposition=DISPOSITION_SCORED, fraction='1', weight='1.00'),
            outcome(outcome_kind=OUTCOME_PENDING_MANUAL, disposition=DISPOSITION_UNDECIDED, fraction=None, weight='2.00'),
        ]
        totals = derive_totals(rows)
        assert totals.status == RESULT_PROVISIONAL
        assert totals.evaluation_status == EVAL_AWAITING_MANUAL

    def test_unapproved_exclusion_is_provisional(self):
        rows = [
            outcome(outcome_kind=OUTCOME_CORRECT, disposition=DISPOSITION_SCORED, fraction='1', weight='1.00'),
            outcome(outcome_kind=OUTCOME_UNANSWERED, disposition=DISPOSITION_EXCLUDED, fraction=None, weight='2.00'),
        ]
        totals = derive_totals(rows)
        assert totals.status == RESULT_PROVISIONAL
        assert totals.evaluation_status == EVAL_INCOMPLETE_COVERAGE
        assert totals.excluded_weight == D('2.000000')
        assert totals.final_score is None

    def test_approved_exclusion_can_be_final_with_independent_coverage(self):
        rows = [
            outcome(outcome_kind=OUTCOME_CORRECT, disposition=DISPOSITION_SCORED, fraction='1', weight='1.00'),
            outcome(outcome_kind=OUTCOME_UNANSWERED, disposition=DISPOSITION_EXCLUDED, fraction=None, weight='2.00'),
        ]
        totals = derive_totals(rows, allow_approved_exclusions=True)
        assert totals.status == RESULT_FINAL
        assert totals.evaluation_status == EVAL_COMPLETE
        assert totals.final_score == D('100.00')
        assert totals.graded_weight == D('1.000000')
        assert totals.total_weight == D('3.000000')

    def test_zero_graded_weight_never_final(self):
        rows = [
            outcome(outcome_kind=OUTCOME_UNANSWERED, disposition=DISPOSITION_EXCLUDED, fraction=None, weight='2.00'),
        ]
        totals = derive_totals(rows, allow_approved_exclusions=True)
        assert totals.status == RESULT_PROVISIONAL
        assert totals.evaluation_status == EVAL_INCOMPLETE_COVERAGE
        assert totals.final_score is None
        assert totals.provisional_score is None


# ---------------------------------------------------------------------------
# Configuration validation
# ---------------------------------------------------------------------------

class TestConfigValidator:
    def test_valid_configuration_passes_strict(self):
        report = EvaluationConfigValidator.inspect(
            question_type='SINGLE_CHOICE',
            grading_strategy='EXACT_MATCH',
            correct_payload={'correct_option_id': 'opt_a'},
            scoring_rubric={'rubric_version': '1'},
            strict=True,
        )
        assert report.ok

    def test_incompatible_type_strategy_is_an_error(self):
        report = EvaluationConfigValidator.inspect(
            question_type='SINGLE_CHOICE',
            grading_strategy='SET_MATCH',
            correct_payload={'correct_option_ids': ['a']},
            scoring_rubric={'rubric_version': '1'},
        )
        assert report.errors
        assert not report.ok

    def test_missing_rubric_version_is_reported(self):
        report = EvaluationConfigValidator.inspect(
            question_type='SINGLE_CHOICE',
            grading_strategy='EXACT_MATCH',
            correct_payload={'correct_option_id': 'opt_a'},
            scoring_rubric={},
        )
        assert any('rubric_version' in item for item in report.missing)

    def test_strict_mode_raises(self):
        with pytest.raises(EvaluationConfigurationError):
            EvaluationConfigValidator.inspect(
                question_type='NUMERICAL',
                grading_strategy='NUMERIC_TOLERANCE',
                correct_payload={'value': '10'},
                scoring_rubric={'rubric_version': '1'},
                strict=True,
            )

    def test_disabled_strategy_is_rejected(self):
        report = EvaluationConfigValidator.inspect(
            question_type='SHORT_TEXT',
            grading_strategy='REGEX_MATCH',
            correct_payload={'pattern': '^a+$'},
            scoring_rubric={'rubric_version': '1'},
        )
        assert report.errors
