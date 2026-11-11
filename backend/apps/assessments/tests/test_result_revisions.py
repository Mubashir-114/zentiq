"""
Integration tests for Phase 2E.2 result persistence.

Covers: submit-time evaluation, weighted scoring, unanswered semantics,
immutable revisions, authoritative head movement, stale/cross-attempt
supersession conflicts, transaction rollback on unexpected errors, redaction
refusal, terminal snapshots, and confidential-data isolation.
"""
import sys
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.arena.models import Question, QuestionEvaluationData, QuestionVersion
from apps.assessments.models import (
    Assessment,
    AssessmentAttempt,
    AssessmentVersion,
    AttemptAnswer,
    AttemptQuestion,
    AttemptQuestionEvaluation,
    AttemptResultHead,
    AttemptResultRevision,
    AttemptTerminalSnapshot,
    ResultOutboxEvent,
)
from apps.assessments.services import (
    AnswerValidationError,
    AssessmentAnswerService,
    AssessmentAttemptService,
    AssessmentCompositionService,
    AttemptEvaluationService,
    AttemptExpiredError,
    AttemptRedactedError,
    ResultRevisionConflictError,
    ResultRevisionIntegrityError,
    ResultRevisionService,
)
from apps.assessments.services.evaluation.dto import QuestionOutcome
from apps.skills.models import Competency, Domain, Subdomain

User = get_user_model()


@pytest.fixture
def author_user(db):
    return User.objects.create_user(
        email='author_eval@example.com', password='TestPassword123!', is_staff=True,
    )


@pytest.fixture
def grader_user(db):
    return User.objects.create_user(
        email='grader_eval@example.com', password='TestPassword123!', is_staff=True,
    )


@pytest.fixture
def candidate_user(db):
    return User.objects.create_user(email='cand_eval@example.com', password='TestPassword123!')


@pytest.fixture
def other_candidate(db):
    return User.objects.create_user(email='other_eval@example.com', password='TestPassword123!')


@pytest.fixture
def competency(db):
    domain = Domain.objects.create(
        slug='eval-domain', name='Evaluation', category='TECHNICAL',
        description='Evaluation domain', display_order=1,
    )
    subdomain = Subdomain.objects.create(
        domain=domain, slug='eval-sub', name='Eval Sub', display_order=1,
    )
    return Competency.objects.create(
        subdomain=subdomain, code='COMP-EVAL-01', name='Evaluation Competency',
        description='Evaluation', bloom_level='APPLY',
    )


def make_published_question(
    *,
    author_user,
    competency,
    code,
    question_type,
    strategy,
    correct_payload,
    rubric=None,
    content_payload=None,
):
    question = Question.objects.create(code=code, created_by=author_user)
    version = QuestionVersion.objects.create(
        question=question,
        version_number=1,
        status='DRAFT',
        title=f'Question {code}',
        prompt='Answer the question.',
        question_type=question_type,
        primary_competency=competency,
        content_payload=content_payload or {},
        created_by=author_user,
    )
    if strategy:
        QuestionEvaluationData.objects.create(
            question_version=version,
            grading_strategy=strategy,
            correct_payload=correct_payload,
            scoring_rubric=rubric or {'rubric_version': '1'},
        )
    version.status = 'IN_REVIEW'
    version.save()
    version.status = 'PUBLISHED'
    version.save()
    question.active_version = version
    question.save()
    return version


def make_assessment(*, author_user, code, version_weights, published=True):
    assessment = AssessmentCompositionService.create_assessment(
        code=code, title=f'Assessment {code}', user=author_user,
    )
    version = AssessmentCompositionService.create_draft_version(
        assessment.id, title='v1', time_limit_seconds=1800,
        allow_backtracking=True, user=author_user,
    )
    for question_version, weight in version_weights:
        AssessmentCompositionService.add_question_to_version(
            version.id, question_version.id, weight=weight, user=author_user,
        )
    if published:
        AssessmentCompositionService.publish_version(version.id, user=author_user)
        assessment.refresh_from_db()
    return assessment, version


@pytest.fixture
def scoring_assessment(db, author_user, competency):
    """Three questions: weight 1 (single choice), 2 (multi), 3 (numerical)."""
    qv1 = make_published_question(
        author_user=author_user, competency=competency, code='QST-EVAL-001',
        question_type='SINGLE_CHOICE', strategy='EXACT_MATCH',
        correct_payload={'correct_option_id': 'opt_a'},
        content_payload={'options': [{'id': 'opt_a', 'text': 'A'}, {'id': 'opt_b', 'text': 'B'}]},
    )
    qv2 = make_published_question(
        author_user=author_user, competency=competency, code='QST-EVAL-002',
        question_type='MULTIPLE_CHOICE', strategy='SET_MATCH',
        correct_payload={'correct_option_ids': ['opt_1', 'opt_2']},
        content_payload={'options': [
            {'id': 'opt_1', 'text': '1'}, {'id': 'opt_2', 'text': '2'}, {'id': 'opt_3', 'text': '3'},
        ]},
    )
    qv3 = make_published_question(
        author_user=author_user, competency=competency, code='QST-EVAL-003',
        question_type='NUMERICAL', strategy='NUMERIC_TOLERANCE',
        correct_payload={'value': '10', 'tolerance': '0.5'},
    )
    return make_assessment(
        author_user=author_user, code='ASM-EVAL-001',
        version_weights=[(qv1, Decimal('1.00')), (qv2, Decimal('2.00')), (qv3, Decimal('3.00'))],
    )


@pytest.fixture
def unanswered_assessment(db, author_user, competency):
    qv = make_published_question(
        author_user=author_user, competency=competency, code='QST-EVAL-010',
        question_type='SHORT_TEXT', strategy='EXACT_MATCH',
        correct_payload={'value': 'TOP_SECRET_EXPECTED_VALUE'},
    )
    return make_assessment(
        author_user=author_user, code='ASM-EVAL-010', version_weights=[(qv, Decimal('1.00'))],
    )


@pytest.fixture
def legacy_assessment(db, author_user, competency):
    """Published question with no evaluation data (legacy / ungradable)."""
    qv = make_published_question(
        author_user=author_user, competency=competency, code='QST-EVAL-020',
        question_type='SHORT_TEXT', strategy=None, correct_payload=None,
    )
    return make_assessment(
        author_user=author_user, code='ASM-EVAL-020', version_weights=[(qv, Decimal('1.00'))],
    )


def start_attempt(assessment, user, key):
    attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
        assessment_id=assessment.id, user=user, idempotency_key=key,
    )
    return attempt


def submit(attempt, user):
    return AssessmentAttemptService.submit_attempt(attempt.id, user=user)


# ---------------------------------------------------------------------------
# Submit-time evaluation
# ---------------------------------------------------------------------------

class TestSubmitEvaluation:
    def test_all_correct_produces_final_revision(self, db, scoring_assessment, candidate_user):
        assessment, _ = scoring_assessment
        attempt = start_attempt(assessment, candidate_user, 'idem-eval-all')
        AssessmentAnswerService.submit_answer(
            attempt.id, 1, {'selected_option_id': 'opt_a'}, user=candidate_user)
        AssessmentAnswerService.submit_answer(
            attempt.id, 2, {'selected_option_ids': ['opt_1', 'opt_2']}, user=candidate_user)
        AssessmentAnswerService.submit_answer(
            attempt.id, 3, {'value': '10.25'}, user=candidate_user)

        submit(attempt, candidate_user)

        revision = AttemptResultRevision.objects.get(attempt=attempt)
        assert revision.revision_number == 1
        assert revision.status == 'FINAL'
        assert revision.evaluation_status == 'COMPLETE'
        assert revision.total_weight == Decimal('6.000000')
        assert revision.graded_weight == Decimal('6.000000')
        assert revision.earned_weight == Decimal('6.000000')
        assert revision.final_score == Decimal('100.00')
        assert revision.provisional_score is None
        assert revision.correct_count == 3
        assert revision.question_count == 3

        head = AttemptResultHead.objects.get(attempt=attempt)
        assert head.current_revision_id == revision.id
        assert AttemptQuestionEvaluation.objects.filter(result_revision=revision).count() == 3

        snapshot = AttemptTerminalSnapshot.objects.get(attempt=attempt)
        assert snapshot.terminal_status == 'SUBMITTED'
        assert snapshot.evaluate_eligible is True

        assert ResultOutboxEvent.objects.filter(result_revision=revision).count() == 1

    def test_partial_credit_scores_weighted_percentage(self, db, scoring_assessment, candidate_user):
        assessment, _ = scoring_assessment
        attempt = start_attempt(assessment, candidate_user, 'idem-eval-partial')
        AssessmentAnswerService.submit_answer(
            attempt.id, 1, {'selected_option_id': 'opt_a'}, user=candidate_user)
        AssessmentAnswerService.submit_answer(
            attempt.id, 2, {'selected_option_ids': ['opt_1']}, user=candidate_user)
        AssessmentAnswerService.submit_answer(
            attempt.id, 3, {'value': '20'}, user=candidate_user)

        submit(attempt, candidate_user)

        revision = AttemptResultRevision.objects.get(attempt=attempt)
        assert revision.status == 'FINAL'
        assert revision.earned_weight == Decimal('1.000000')
        assert revision.graded_weight == Decimal('6.000000')
        assert revision.final_score == Decimal('16.67')
        assert revision.correct_count == 1
        assert revision.incorrect_count == 2

    def test_unanswered_is_scored_zero_in_denominator(self, db, scoring_assessment, candidate_user):
        assessment, _ = scoring_assessment
        attempt = start_attempt(assessment, candidate_user, 'idem-eval-unanswered')
        AssessmentAnswerService.submit_answer(
            attempt.id, 1, {'selected_option_id': 'opt_a'}, user=candidate_user)

        submit(attempt, candidate_user)

        revision = AttemptResultRevision.objects.get(attempt=attempt)
        assert revision.status == 'FINAL'
        assert revision.unanswered_count == 2
        assert revision.answered_count == 1
        assert revision.graded_weight == Decimal('6.000000')
        assert revision.earned_weight == Decimal('1.000000')
        assert revision.final_score == Decimal('16.67')

        unanswered = AttemptQuestionEvaluation.objects.filter(
            result_revision=revision, outcome='UNANSWERED',
        ).first()
        assert unanswered.disposition == 'SCORED'
        assert unanswered.awarded_fraction == Decimal('0.0000')
        assert unanswered.absence_reason == 'NOT_REACHED'

    def test_missing_evaluation_data_is_provisional(self, db, legacy_assessment, candidate_user):
        assessment, _ = legacy_assessment
        attempt = start_attempt(assessment, candidate_user, 'idem-eval-legacy')
        AssessmentAnswerService.submit_answer(attempt.id, 1, {'text': 'anything'}, user=candidate_user)

        submit(attempt, candidate_user)

        revision = AttemptResultRevision.objects.get(attempt=attempt)
        assert revision.status == 'PROVISIONAL'
        assert revision.evaluation_status == 'CONFIGURATION_UNGRADABLE'
        assert revision.final_score is None
        assert revision.provisional_score is None
        assert revision.ungraded_count == 1
        assert AttemptQuestionEvaluation.objects.get(
            result_revision=revision,
        ).ungraded_reason == 'STRATEGY_UNSUPPORTED'

    def test_source_code_answer_pends_manual(self, db, author_user, competency, candidate_user):
        qv = make_published_question(
            author_user=author_user, competency=competency, code='QST-EVAL-030',
            question_type='CODE_OUTPUT', strategy='STDOUT_MATCH',
            correct_payload={'expected_output': '42\n'},
        )
        assessment, _ = make_assessment(
            author_user=author_user, code='ASM-EVAL-030',
            version_weights=[(qv, Decimal('2.00'))],
        )
        attempt = start_attempt(assessment, candidate_user, 'idem-eval-code')
        # Phase 2D's public answer contract accepts output/text only; the SOURCE_CODE
        # answer shape is not yet approved (D-15). Persist the row directly to verify
        # the evaluator's PENDING_MANUAL branch without changing the API contract.
        aq = AttemptQuestion.objects.get(attempt=attempt, order_index=1)
        attempt.answer_count = 1
        attempt.save(update_fields=['answer_count', 'updated_at'])
        AttemptAnswer.objects.create(
            attempt_question=aq,
            answer_payload={'source_code': 'print(42)'},
            is_answered=True,
            answered_at=timezone.now(),
        )

        submit(attempt, candidate_user)

        revision = AttemptResultRevision.objects.get(attempt=attempt)
        assert revision.status == 'PROVISIONAL'
        assert revision.evaluation_status == 'AWAITING_MANUAL_GRADING'
        assert revision.final_score is None


# ---------------------------------------------------------------------------
# Immutability and confidentiality
# ---------------------------------------------------------------------------

class TestRevisionImmutability:
    def test_revision_cannot_be_updated_or_deleted(self, db, scoring_assessment, candidate_user):
        assessment, _ = scoring_assessment
        attempt = start_attempt(assessment, candidate_user, 'idem-eval-immutable')
        submit(attempt, candidate_user)
        revision = AttemptResultRevision.objects.get(attempt=attempt)

        revision.status = 'PROVISIONAL'
        with pytest.raises(ValidationError):
            revision.save()

        with pytest.raises(ValidationError):
            revision.delete()

        with pytest.raises(ValidationError):
            AttemptResultRevision.objects.filter(pk=revision.pk).update(status='PROVISIONAL')

        with pytest.raises(ValidationError):
            AttemptQuestionEvaluation.objects.filter(result_revision=revision).delete()

    def test_snapshot_cannot_be_mutated(self, db, scoring_assessment, candidate_user):
        assessment, _ = scoring_assessment
        attempt = start_attempt(assessment, candidate_user, 'idem-eval-snapshot')
        submit(attempt, candidate_user)
        snapshot = AttemptTerminalSnapshot.objects.get(attempt=attempt)

        snapshot.evaluate_eligible = False
        with pytest.raises(ValidationError):
            snapshot.save()
        with pytest.raises(ValidationError):
            snapshot.delete()

    def test_correct_answer_is_not_persisted_in_details(self, db, unanswered_assessment, candidate_user):
        assessment, _ = unanswered_assessment
        attempt = start_attempt(assessment, candidate_user, 'idem-eval-secret')
        AssessmentAnswerService.submit_answer(attempt.id, 1, {'text': 'wrong'}, user=candidate_user)

        submit(attempt, candidate_user)

        revision = AttemptResultRevision.objects.get(attempt=attempt)
        rows = list(AttemptQuestionEvaluation.objects.filter(result_revision=revision))
        serialized = ' '.join(str(row.details) for row in rows)
        assert 'TOP_SECRET_EXPECTED_VALUE' not in serialized
        assert revision.status == 'FINAL'
        assert revision.final_score == Decimal('0.00')


# ---------------------------------------------------------------------------
# Supersession, staleness, cross-attempt integrity
# ---------------------------------------------------------------------------

class TestSupersession:
    def test_supersede_preserves_history_and_moves_head(
        self, db, scoring_assessment, candidate_user, grader_user,
    ):
        assessment, _ = scoring_assessment
        attempt = start_attempt(assessment, candidate_user, 'idem-eval-supersede')
        submit(attempt, candidate_user)
        first = AttemptResultRevision.objects.get(attempt=attempt)

        second = AttemptEvaluationService.evaluate_attempt(
            attempt,
            actor=grader_user,
            reason='CORRECTION',
            expected_revision_id=first.id,
        )

        assert second.revision_number == 2
        assert second.supersedes_id == first.id
        assert second.actor_type == 'STAFF'
        assert second.actor_id == grader_user.id

        first.refresh_from_db()
        assert first.status == 'FINAL'  # preserved, unchanged
        assert list(first.superseded_by.values_list('pk', flat=True)) == [second.id]

        head = AttemptResultHead.objects.get(attempt=attempt)
        assert head.current_revision_id == second.id
        assert AttemptResultRevision.objects.filter(attempt=attempt).count() == 2
        assert ResultOutboxEvent.objects.filter(result_revision=second).count() == 1

    def test_stale_predecessor_is_rejected(self, db, scoring_assessment, candidate_user):
        assessment, _ = scoring_assessment
        attempt = start_attempt(assessment, candidate_user, 'idem-eval-stale')
        submit(attempt, candidate_user)

        with pytest.raises(ResultRevisionConflictError):
            AttemptEvaluationService.evaluate_attempt(
                attempt, expected_revision_id=uuid.uuid4(),
            )

        with pytest.raises(ResultRevisionConflictError):
            # No token supplied while an authoritative revision exists.
            AttemptEvaluationService.evaluate_attempt(attempt)

        assert AttemptResultRevision.objects.filter(attempt=attempt).count() == 1

    def test_cross_attempt_outcomes_are_rejected(
        self, db, scoring_assessment, candidate_user, other_candidate,
    ):
        assessment, _ = scoring_assessment
        attempt_a = start_attempt(assessment, candidate_user, 'idem-eval-a')
        submit(attempt_a, candidate_user)
        revision_a = AttemptResultRevision.objects.get(attempt=attempt_a)

        attempt_b = start_attempt(assessment, other_candidate, 'idem-eval-b')
        submit(attempt_b, other_candidate)
        revision_b = AttemptResultRevision.objects.get(attempt=attempt_b)

        foreign_rows = [
            QuestionOutcome(
                attempt_question_id=row.attempt_question_id,
                outcome=row.outcome,
                disposition=row.disposition,
                awarded_fraction=row.awarded_fraction,
                awarded_points=row.awarded_points,
                max_points=row.max_points,
                grading_strategy=row.grading_strategy,
            )
            for row in revision_a.question_evaluations.all()
        ]

        with pytest.raises(ResultRevisionIntegrityError):
            ResultRevisionService.record_revision(
                attempt_b, foreign_rows, expected_revision_id=revision_b.id,
            )

        assert AttemptResultRevision.objects.filter(attempt=attempt_b).count() == 1


# ---------------------------------------------------------------------------
# Terminal transitions, rollback, redaction
# ---------------------------------------------------------------------------

class TestTerminalAndFailureBehaviour:
    def test_unexpected_error_rolls_back_submission(
        self, db, scoring_assessment, candidate_user, monkeypatch,
    ):
        assessment, _ = scoring_assessment
        attempt = start_attempt(assessment, candidate_user, 'idem-eval-rollback')

        import apps.assessments.services.evaluation.service as evaluation_service

        def _boom(inp):
            raise RuntimeError('unexpected evaluator bug')

        monkeypatch.setattr(evaluation_service, 'evaluate_question', _boom)

        with pytest.raises(RuntimeError):
            submit(attempt, candidate_user)

        attempt.refresh_from_db()
        assert attempt.status == 'IN_PROGRESS'
        assert not AttemptTerminalSnapshot.objects.filter(attempt=attempt).exists()
        assert not AttemptResultRevision.objects.filter(attempt=attempt).exists()

    def test_redacted_answer_blocks_evaluation(
        self, db, scoring_assessment, candidate_user,
    ):
        assessment, _ = scoring_assessment
        attempt = start_attempt(assessment, candidate_user, 'idem-eval-redacted')
        AssessmentAnswerService.submit_answer(
            attempt.id, 1, {'selected_option_id': 'opt_a'}, user=candidate_user)
        AttemptAnswer.objects.filter(
            attempt_question__attempt=attempt,
        ).update(redacted_at=timezone.now())

        with pytest.raises(AttemptRedactedError):
            submit(attempt, candidate_user)

        attempt.refresh_from_db()
        assert attempt.status == 'IN_PROGRESS'
        assert not AttemptResultRevision.objects.filter(attempt=attempt).exists()

    def test_expired_attempt_gets_snapshot_but_is_not_evaluated(
        self, db, scoring_assessment, candidate_user,
    ):
        assessment, _ = scoring_assessment
        attempt = start_attempt(assessment, candidate_user, 'idem-eval-expired')
        AssessmentAttempt.objects.filter(pk=attempt.pk).update(
            deadline=timezone.now() - timedelta(seconds=1),
        )

        with pytest.raises(AttemptExpiredError):
            submit(attempt, candidate_user)

        attempt.refresh_from_db()
        assert attempt.status == 'EXPIRED'
        snapshot = AttemptTerminalSnapshot.objects.get(attempt=attempt)
        assert snapshot.terminal_status == 'EXPIRED'
        assert snapshot.evaluate_eligible is False
        assert not AttemptResultRevision.objects.filter(attempt=attempt).exists()

    def test_cancelled_attempt_gets_snapshot_without_result(
        self, db, scoring_assessment, candidate_user,
    ):
        assessment, _ = scoring_assessment
        attempt = start_attempt(assessment, candidate_user, 'idem-eval-cancel')
        AssessmentAttemptService.cancel_attempt(attempt.id, user=candidate_user)

        snapshot = AttemptTerminalSnapshot.objects.get(attempt=attempt)
        assert snapshot.terminal_status == 'CANCELLED'
        assert snapshot.evaluate_eligible is False
        assert not AttemptResultRevision.objects.filter(attempt=attempt).exists()

    def test_redaction_sentinel_is_rejected_as_candidate_answer(
        self, db, scoring_assessment, candidate_user,
    ):
        assessment, _ = scoring_assessment
        attempt = start_attempt(assessment, candidate_user, 'idem-eval-sentinel')

        with pytest.raises(AnswerValidationError):
            AssessmentAnswerService.submit_answer(
                attempt.id, 1, {'__redacted__': True}, user=candidate_user,
            )

    def test_in_progress_attempt_has_no_result(self, db, scoring_assessment, candidate_user):
        assessment, _ = scoring_assessment
        attempt = start_attempt(assessment, candidate_user, 'idem-eval-inprogress')

        assert not AttemptResultRevision.objects.filter(attempt=attempt).exists()
        assert not AttemptResultHead.objects.filter(attempt=attempt).exists()
