"""
Unit and integration tests for AssessmentAttemptService (Milestone 4A - Phase 2D.2 Stages B & D).
Covers:
- Attempt creation, resumption, and mandatory idempotency key handling.
- Active reservation uniqueness: exactly one active attempt per (user, assessment).
- Unlimited retakes after terminal attempts with sequential attempt numbers.
- Exact QuestionVersion pinning and presentation snapshotting.
- Option shuffling and candidate-safe presentation payload.
- Zero leakage of confidential evaluation keys.
- Stage D lifecycle transitions: Submit, Expire, Cancel.
- Strict server-side deadline enforcement without grace periods.
- Terminal-state immutability.
- Transactional reservation cleanup on terminal transition.
- Append-only audit events integrity.
- MySQL deadlock retry (1213) and lock timeout (1205) handler verification.
"""
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch
import uuid

# Ensure backend root is on sys.path
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, OperationalError
from django.utils import timezone

from apps.arena.models import Question, QuestionVersion
from apps.assessments.models import (
    ActiveAssessmentReservation,
    Assessment,
    AssessmentAttempt,
    AssessmentVersion,
    AssessmentVersionQuestion,
    AttemptEvent,
    AttemptQuestion,
)
from apps.assessments.services import (
    ActiveAttemptExistsError,
    AssessmentAttemptService,
    AssessmentCompositionService,
    AssessmentDeprecatedError,
    AssessmentNoActiveVersionError,
    AssessmentPermissionDeniedError,
    AssessmentValidationError,
    AttemptExpiredError,
    AttemptNotFoundError,
    AttemptTerminalError,
    LockTimeoutError,
    with_deadlock_retry,
)
from apps.skills.models import Competency, Domain, Subdomain

User = get_user_model()


@pytest.fixture
def author_user(db):
    return User.objects.create_user(
        email='asm_author@example.com',
        password='TestPassword123!',
        is_staff=True,
    )


@pytest.fixture
def candidate_user(db):
    return User.objects.create_user(
        email='candidate_main@example.com',
        password='TestPassword123!',
    )


@pytest.fixture
def second_candidate(db):
    return User.objects.create_user(
        email='candidate_secondary@example.com',
        password='TestPassword123!',
    )


@pytest.fixture
def competency(db):
    domain = Domain.objects.create(
        slug='sys-design',
        name='System Design',
        category='TECHNICAL',
        description='Architecture domain',
        display_order=1,
    )
    subdomain = Subdomain.objects.create(
        domain=domain,
        slug='concurrency-ctrl',
        name='Concurrency',
        display_order=1,
    )
    return Competency.objects.create(
        subdomain=subdomain,
        code='COMP-CONC-01',
        name='Locks & Deadlocks',
        description='Locking mechanisms',
        bloom_level='APPLY',
    )


@pytest.fixture
def published_assessment(db, author_user, competency):
    """Creates an active published Assessment with 2 pinned questions."""
    q1 = Question.objects.create(code='QST-C-001', created_by=author_user)
    qv1 = QuestionVersion.objects.create(
        question=q1,
        version_number=1,
        status='DRAFT',
        title='Question 1',
        prompt='What causes a deadlock?',
        question_type='SINGLE_CHOICE',
        primary_competency=competency,
        time_limit_seconds=60,
        content_payload={
            'options': [
                {'id': 'opt1', 'text': 'Mutual exclusion'},
                {'id': 'opt2', 'text': 'No mutual exclusion'},
                {'id': 'opt3', 'text': 'Random allocation'},
            ],
        },
        created_by=author_user,
    )
    qv1.status = 'IN_REVIEW'
    qv1.save()
    qv1.status = 'PUBLISHED'
    qv1.save()
    q1.active_version = qv1
    q1.save()

    q2 = Question.objects.create(code='QST-C-002', created_by=author_user)
    qv2 = QuestionVersion.objects.create(
        question=q2,
        version_number=1,
        status='DRAFT',
        title='Question 2',
        prompt='State true or false: Read locks block write locks.',
        question_type='TRUE_FALSE',
        primary_competency=competency,
        time_limit_seconds=45,
        content_payload={
            'options': [{'id': 'true', 'text': 'True'}, {'id': 'false', 'text': 'False'}],
        },
        created_by=author_user,
    )
    qv2.status = 'IN_REVIEW'
    qv2.save()
    qv2.status = 'PUBLISHED'
    qv2.save()
    q2.active_version = qv2
    q2.save()

    asm = AssessmentCompositionService.create_assessment(
        code='ASM-AT-001',
        title='Concurrency Assessment',
        description='Testing attempt service',
        user=author_user,
    )
    ver = AssessmentCompositionService.create_draft_version(
        asm.id,
        title='Version 1.0',
        time_limit_seconds=3600,
        allow_backtracking=True,
        user=author_user,
    )
    AssessmentCompositionService.add_question_to_version(ver.id, qv1.id, weight=Decimal('1.00'), user=author_user)
    AssessmentCompositionService.add_question_to_version(ver.id, qv2.id, weight=Decimal('2.00'), user=author_user)
    AssessmentCompositionService.publish_version(ver.id, user=author_user)
    asm.refresh_from_db()
    return asm, ver, [qv1, qv2]


# ==============================================================================
# Stage B — Attempt Creation and Reservation Tests
# ==============================================================================

class TestAttemptCreationAndReservation:
    def test_start_attempt_success(self, db, candidate_user, published_assessment):
        asm, ver, qvs = published_assessment
        attempt, created = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-start-1',
        )
        assert created is True
        assert attempt.user == candidate_user
        assert attempt.assessment == asm
        assert attempt.assessment_version == ver
        assert attempt.status == 'IN_PROGRESS'
        assert attempt.attempt_number == 1
        assert attempt.question_count == 2
        assert attempt.answer_count == 0
        assert attempt.current_order_index == 1
        assert attempt.time_limit_seconds == 3600
        assert attempt.deadline is not None
        assert attempt.allow_backtracking is True

        # Verify active reservation was created
        res = ActiveAssessmentReservation.objects.get(attempt=attempt)
        assert res.user == candidate_user
        assert res.assessment == asm

        # Verify ATTEMPT_STARTED audit event
        event = AttemptEvent.objects.get(attempt=attempt, event_type='ATTEMPT_STARTED')
        assert event.payload['question_count'] == 2
        assert event.payload['attempt_number'] == 1

    def test_question_snapshotting_and_candidate_confidentiality(self, db, candidate_user, published_assessment):
        asm, _, qvs = published_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-snap-1',
        )
        aqs = list(AttemptQuestion.objects.filter(attempt=attempt).order_by('order_index'))
        assert len(aqs) == 2
        assert aqs[0].question_version == qvs[0]
        assert aqs[0].weight == Decimal('1.00')
        assert aqs[0].prompt_snapshot == qvs[0].prompt
        assert aqs[0].question_type_snapshot == 'SINGLE_CHOICE'
        assert aqs[0].time_limit_seconds_snapshot == 60

        # Verify candidate confidentiality: no confidential keys in snapshot!
        payload = aqs[0].content_payload_snapshot
        assert 'correct_answer' not in payload
        assert 'explanation' not in payload
        assert 'options' in payload
        # Options must have the choices preserved
        option_ids = {opt['id'] for opt in payload['options']}
        assert option_ids == {'opt1', 'opt2', 'opt3'}

        # Verify question 2 confidentiality
        payload2 = aqs[1].content_payload_snapshot
        assert 'scoring_rubric' not in payload2

    def test_idempotent_replay_returns_existing_attempt(self, db, candidate_user, published_assessment):
        asm, _, _ = published_assessment
        attempt1, created1 = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-replay-key',
        )
        assert created1 is True

        attempt2, created2 = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-replay-key',
        )
        assert created2 is False
        assert attempt1.id == attempt2.id

    def test_mandatory_idempotency_key_validation(self, db, candidate_user, published_assessment):
        asm, _, _ = published_assessment
        for bad_key in ['', '   ', None]:
            with pytest.raises(AssessmentValidationError):
                AssessmentAttemptService.start_or_resume_attempt(
                    assessment_id=asm.id,
                    user=candidate_user,
                    idempotency_key=bad_key,
                )

        with pytest.raises(AssessmentValidationError) as exc:
            AssessmentAttemptService.start_or_resume_attempt(
                assessment_id=asm.id,
                user=candidate_user,
                idempotency_key='a' * 65,  # Too long
            )
        assert 'exceed 64 characters' in str(exc.value)

    def test_prevent_second_active_attempt_while_first_in_progress(self, db, candidate_user, published_assessment):
        asm, _, _ = published_assessment
        AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-first',
        )
        with pytest.raises(ActiveAttemptExistsError) as exc:
            AssessmentAttemptService.start_or_resume_attempt(
                assessment_id=asm.id,
                user=candidate_user,
                idempotency_key='idem-second',
            )
        assert 'already in progress' in str(exc.value)

    def test_unlimited_retakes_after_terminal_attempt(self, db, candidate_user, published_assessment):
        asm, _, _ = published_assessment
        # Attempt 1
        att1, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-retake-1',
        )
        assert att1.attempt_number == 1

        # Submit attempt 1
        AssessmentAttemptService.submit_attempt(att1.id, user=candidate_user)

        # Attempt 2 is permitted and receives sequential attempt_number 2
        att2, created2 = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-retake-2',
        )
        assert created2 is True
        assert att2.attempt_number == 2
        assert att2.id != att1.id

    def test_start_attempt_on_deprecated_assessment_rejected(self, db, candidate_user, published_assessment, author_user):
        asm, _, _ = published_assessment
        AssessmentCompositionService.deprecate_assessment(asm.id, user=author_user)
        with pytest.raises(AssessmentDeprecatedError):
            AssessmentAttemptService.start_or_resume_attempt(
                assessment_id=asm.id,
                user=candidate_user,
                idempotency_key='idem-dep',
            )

    def test_start_attempt_no_active_version_rejected(self, db, candidate_user, author_user):
        asm = AssessmentCompositionService.create_assessment(
            code='ASM-NO-ACT',
            title='No Active Version',
            user=author_user,
        )
        with pytest.raises(AssessmentNoActiveVersionError):
            AssessmentAttemptService.start_or_resume_attempt(
                assessment_id=asm.id,
                user=candidate_user,
                idempotency_key='idem-no-act',
            )


# ==============================================================================
# Stage D — Attempt Lifecycle Tests
# ==============================================================================

class TestAttemptLifecycle:
    def test_submit_attempt_success(self, db, candidate_user, published_assessment):
        asm, _, _ = published_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-sub-1',
        )
        summary = AssessmentAttemptService.submit_attempt(attempt.id, user=candidate_user)
        assert summary.status == 'SUBMITTED'
        assert summary.completed_at is not None

        attempt.refresh_from_db()
        assert attempt.status == 'SUBMITTED'
        assert not ActiveAssessmentReservation.objects.filter(attempt=attempt).exists()

        event = AttemptEvent.objects.get(attempt=attempt, event_type='ATTEMPT_SUBMITTED')
        assert event.payload['attempt_number'] == 1

    def test_expire_attempt_success(self, db, candidate_user, published_assessment):
        asm, _, _ = published_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-exp-1',
        )
        summary = AssessmentAttemptService.expire_attempt(attempt.id)
        assert summary.status == 'EXPIRED'
        assert summary.completed_at is not None

        attempt.refresh_from_db()
        assert attempt.status == 'EXPIRED'
        assert not ActiveAssessmentReservation.objects.filter(attempt=attempt).exists()

        event = AttemptEvent.objects.get(attempt=attempt, event_type='ATTEMPT_EXPIRED')
        assert event.event_type == 'ATTEMPT_EXPIRED'

    def test_cancel_attempt_success(self, db, candidate_user, published_assessment):
        asm, _, _ = published_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-can-1',
        )
        summary = AssessmentAttemptService.cancel_attempt(
            attempt.id,
            user=candidate_user,
            reason='Candidate requested cancellation',
        )
        assert summary.status == 'CANCELLED'

        attempt.refresh_from_db()
        assert attempt.status == 'CANCELLED'
        assert not ActiveAssessmentReservation.objects.filter(attempt=attempt).exists()

        event = AttemptEvent.objects.get(attempt=attempt, event_type='ATTEMPT_CANCELLED')
        assert event.payload['reason'] == 'Candidate requested cancellation'

    def test_strict_server_side_deadline_enforcement(self, db, candidate_user, published_assessment):
        asm, _, _ = published_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-deadline-1',
        )
        # Fast-forward deadline into past
        attempt.deadline = timezone.now() - timedelta(seconds=1)
        attempt.save(update_fields=['deadline'])

        # Submitting an expired attempt must expire it and raise AttemptExpiredError
        with pytest.raises(AttemptExpiredError):
            AssessmentAttemptService.submit_attempt(attempt.id, user=candidate_user)

        attempt.refresh_from_db()
        assert attempt.status == 'EXPIRED'

    def test_terminal_state_immutability(self, db, candidate_user, published_assessment):
        asm, _, _ = published_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-term-imm',
        )
        AssessmentAttemptService.submit_attempt(attempt.id, user=candidate_user)

        # Attempting to re-submit must fail
        with pytest.raises(AttemptTerminalError):
            AssessmentAttemptService.submit_attempt(attempt.id, user=candidate_user)

        # Attempting to cancel must fail
        with pytest.raises(AttemptTerminalError):
            AssessmentAttemptService.cancel_attempt(attempt.id, user=candidate_user)

    def test_unauthorized_user_cannot_submit_or_cancel(self, db, candidate_user, second_candidate, published_assessment):
        asm, _, _ = published_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-auth-test',
        )
        with pytest.raises(AssessmentPermissionDeniedError):
            AssessmentAttemptService.submit_attempt(attempt.id, user=second_candidate)

        with pytest.raises(AssessmentPermissionDeniedError):
            AssessmentAttemptService.cancel_attempt(attempt.id, user=second_candidate)


# ==============================================================================
# Concurrency & Deadlock Retry Tests
# ==============================================================================

class TestDeadlockAndLockTimeoutHandling:
    def test_retry_on_mysql_1213_deadlock(self):
        call_count = 0

        @with_deadlock_retry(max_retries=3, initial_delay=0.01)
        def simulated_deadlock_op():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise OperationalError(1213, "Deadlock found when trying to get lock")
            return "SUCCESS"

        result = simulated_deadlock_op()
        assert result == "SUCCESS"
        assert call_count == 3

    def test_fail_fast_on_mysql_1205_lock_timeout(self):
        call_count = 0

        @with_deadlock_retry(max_retries=3, initial_delay=0.01)
        def simulated_timeout_op():
            nonlocal call_count
            call_count += 1
            raise OperationalError(1205, "Lock wait timeout exceeded; try restarting transaction")

        with pytest.raises(LockTimeoutError) as exc:
            simulated_timeout_op()

        # Must fail fast without retries
        assert call_count == 1
        assert exc.value.details.get('code') == 1205
