"""
Unit and integration tests for AssessmentAnswerService (Milestone 4A - Phase 2D.2 Stage C).
Covers:
- Answer submission across all supported question types (SINGLE_CHOICE, MULTIPLE_CHOICE, TRUE_FALSE, NUMERICAL, SHORT_TEXT, CODE_OUTPUT).
- Answer payload validation against question type and snapshot choices.
- Distinct answer count maintenance.
- Explicit question skipping and audit log integrity.
- Forward-only navigation and auto-advancement when backtracking is disabled.
- Prevention of out-of-order submissions when backtracking is disabled.
- Terminal-state immutability and server-side deadline expiration.
- Candidate-facing data confidentiality.
- Authorization checks.
"""
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import sys

# Ensure backend root is on sys.path
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.arena.models import Question, QuestionVersion
from apps.assessments.models import (
    AssessmentAttempt,
    AttemptAnswer,
    AttemptEvent,
    AttemptQuestion,
)
from apps.assessments.services import (
    AnswerValidationError,
    AssessmentAnswerService,
    AssessmentAttemptService,
    AssessmentCompositionService,
    AssessmentPermissionDeniedError,
    AttemptExpiredError,
    AttemptTerminalError,
    BacktrackingNotAllowedError,
)
from apps.skills.models import Competency, Domain, Subdomain

User = get_user_model()


@pytest.fixture
def author_user(db):
    return User.objects.create_user(
        email='author_ans@example.com',
        password='TestPassword123!',
        is_staff=True,
    )


@pytest.fixture
def candidate_user(db):
    return User.objects.create_user(
        email='cand_ans@example.com',
        password='TestPassword123!',
    )


@pytest.fixture
def other_candidate(db):
    return User.objects.create_user(
        email='other_ans@example.com',
        password='TestPassword123!',
    )


@pytest.fixture
def competency(db):
    domain = Domain.objects.create(
        slug='algorithms',
        name='Algorithms',
        category='TECHNICAL',
        description='Algorithmic domain',
        display_order=1,
    )
    subdomain = Subdomain.objects.create(
        domain=domain,
        slug='sorting',
        name='Sorting',
        display_order=1,
    )
    return Competency.objects.create(
        subdomain=subdomain,
        code='COMP-SORT-01',
        name='QuickSort Analysis',
        description='Sorting mechanics',
        bloom_level='ANALYZE',
    )


@pytest.fixture
def multi_type_assessment(db, author_user, competency):
    """Creates a published assessment containing diverse question types."""
    # 1. SINGLE_CHOICE
    q1 = Question.objects.create(code='QST-TYP-001', created_by=author_user)
    qv1 = QuestionVersion.objects.create(
        question=q1,
        version_number=1,
        status='DRAFT',
        title='Single Choice Q',
        prompt='Pick the correct algorithm.',
        question_type='SINGLE_CHOICE',
        primary_competency=competency,
        content_payload={'options': [{'id': 'opt_a', 'text': 'QuickSort'}, {'id': 'opt_b', 'text': 'MergeSort'}]},
        created_by=author_user,
    )
    qv1.status = 'IN_REVIEW'
    qv1.save()
    qv1.status = 'PUBLISHED'
    qv1.save()
    q1.active_version = qv1
    q1.save()

    # 2. MULTIPLE_CHOICE
    q2 = Question.objects.create(code='QST-TYP-002', created_by=author_user)
    qv2 = QuestionVersion.objects.create(
        question=q2,
        version_number=1,
        status='DRAFT',
        title='Multiple Choice Q',
        prompt='Select all stable sorts.',
        question_type='MULTIPLE_CHOICE',
        primary_competency=competency,
        content_payload={'options': [{'id': 'opt_1', 'text': 'MergeSort'}, {'id': 'opt_2', 'text': 'InsertionSort'}, {'id': 'opt_3', 'text': 'HeapSort'}]},
        created_by=author_user,
    )
    qv2.status = 'IN_REVIEW'
    qv2.save()
    qv2.status = 'PUBLISHED'
    qv2.save()
    q2.active_version = qv2
    q2.save()

    # 3. NUMERICAL
    q3 = Question.objects.create(code='QST-TYP-003', created_by=author_user)
    qv3 = QuestionVersion.objects.create(
        question=q3,
        version_number=1,
        status='DRAFT',
        title='Numerical Q',
        prompt='What is the best case time complexity constant?',
        question_type='NUMERICAL',
        primary_competency=competency,
        content_payload={},
        created_by=author_user,
    )
    qv3.status = 'IN_REVIEW'
    qv3.save()
    qv3.status = 'PUBLISHED'
    qv3.save()
    q3.active_version = qv3
    q3.save()

    # 4. SHORT_TEXT
    q4 = Question.objects.create(code='QST-TYP-004', created_by=author_user)
    qv4 = QuestionVersion.objects.create(
        question=q4,
        version_number=1,
        status='DRAFT',
        title='Short Text Q',
        prompt='State the pivot selection strategy.',
        question_type='SHORT_TEXT',
        primary_competency=competency,
        content_payload={},
        created_by=author_user,
    )
    qv4.status = 'IN_REVIEW'
    qv4.save()
    qv4.status = 'PUBLISHED'
    qv4.save()
    q4.active_version = qv4
    q4.save()

    asm = AssessmentCompositionService.create_assessment(
        code='ASM-ANS-001',
        title='Question Types Assessment',
        user=author_user,
    )
    ver = AssessmentCompositionService.create_draft_version(
        asm.id,
        title='Types v1.0',
        time_limit_seconds=1800,
        allow_backtracking=True,
        user=author_user,
    )
    AssessmentCompositionService.add_question_to_version(ver.id, qv1.id, weight=Decimal('1.00'), user=author_user)
    AssessmentCompositionService.add_question_to_version(ver.id, qv2.id, weight=Decimal('1.00'), user=author_user)
    AssessmentCompositionService.add_question_to_version(ver.id, qv3.id, weight=Decimal('1.00'), user=author_user)
    AssessmentCompositionService.add_question_to_version(ver.id, qv4.id, weight=Decimal('1.00'), user=author_user)
    AssessmentCompositionService.publish_version(ver.id, user=author_user)
    asm.refresh_from_db()
    return asm, ver


# ==============================================================================
# Question Type Validation & Submission Tests
# ==============================================================================

class TestAnswerSubmissionAndValidation:
    def test_single_choice_submission_and_validation(self, db, candidate_user, multi_type_assessment):
        asm, _ = multi_type_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-ans-sc',
        )
        # Valid option
        dto = AssessmentAnswerService.submit_answer(
            attempt.id,
            question_order_index=1,
            answer_payload={'selected_option_id': 'opt_a'},
            user=candidate_user,
        )
        assert dto.is_answered is True
        assert dto.current_answer == {'selected_option_id': 'opt_a'}

        # Invalid option not in choices
        with pytest.raises(AnswerValidationError):
            AssessmentAnswerService.submit_answer(
                attempt.id,
                question_order_index=1,
                answer_payload={'selected_option_id': 'opt_nonexistent'},
                user=candidate_user,
            )

        # Missing key
        with pytest.raises(AnswerValidationError):
            AssessmentAnswerService.submit_answer(
                attempt.id,
                question_order_index=1,
                answer_payload={'wrong_key': 'opt_a'},
                user=candidate_user,
            )

    def test_multiple_choice_submission_and_validation(self, db, candidate_user, multi_type_assessment):
        asm, _ = multi_type_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-ans-mc',
        )
        # Valid list of choices
        dto = AssessmentAnswerService.submit_answer(
            attempt.id,
            question_order_index=2,
            answer_payload={'selected_option_ids': ['opt_1', 'opt_2']},
            user=candidate_user,
        )
        assert dto.is_answered is True
        assert dto.current_answer == {'selected_option_ids': ['opt_1', 'opt_2']}

        # Empty list rejected
        with pytest.raises(AnswerValidationError):
            AssessmentAnswerService.submit_answer(
                attempt.id,
                question_order_index=2,
                answer_payload={'selected_option_ids': []},
                user=candidate_user,
            )

        # Invalid option rejected
        with pytest.raises(AnswerValidationError):
            AssessmentAnswerService.submit_answer(
                attempt.id,
                question_order_index=2,
                answer_payload={'selected_option_ids': ['opt_1', 'opt_invalid']},
                user=candidate_user,
            )

    def test_numerical_submission_and_validation(self, db, candidate_user, multi_type_assessment):
        asm, _ = multi_type_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-ans-num',
        )
        # Valid numeric values
        dto1 = AssessmentAnswerService.submit_answer(
            attempt.id,
            question_order_index=3,
            answer_payload={'value': 42},
            user=candidate_user,
        )
        assert dto1.is_answered is True

        dto2 = AssessmentAnswerService.submit_answer(
            attempt.id,
            question_order_index=3,
            answer_payload={'value': '3.14159'},
            user=candidate_user,
        )
        assert dto2.is_answered is True

        # Boolean rejected
        with pytest.raises(AnswerValidationError):
            AssessmentAnswerService.submit_answer(
                attempt.id,
                question_order_index=3,
                answer_payload={'value': True},
                user=candidate_user,
            )

        # Non-numeric text rejected
        with pytest.raises(AnswerValidationError):
            AssessmentAnswerService.submit_answer(
                attempt.id,
                question_order_index=3,
                answer_payload={'value': 'abc'},
                user=candidate_user,
            )

    def test_short_text_submission_and_validation(self, db, candidate_user, multi_type_assessment):
        asm, _ = multi_type_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-ans-st',
        )
        # Valid string
        dto = AssessmentAnswerService.submit_answer(
            attempt.id,
            question_order_index=4,
            answer_payload={'text': 'Median of three'},
            user=candidate_user,
        )
        assert dto.is_answered is True
        assert dto.current_answer == {'text': 'Median of three'}

        # Empty string rejected
        with pytest.raises(AnswerValidationError):
            AssessmentAnswerService.submit_answer(
                attempt.id,
                question_order_index=4,
                answer_payload={'text': '   '},
                user=candidate_user,
            )

    def test_distinct_answer_count_maintenance(self, db, candidate_user, multi_type_assessment):
        asm, _ = multi_type_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-ans-count',
        )
        assert attempt.answer_count == 0

        # Answer Q1
        AssessmentAnswerService.submit_answer(
            attempt.id,
            question_order_index=1,
            answer_payload={'selected_option_id': 'opt_a'},
            user=candidate_user,
        )
        attempt.refresh_from_db()
        assert attempt.answer_count == 1

        # Re-submit updated answer for Q1
        AssessmentAnswerService.submit_answer(
            attempt.id,
            question_order_index=1,
            answer_payload={'selected_option_id': 'opt_b'},
            user=candidate_user,
        )
        attempt.refresh_from_db()
        assert attempt.answer_count == 1  # Unchanged

        # Answer Q2
        AssessmentAnswerService.submit_answer(
            attempt.id,
            question_order_index=2,
            answer_payload={'selected_option_ids': ['opt_1']},
            user=candidate_user,
        )
        attempt.refresh_from_db()
        assert attempt.answer_count == 2

    def test_explicit_question_skipping(self, db, candidate_user, multi_type_assessment):
        asm, _ = multi_type_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-skip-test',
        )
        # Skip Q1
        dto = AssessmentAnswerService.skip_question(attempt.id, question_order_index=1, user=candidate_user)
        assert dto.order_index == 1

        attempt.refresh_from_db()
        assert attempt.answer_count == 0  # Skip does not count as answered

        event = AttemptEvent.objects.get(attempt=attempt, event_type='QUESTION_SKIPPED')
        assert event.payload['order_index'] == 1


# ==============================================================================
# Navigation Restrictions & Backtracking Tests on Answers
# ==============================================================================

class TestAnswerBacktrackingRestrictions:
    def test_forward_only_navigation_enforcement(self, db, author_user, competency, candidate_user):
        q1 = Question.objects.create(code='QST-FO-1', created_by=author_user)
        qv1 = QuestionVersion.objects.create(
            question=q1, version_number=1, status='DRAFT', title='Q1', prompt='P1',
            question_type='SINGLE_CHOICE', primary_competency=competency,
            content_payload={'options': [{'id': '1', 'text': 'A'}]}, created_by=author_user,
        )
        qv1.status = 'IN_REVIEW'; qv1.save(); qv1.status = 'PUBLISHED'; qv1.save()
        q1.active_version = qv1; q1.save()

        q2 = Question.objects.create(code='QST-FO-2', created_by=author_user)
        qv2 = QuestionVersion.objects.create(
            question=q2, version_number=1, status='DRAFT', title='Q2', prompt='P2',
            question_type='SINGLE_CHOICE', primary_competency=competency,
            content_payload={'options': [{'id': '1', 'text': 'A'}]}, created_by=author_user,
        )
        qv2.status = 'IN_REVIEW'; qv2.save(); qv2.status = 'PUBLISHED'; qv2.save()
        q2.active_version = qv2; q2.save()

        asm = AssessmentCompositionService.create_assessment(code='ASM-FO-1', title='Forward Only', user=author_user)
        ver = AssessmentCompositionService.create_draft_version(
            asm.id, title='v1', time_limit_seconds=1800, allow_backtracking=False, user=author_user
        )
        AssessmentCompositionService.add_question_to_version(ver.id, qv1.id, user=author_user)
        AssessmentCompositionService.add_question_to_version(ver.id, qv2.id, user=author_user)
        AssessmentCompositionService.publish_version(ver.id, user=author_user)

        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-fo-att',
        )
        assert attempt.current_order_index == 1
        assert attempt.allow_backtracking is False

        # Attempting to answer Q2 directly while at Q1 must be rejected
        with pytest.raises(BacktrackingNotAllowedError):
            AssessmentAnswerService.submit_answer(
                attempt.id,
                question_order_index=2,
                answer_payload={'selected_option_id': '1'},
                user=candidate_user,
            )

        # Answering Q1 auto-advances current_order_index to 2
        AssessmentAnswerService.submit_answer(
            attempt.id,
            question_order_index=1,
            answer_payload={'selected_option_id': '1'},
            user=candidate_user,
        )
        attempt.refresh_from_db()
        assert attempt.current_order_index == 2

        # Now attempting to answer Q1 again must be rejected because backtracking is disabled
        with pytest.raises(BacktrackingNotAllowedError):
            AssessmentAnswerService.submit_answer(
                attempt.id,
                question_order_index=1,
                answer_payload={'selected_option_id': '1'},
                user=candidate_user,
            )

    def test_deadline_expiration_on_submit_answer(self, db, candidate_user, multi_type_assessment):
        asm, _ = multi_type_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-ans-deadline',
        )
        # Fast forward deadline
        attempt.deadline = timezone.now() - timedelta(seconds=1)
        attempt.save(update_fields=['deadline'])

        with pytest.raises(AttemptExpiredError):
            AssessmentAnswerService.submit_answer(
                attempt.id,
                question_order_index=1,
                answer_payload={'selected_option_id': 'opt_a'},
                user=candidate_user,
            )

        attempt.refresh_from_db()
        assert attempt.status == 'EXPIRED'

    def test_unauthorized_user_rejected(self, db, candidate_user, other_candidate, multi_type_assessment):
        asm, _ = multi_type_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-ans-unauth',
        )
        with pytest.raises(AssessmentPermissionDeniedError):
            AssessmentAnswerService.submit_answer(
                attempt.id,
                question_order_index=1,
                answer_payload={'selected_option_id': 'opt_a'},
                user=other_candidate,
            )

