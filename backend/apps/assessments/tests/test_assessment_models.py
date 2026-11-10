"""
Unit and integration tests for apps.assessments data models, constraints, and database policies.
Covers:
- Assessment permanent catalog identity, deprecation state, and active-version ownership invariants.
- AssessmentVersion approved lifecycle transitions (DRAFT -> PUBLISHED -> ARCHIVED), immutability, and duration configuration.
- AssessmentVersionQuestion uniqueness, canonical question deduplication, and published immutability.
- AssessmentAttempt consistency, mandatory idempotency, historical uniqueness, and counter constraints.
- Approved attempt states (IN_PROGRESS, SUBMITTED, EXPIRED, CANCELLED).
- ActiveAssessmentReservation unconditional unique constraint and concurrent attempt prevention.
- AttemptQuestion presentation snapshots, ordering, and canonical Question validation.
- AttemptAnswer 1-to-1 enforcement per attempt question.
- AttemptEvent append-only audit log guarantees and bulk update prevention.
- Database-level FK PROTECT vs CASCADE deletion policies.
- Database-level status check constraints.
"""
import sys
import uuid
from decimal import Decimal
from pathlib import Path

# Ensure backend root is on sys.path
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from apps.arena.models import Question, QuestionVersion
from apps.assessments.models import (
    ActiveAssessmentReservation,
    Assessment,
    AssessmentAttempt,
    AssessmentVersion,
    AssessmentVersionQuestion,
    AttemptAnswer,
    AttemptEvent,
    AttemptQuestion,
)
from apps.skills.models import Competency, Domain, Subdomain

User = get_user_model()


@pytest.fixture
def author_user(db):
    return User.objects.create_user(
        email='assessment_author@example.com',
        password='TestPassword123!',
    )


@pytest.fixture
def candidate_user(db):
    return User.objects.create_user(
        email='candidate_one@example.com',
        password='TestPassword123!',
    )


@pytest.fixture
def second_candidate(db):
    return User.objects.create_user(
        email='candidate_two@example.com',
        password='TestPassword123!',
    )


@pytest.fixture
def competency(db):
    domain = Domain.objects.create(
        slug='system-architecture',
        name='System Architecture',
        category='TECHNICAL',
        description='Architecture domain',
        display_order=1,
    )
    subdomain = Subdomain.objects.create(
        domain=domain,
        slug='database-design',
        name='Database Design',
        display_order=1,
    )
    return Competency.objects.create(
        subdomain=subdomain,
        code='DB-ACID-01',
        name='ACID Principles & Isolation Levels',
        description='Transactional integrity and concurrency.',
        bloom_level='APPLY',
    )


@pytest.fixture
def question_series(db, author_user, competency):
    """Creates a canonical Question and a published QuestionVersion."""
    q = Question.objects.create(
        code='QST-DB-001',
        created_by=author_user,
    )
    qv = QuestionVersion.objects.create(
        question=q,
        version_number=1,
        status='DRAFT',
        title='Transaction Isolation Levels',
        prompt='Which isolation level prevents phantom reads?',
        question_type='SINGLE_CHOICE',
        difficulty_tier='INTERMEDIATE',
        primary_competency=competency,
        time_limit_seconds=90,
        content_payload={'options': [{'id': 'opt1', 'text': 'Serializable'}]},
        created_by=author_user,
    )
    qv.status = 'IN_REVIEW'
    qv.save()
    qv.status = 'PUBLISHED'
    qv.save()
    q.active_version = qv
    q.save()
    return q, qv


@pytest.fixture
def second_question_series(db, author_user, competency):
    """Creates a second canonical Question and published QuestionVersion."""
    q = Question.objects.create(
        code='QST-DB-002',
        created_by=author_user,
    )
    qv = QuestionVersion.objects.create(
        question=q,
        version_number=1,
        status='DRAFT',
        title='Write-Ahead Logging Mechanics',
        prompt='What is the primary role of the WAL?',
        question_type='SINGLE_CHOICE',
        difficulty_tier='ADVANCED',
        primary_competency=competency,
        time_limit_seconds=120,
        content_payload={'options': [{'id': 'opt1', 'text': 'Durability'}]},
        created_by=author_user,
    )
    qv.status = 'IN_REVIEW'
    qv.save()
    qv.status = 'PUBLISHED'
    qv.save()
    q.active_version = qv
    q.save()
    return q, qv


@pytest.fixture
def published_assessment_setup(db, author_user, question_series, second_question_series):
    """Creates a complete published Assessment with two questions using approved DRAFT -> PUBLISHED lifecycle."""
    _, qv1 = question_series
    _, qv2 = second_question_series

    asm = Assessment.objects.create(
        code='ASM-SYS-001',
        title='Systems & Database Architecture Benchmark',
        description='Standardized evaluation of transactional fundamentals.',
        created_by=author_user,
    )
    ver = AssessmentVersion.objects.create(
        assessment=asm,
        version_number=1,
        status='DRAFT',
        title='Benchmark v1.0',
        description='Standard exam syllabus.',
        time_limit_seconds=3600,
        allow_backtracking=True,
        created_by=author_user,
    )
    avq1 = AssessmentVersionQuestion.objects.create(
        assessment_version=ver,
        question_version=qv1,
        order_index=1,
        weight=Decimal('1.00'),
    )
    avq2 = AssessmentVersionQuestion.objects.create(
        assessment_version=ver,
        question_version=qv2,
        order_index=2,
        weight=Decimal('2.00'),
    )
    # Direct approved transition: DRAFT -> PUBLISHED
    ver.status = 'PUBLISHED'
    ver.save()

    asm.active_version = ver
    asm.save()

    return asm, ver, [avq1, avq2]


# ==============================================================================
# 1. Assessment Model Tests
# ==============================================================================

class TestAssessmentModel:
    def test_assessment_creation_and_defaults(self, db, author_user):
        asm = Assessment.objects.create(
            code='ASM-TEST-001',
            title='Test Assessment',
            description='Test scope',
            created_by=author_user,
        )
        assert isinstance(asm.id, uuid.UUID)
        assert asm.is_deprecated is False
        assert asm.active_version is None
        assert str(asm) == 'ASM-TEST-001 - Test Assessment'

    def test_assessment_code_immutable_after_creation(self, db, author_user):
        asm = Assessment.objects.create(
            code='ASM-IMM-001',
            title='Immutable Code Assessment',
            created_by=author_user,
        )
        asm.code = 'ASM-MUTATED-001'
        with pytest.raises(ValidationError) as exc:
            asm.clean()
        assert 'code' in exc.value.error_dict

    def test_assessment_code_uniqueness_constraint(self, db, author_user):
        Assessment.objects.create(
            code='ASM-DUP-001',
            title='Original Assessment',
            created_by=author_user,
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Assessment.objects.create(
                    code='ASM-DUP-001',
                    title='Duplicate Code Assessment',
                    created_by=author_user,
                )

    def test_assessment_active_version_ownership_validation(self, db, author_user):
        asm1 = Assessment.objects.create(code='ASM-A-001', title='Assessment A')
        asm2 = Assessment.objects.create(code='ASM-B-001', title='Assessment B')

        ver2 = AssessmentVersion.objects.create(
            assessment=asm2,
            version_number=1,
            status='DRAFT',
            title='Version on B',
        )
        ver2.status = 'PUBLISHED'
        ver2.save()

        # Attempting to assign ver2 (belonging to asm2) as active_version on asm1
        asm1.active_version = ver2
        with pytest.raises(ValidationError) as exc:
            asm1.clean()
        assert 'active_version' in exc.value.error_dict
        assert "belong to this assessment" in str(exc.value)

    def test_assessment_active_version_must_be_published(self, db, author_user):
        asm = Assessment.objects.create(code='ASM-PUB-001', title='Assessment')
        ver = AssessmentVersion.objects.create(
            assessment=asm,
            version_number=1,
            status='DRAFT',
            title='Draft Version',
        )
        asm.active_version = ver
        with pytest.raises(ValidationError) as exc:
            asm.clean()
        assert 'active_version' in exc.value.error_dict
        assert "PUBLISHED" in str(exc.value)

    def test_deprecated_assessment_cannot_have_active_version(self, db, published_assessment_setup):
        asm, ver, _ = published_assessment_setup
        assert asm.active_version == ver

        asm.is_deprecated = True
        with pytest.raises(ValidationError) as exc:
            asm.clean()
        assert 'active_version' in exc.value.error_dict
        assert "deprecated assessment cannot have an active version" in str(exc.value)


# ==============================================================================
# 2. AssessmentVersion Model Tests
# ==============================================================================

class TestAssessmentVersionModel:
    def test_initial_version_must_be_draft(self, db, author_user):
        asm = Assessment.objects.create(code='ASM-VER-001', title='Version Test')
        with pytest.raises(ValidationError) as exc:
            AssessmentVersion.objects.create(
                assessment=asm,
                version_number=1,
                status='PUBLISHED',
                title='Illegal Initial Published Version',
            )
        assert 'status' in exc.value.error_dict

    def test_version_number_uniqueness_per_assessment(self, db, author_user):
        asm = Assessment.objects.create(code='ASM-VER-002', title='Version Test')
        AssessmentVersion.objects.create(
            assessment=asm,
            version_number=1,
            status='DRAFT',
            title='Version 1',
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                AssessmentVersion.objects.create(
                    assessment=asm,
                    version_number=1,
                    status='DRAFT',
                    title='Duplicate Version 1',
                )

    def test_version_number_greater_than_zero_constraint(self, db, author_user):
        asm = Assessment.objects.create(code='ASM-VER-003', title='Version Test')
        with pytest.raises((ValidationError, IntegrityError)):
            with transaction.atomic():
                ver = AssessmentVersion(
                    assessment=asm,
                    version_number=0,
                    status='DRAFT',
                    title='Version 0',
                )
                ver.full_clean()
                ver.save()

    def test_approved_lifecycle_transitions(self, db, author_user):
        """Approved lifecycle: DRAFT -> PUBLISHED -> ARCHIVED."""
        asm = Assessment.objects.create(code='ASM-LIF-001', title='Lifecycle Test')
        ver = AssessmentVersion.objects.create(
            assessment=asm,
            version_number=1,
            status='DRAFT',
            title='Draft Version',
        )
        assert ver.published_at is None

        # DRAFT -> PUBLISHED
        ver.status = 'PUBLISHED'
        ver.save()
        assert ver.status == 'PUBLISHED'
        assert ver.published_at is not None

        # PUBLISHED -> ARCHIVED
        ver.status = 'ARCHIVED'
        ver.save()
        assert ver.status == 'ARCHIVED'

    def test_invalid_lifecycle_transition_raises_validation_error(self, db, author_user):
        asm = Assessment.objects.create(code='ASM-LIF-002', title='Invalid Transition')
        ver = AssessmentVersion.objects.create(
            assessment=asm,
            version_number=1,
            status='DRAFT',
            title='Draft Version',
        )
        # Direct DRAFT -> ARCHIVED is forbidden
        ver.status = 'ARCHIVED'
        with pytest.raises(ValidationError) as exc:
            ver.save()
        assert 'status' in exc.value.error_dict

        # Unapproved states (like IN_REVIEW or DEPRECATED) must be rejected
        ver.status = 'IN_REVIEW'
        with pytest.raises(ValidationError) as exc:
            ver.clean()
        assert 'status' in exc.value.error_dict

    def test_version_status_database_check_constraint(self, db, author_user):
        asm = Assessment.objects.create(code='ASM-CHK-001', title='Check Constraint Test')
        ver = AssessmentVersion(
            assessment=asm,
            version_number=1,
            status='UNAPPROVED_STATUS',
            title='Bad Status',
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                super(AssessmentVersion, ver).save()

    def test_published_version_immutability(self, db, author_user):
        asm = Assessment.objects.create(code='ASM-IMM-002', title='Immutability Test')
        ver = AssessmentVersion.objects.create(
            assessment=asm,
            version_number=1,
            status='DRAFT',
            title='Original Title',
            description='Original Description',
            time_limit_seconds=1800,
            allow_backtracking=True,
        )
        ver.status = 'PUBLISHED'
        ver.save()

        # Attempt to modify title
        ver.title = 'Mutated Title'
        with pytest.raises(ValidationError) as exc:
            ver.save()
        assert 'immutable' in str(exc.value)

        # Revert title and attempt to modify time_limit_seconds
        ver.title = 'Original Title'
        ver.time_limit_seconds = 3600
        with pytest.raises(ValidationError) as exc:
            ver.save()
        assert 'time_limit_seconds' in str(exc.value)

    def test_duration_minutes_property(self, db, author_user):
        asm = Assessment.objects.create(code='ASM-DUR-001', title='Duration Test')
        ver = AssessmentVersion(
            assessment=asm,
            version_number=1,
            status='DRAFT',
            title='Timed Version',
            time_limit_seconds=5400,
        )
        assert ver.duration_minutes == 90

        untimed_ver = AssessmentVersion(
            assessment=asm,
            version_number=2,
            status='DRAFT',
            title='Untimed Version',
            time_limit_seconds=None,
        )
        assert untimed_ver.duration_minutes is None

    def test_reconciliation_clears_active_version_when_archived(self, db, published_assessment_setup):
        asm, ver, _ = published_assessment_setup
        assert asm.active_version == ver

        # Transition active version to ARCHIVED
        ver.status = 'ARCHIVED'
        ver.save()

        asm.refresh_from_db()
        # Invariant: active_version cannot reference an archived version
        assert asm.active_version is None

    def test_reconciliation_never_restores_deprecated_assessment(self, db, published_assessment_setup):
        asm, ver, _ = published_assessment_setup
        asm.active_version = None
        asm.is_deprecated = True
        asm.save()

        # Archiving a version on a deprecated assessment must never set active_version
        ver.status = 'ARCHIVED'
        ver.save()

        asm.refresh_from_db()
        assert asm.active_version is None


# ==============================================================================
# 3. AssessmentVersionQuestion Model Tests
# ==============================================================================

class TestAssessmentVersionQuestionModel:
    def test_exact_question_version_foreign_key(self, db, author_user, question_series):
        _, qv = question_series
        asm = Assessment.objects.create(code='ASM-AVQ-001', title='Question Composition')
        ver = AssessmentVersion.objects.create(
            assessment=asm,
            version_number=1,
            status='DRAFT',
            title='Draft Composition',
        )
        avq = AssessmentVersionQuestion.objects.create(
            assessment_version=ver,
            question_version=qv,
            order_index=1,
            weight=Decimal('1.50'),
        )
        assert avq.question_version == qv
        assert avq.question_version_id == qv.id
        assert not hasattr(avq, 'question_id')  # Redundant question FK removed

    def test_prevent_two_versions_of_same_canonical_question(self, db, author_user, question_series, competency):
        q, qv1 = question_series

        # Create a second published version of the same Question series
        qv2 = QuestionVersion.objects.create(
            question=q,
            version_number=2,
            status='DRAFT',
            title='Transaction Isolation v2',
            prompt='Updated prompt text',
            question_type='SINGLE_CHOICE',
            difficulty_tier='ADVANCED',
            primary_competency=competency,
            created_by=author_user,
        )
        qv2.status = 'IN_REVIEW'
        qv2.save()
        qv2.status = 'PUBLISHED'
        qv2.save()

        asm = Assessment.objects.create(code='ASM-AVQ-003', title='Canonical Dedup Test')
        ver = AssessmentVersion.objects.create(
            assessment=asm,
            version_number=1,
            status='DRAFT',
            title='Draft',
        )
        # Add question version 1
        AssessmentVersionQuestion.objects.create(
            assessment_version=ver,
            question_version=qv1,
            order_index=1,
            weight=Decimal('1.00'),
        )

        # Attempt to add question version 2 of the same canonical question
        avq_dup = AssessmentVersionQuestion(
            assessment_version=ver,
            question_version=qv2,
            order_index=2,
            weight=Decimal('1.00'),
        )
        with pytest.raises(ValidationError) as exc:
            avq_dup.clean()
        assert 'question_version' in exc.value.error_dict
        assert "canonical Question" in str(exc.value)

    def test_order_index_uniqueness_in_assessment_version(self, db, author_user, question_series, second_question_series):
        _, qv1 = question_series
        _, qv2 = second_question_series
        asm = Assessment.objects.create(code='ASM-AVQ-004', title='Order Uniqueness')
        ver = AssessmentVersion.objects.create(
            assessment=asm,
            version_number=1,
            status='DRAFT',
            title='Draft',
        )
        AssessmentVersionQuestion.objects.create(
            assessment_version=ver,
            question_version=qv1,
            order_index=1,
            weight=Decimal('1.00'),
        )
        dup_order = AssessmentVersionQuestion(
            assessment_version=ver,
            question_version=qv2,
            order_index=1,  # Duplicate order
            weight=Decimal('2.00'),
        )
        with pytest.raises(ValidationError) as exc:
            dup_order.clean()
        assert 'order_index' in exc.value.error_dict

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                super(AssessmentVersionQuestion, dup_order).save()

    def test_numeric_ranges_and_constraints(self, db, author_user, question_series):
        _, qv = question_series
        asm = Assessment.objects.create(code='ASM-NUM-001', title='Numeric Constraint Test')
        ver = AssessmentVersion.objects.create(
            assessment=asm,
            version_number=1,
            status='DRAFT',
            title='Draft',
        )
        # order_index < 1 must fail
        with pytest.raises((ValidationError, IntegrityError)):
            with transaction.atomic():
                bad_order = AssessmentVersionQuestion(
                    assessment_version=ver,
                    question_version=qv,
                    order_index=0,
                    weight=Decimal('1.00'),
                )
                bad_order.full_clean()
                bad_order.save()

        # weight <= 0 must fail
        with pytest.raises((ValidationError, IntegrityError)):
            with transaction.atomic():
                bad_weight = AssessmentVersionQuestion(
                    assessment_version=ver,
                    question_version=qv,
                    order_index=1,
                    weight=Decimal('0.00'),
                )
                bad_weight.full_clean()
                bad_weight.save()

    def test_cannot_modify_or_delete_questions_on_published_version(self, db, published_assessment_setup, question_series):
        _, ver, questions = published_assessment_setup
        q1_item = questions[0]

        # Cannot edit weight on published assessment version
        q1_item.weight = Decimal('5.00')
        with pytest.raises(ValidationError) as exc:
            q1_item.save()
        assert "Cannot modify questions" in str(exc.value)

        # Cannot delete questions from published assessment version
        with pytest.raises(ValidationError) as exc:
            q1_item.delete()
        assert "Cannot remove questions" in str(exc.value)


# ==============================================================================
# 4. AssessmentAttempt Model Tests
# ==============================================================================

class TestAssessmentAttemptModel:
    def test_attempt_creation_and_defaults(self, db, candidate_user, published_assessment_setup):
        asm, ver, questions = published_assessment_setup
        attempt = AssessmentAttempt.objects.create(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            idempotency_key='idem-key-001',
            question_count=len(questions),
        )
        assert isinstance(attempt.id, uuid.UUID)
        assert attempt.status == 'IN_PROGRESS'
        assert attempt.current_order_index == 1
        assert attempt.answer_count == 0
        assert attempt.started_at is not None
        assert attempt.completed_at is None
        # Snapshotted from ver
        assert attempt.time_limit_seconds == 3600
        assert attempt.allow_backtracking is True

    def test_approved_attempt_statuses(self, db, candidate_user, published_assessment_setup):
        """Approved statuses: IN_PROGRESS, SUBMITTED, EXPIRED, CANCELLED."""
        asm, ver, _ = published_assessment_setup
        for idx, status in enumerate(['IN_PROGRESS', 'SUBMITTED', 'EXPIRED', 'CANCELLED'], start=1):
            att = AssessmentAttempt.objects.create(
                user=candidate_user,
                assessment=asm,
                assessment_version=ver,
                attempt_number=idx,
                idempotency_key=f'idem-status-{status}',
                status=status,
            )
            assert att.status == status

    def test_invalid_attempt_status_database_check_constraint(self, db, candidate_user, published_assessment_setup):
        asm, ver, _ = published_assessment_setup
        att = AssessmentAttempt(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            idempotency_key='idem-bad-status',
            status='COMPLETED',  # Replaced obsolete status must fail check constraint
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                super(AssessmentAttempt, att).save()

    def test_attempt_assessment_and_version_mismatch_raises_error(self, db, candidate_user, published_assessment_setup):
        asm1, ver1, _ = published_assessment_setup
        asm2 = Assessment.objects.create(code='ASM-OTHER-001', title='Other Assessment')

        attempt = AssessmentAttempt(
            user=candidate_user,
            assessment=asm2,  # Mismatch: ver1 belongs to asm1
            assessment_version=ver1,
            attempt_number=1,
            idempotency_key='idem-key-mismatch',
        )
        with pytest.raises(ValidationError) as exc:
            attempt.clean()
        assert 'assessment_version' in exc.value.error_dict

    def test_mandatory_idempotency_key(self, db, candidate_user, published_assessment_setup):
        asm, ver, _ = published_assessment_setup
        attempt = AssessmentAttempt(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            idempotency_key='   ',  # Blank key
        )
        with pytest.raises(ValidationError) as exc:
            attempt.clean()
        assert 'idempotency_key' in exc.value.error_dict

    def test_historical_idempotency_uniqueness(self, db, candidate_user, published_assessment_setup):
        asm, ver, _ = published_assessment_setup
        AssessmentAttempt.objects.create(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            idempotency_key='idem-key-unique',
        )
        # Same user, assessment, and idempotency key
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                AssessmentAttempt.objects.create(
                    user=candidate_user,
                    assessment=asm,
                    assessment_version=ver,
                    attempt_number=2,
                    idempotency_key='idem-key-unique',
                )

    def test_attempt_number_uniqueness_per_user_assessment(self, db, candidate_user, published_assessment_setup):
        asm, ver, _ = published_assessment_setup
        AssessmentAttempt.objects.create(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            idempotency_key='idem-1',
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                AssessmentAttempt.objects.create(
                    user=candidate_user,
                    assessment=asm,
                    assessment_version=ver,
                    attempt_number=1,  # Duplicate attempt number
                    idempotency_key='idem-2',
                )

    def test_attempt_number_greater_than_zero_constraint(self, db, candidate_user, published_assessment_setup):
        asm, ver, _ = published_assessment_setup
        with pytest.raises((ValidationError, IntegrityError)):
            with transaction.atomic():
                att = AssessmentAttempt(
                    user=candidate_user,
                    assessment=asm,
                    assessment_version=ver,
                    attempt_number=0,
                    idempotency_key='idem-zero',
                )
                att.full_clean()
                att.save()

    def test_counters_and_answer_count_lte_question_count(self, db, candidate_user, published_assessment_setup):
        asm, ver, _ = published_assessment_setup
        attempt = AssessmentAttempt(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            idempotency_key='idem-counts',
            question_count=2,
            answer_count=3,
        )
        with pytest.raises(ValidationError) as exc:
            attempt.clean()
        assert 'answer_count' in exc.value.error_dict

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                super(AssessmentAttempt, attempt).save()

    def test_terminal_statuses_auto_set_completed_at(self, db, candidate_user, published_assessment_setup):
        asm, ver, _ = published_assessment_setup
        for terminal_status in ['SUBMITTED', 'EXPIRED', 'CANCELLED']:
            attempt = AssessmentAttempt.objects.create(
                user=candidate_user,
                assessment=asm,
                assessment_version=ver,
                attempt_number=10 + ['SUBMITTED', 'EXPIRED', 'CANCELLED'].index(terminal_status),
                idempotency_key=f'idem-term-{terminal_status}',
            )
            assert attempt.completed_at is None

            attempt.status = terminal_status
            attempt.save()
            assert attempt.completed_at is not None


# ==============================================================================
# 5. ActiveAssessmentReservation Model Tests
# ==============================================================================

class TestActiveAssessmentReservationModel:
    def test_active_reservation_creation_and_auto_alignment(self, db, candidate_user, published_assessment_setup):
        asm, ver, _ = published_assessment_setup
        attempt = AssessmentAttempt.objects.create(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            idempotency_key='idem-res-1',
        )
        reservation = ActiveAssessmentReservation.objects.create(
            attempt=attempt,
        )
        assert reservation.user == candidate_user
        assert reservation.assessment == asm
        assert reservation.idempotency_key == 'idem-res-1'
        assert str(reservation).startswith('ActiveReservation:')

    def test_unconditional_unique_reservation_constraint(self, db, candidate_user, published_assessment_setup):
        asm, ver, _ = published_assessment_setup
        attempt1 = AssessmentAttempt.objects.create(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            idempotency_key='idem-res-1',
        )
        attempt2 = AssessmentAttempt.objects.create(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=2,
            idempotency_key='idem-res-2',
        )
        # Create first active reservation
        ActiveAssessmentReservation.objects.create(attempt=attempt1)

        # Attempting a second active reservation for the SAME user & assessment must fail at DB level
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                ActiveAssessmentReservation.objects.create(attempt=attempt2)

    def test_reservation_cleanup_permits_subsequent_attempt(self, db, candidate_user, published_assessment_setup):
        asm, ver, _ = published_assessment_setup
        attempt1 = AssessmentAttempt.objects.create(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            idempotency_key='idem-res-1',
        )
        res1 = ActiveAssessmentReservation.objects.create(attempt=attempt1)

        # Submit attempt 1 and clear reservation
        attempt1.status = 'SUBMITTED'
        attempt1.save()
        res1.delete()

        # Subsequent attempt can now obtain a reservation
        attempt2 = AssessmentAttempt.objects.create(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=2,
            idempotency_key='idem-res-2',
        )
        res2 = ActiveAssessmentReservation.objects.create(attempt=attempt2)
        assert res2.attempt == attempt2

    def test_reservation_validation_rejects_non_in_progress_attempt(self, db, candidate_user, published_assessment_setup):
        asm, ver, _ = published_assessment_setup
        attempt = AssessmentAttempt.objects.create(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            idempotency_key='idem-res-sub',
            status='SUBMITTED',
        )
        res = ActiveAssessmentReservation(attempt=attempt)
        with pytest.raises(ValidationError) as exc:
            res.clean()
        assert 'attempt' in exc.value.error_dict

    def test_attempt_save_terminal_status_cleans_up_reservation(self, db, candidate_user, published_assessment_setup):
        asm, ver, _ = published_assessment_setup
        attempt = AssessmentAttempt.objects.create(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            idempotency_key='idem-res-clean',
            status='IN_PROGRESS',
        )
        res = ActiveAssessmentReservation.objects.create(attempt=attempt)
        res_id = res.id

        # Transitioning attempt to terminal status SUBMITTED deletes the reservation
        attempt.status = 'SUBMITTED'
        attempt.save()

        assert not ActiveAssessmentReservation.objects.filter(id=res_id).exists()


# ==============================================================================
# 6. AttemptQuestion Model Tests
# ==============================================================================

class TestAttemptQuestionModel:
    def test_snapshot_auto_population(self, db, candidate_user, published_assessment_setup, question_series):
        asm, ver, _ = published_assessment_setup
        _, qv1 = question_series
        attempt = AssessmentAttempt.objects.create(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            idempotency_key='idem-aq-1',
        )
        aq = AttemptQuestion.objects.create(
            attempt=attempt,
            question_version=qv1,
            order_index=1,
            weight=Decimal('1.00'),
        )
        assert aq.question_version == qv1
        assert not hasattr(aq, 'question_id')  # Redundant question FK removed
        assert aq.prompt_snapshot == qv1.prompt
        assert aq.content_payload_snapshot == qv1.content_payload
        assert aq.question_type_snapshot == qv1.question_type
        assert aq.time_limit_seconds_snapshot == qv1.time_limit_seconds

    def test_duplicate_canonical_question_in_attempt_rejected(self, db, candidate_user, published_assessment_setup, question_series, competency, author_user):
        asm, ver, _ = published_assessment_setup
        q1, qv1 = question_series
        attempt = AssessmentAttempt.objects.create(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            idempotency_key='idem-aq-dup',
        )
        # Create second version of q1
        qv1_v2 = QuestionVersion.objects.create(
            question=q1,
            version_number=2,
            status='DRAFT',
            title='Title v2',
            prompt='Prompt v2',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
            created_by=author_user,
        )
        qv1_v2.status = 'IN_REVIEW'
        qv1_v2.save()
        qv1_v2.status = 'PUBLISHED'
        qv1_v2.save()

        AttemptQuestion.objects.create(
            attempt=attempt,
            question_version=qv1,
            order_index=1,
            weight=Decimal('1.00'),
        )
        dup_aq = AttemptQuestion(
            attempt=attempt,
            question_version=qv1_v2,
            order_index=2,
            weight=Decimal('1.00'),
        )
        with pytest.raises(ValidationError) as exc:
            dup_aq.clean()
        assert 'question_version' in exc.value.error_dict

    def test_order_index_uniqueness_in_attempt(self, db, candidate_user, published_assessment_setup, question_series, second_question_series):
        asm, ver, _ = published_assessment_setup
        _, qv1 = question_series
        _, qv2 = second_question_series
        attempt = AssessmentAttempt.objects.create(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            idempotency_key='idem-aq-order',
        )
        AttemptQuestion.objects.create(
            attempt=attempt,
            question_version=qv1,
            order_index=1,
            weight=Decimal('1.00'),
        )
        dup_order = AttemptQuestion(
            attempt=attempt,
            question_version=qv2,
            order_index=1,  # Same order_index
            weight=Decimal('1.00'),
        )
        with pytest.raises(ValidationError) as exc:
            dup_order.clean()
        assert 'order_index' in exc.value.error_dict

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                super(AttemptQuestion, dup_order).save()


# ==============================================================================
# 7. AttemptAnswer Model Tests
# ==============================================================================

class TestAttemptAnswerModel:
    def test_enforce_one_answer_per_attempt_question(self, db, candidate_user, published_assessment_setup, question_series):
        asm, ver, _ = published_assessment_setup
        _, qv1 = question_series
        attempt = AssessmentAttempt.objects.create(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            idempotency_key='idem-ans-1',
        )
        aq = AttemptQuestion.objects.create(
            attempt=attempt,
            question_version=qv1,
            order_index=1,
            weight=Decimal('1.00'),
        )
        ans1 = AttemptAnswer.objects.create(
            attempt_question=aq,
            answer_payload={'selected_option_id': 'opt1'},
        )
        assert ans1.is_answered is True
        assert ans1.answered_at is not None

        # Second answer record for same AttemptQuestion must fail
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                AttemptAnswer.objects.create(
                    attempt_question=aq,
                    answer_payload={'selected_option_id': 'opt2'},
                )


# ==============================================================================
# 8. AttemptEvent Model Tests
# ==============================================================================

class TestAttemptEventModel:
    def test_event_creation_and_ordering(self, db, candidate_user, published_assessment_setup):
        asm, ver, _ = published_assessment_setup
        attempt = AssessmentAttempt.objects.create(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            idempotency_key='idem-evt-1',
        )
        evt1 = AttemptEvent.objects.create(
            attempt=attempt,
            event_type='ATTEMPT_STARTED',
            payload={'client_start': True},
        )
        evt2 = AttemptEvent.objects.create(
            attempt=attempt,
            event_type='QUESTION_NAVIGATED',
            payload={'target_order': 2},
        )
        assert isinstance(evt1.id, uuid.UUID)
        assert evt1.created_at <= evt2.created_at

    def test_attempt_event_append_only_save_immutability(self, db, candidate_user, published_assessment_setup):
        asm, ver, _ = published_assessment_setup
        attempt = AssessmentAttempt.objects.create(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            idempotency_key='idem-evt-mut',
        )
        evt = AttemptEvent.objects.create(
            attempt=attempt,
            event_type='ATTEMPT_STARTED',
            payload={'started': True},
        )
        # Attempt to modify payload
        evt.payload = {'started': False, 'tampered': True}
        with pytest.raises(ValidationError) as exc:
            evt.save()
        assert "append-only" in str(exc.value)

    def test_attempt_event_queryset_update_prevention(self, db, candidate_user, published_assessment_setup):
        asm, ver, _ = published_assessment_setup
        attempt = AssessmentAttempt.objects.create(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            idempotency_key='idem-evt-qs',
        )
        AttemptEvent.objects.create(
            attempt=attempt,
            event_type='ATTEMPT_STARTED',
            payload={'q': 1},
        )
        with pytest.raises(ValidationError) as exc:
            AttemptEvent.objects.filter(attempt=attempt).update(event_type='TAMPERED')
        assert "append-only" in str(exc.value)

    def test_attempt_event_instance_delete_prevention(self, db, candidate_user, published_assessment_setup):
        asm, ver, _ = published_assessment_setup
        attempt = AssessmentAttempt.objects.create(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            idempotency_key='idem-evt-del-inst',
        )
        evt = AttemptEvent.objects.create(
            attempt=attempt,
            event_type='ATTEMPT_STARTED',
            payload={'q': 1},
        )
        with pytest.raises(ValidationError) as exc:
            evt.delete()
        assert "append-only" in str(exc.value)

    def test_attempt_event_queryset_delete_prevention(self, db, candidate_user, published_assessment_setup):
        asm, ver, _ = published_assessment_setup
        attempt = AssessmentAttempt.objects.create(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            idempotency_key='idem-evt-del-qs',
        )
        AttemptEvent.objects.create(
            attempt=attempt,
            event_type='ATTEMPT_STARTED',
            payload={'q': 1},
        )
        with pytest.raises(ValidationError) as exc:
            AttemptEvent.objects.filter(attempt=attempt).delete()
        assert "append-only" in str(exc.value)

    def test_attempt_event_admin_delete_permission_disabled(self):
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory
        from apps.assessments.admin import AttemptEventAdmin, AttemptEventInline

        site = AdminSite()
        admin_obj = AttemptEventAdmin(AttemptEvent, site)
        inline_obj = AttemptEventInline(AssessmentAttempt, site)
        request = RequestFactory().get('/admin/')

        assert admin_obj.has_delete_permission(request) is False
        assert admin_obj.has_add_permission(request) is False
        assert admin_obj.has_change_permission(request) is False
        assert inline_obj.has_delete_permission(request) is False

    def test_attempt_event_audit_trail_preserved_against_parent_deletion(self, db, candidate_user, published_assessment_setup):
        """
        Verify that an AssessmentAttempt cannot be deleted via ORM when AttemptEvents exist,
        and that the audit trail remains intact and immutable.
        """
        asm, ver, _ = published_assessment_setup
        attempt = AssessmentAttempt.objects.create(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            idempotency_key='idem-evt-preserv',
        )
        evt1 = AttemptEvent.objects.create(
            attempt=attempt,
            event_type='ATTEMPT_STARTED',
            payload={'question_order': 1},
        )
        evt2 = AttemptEvent.objects.create(
            attempt=attempt,
            event_type='ANSWER_SUBMITTED',
            payload={'question_order': 1, 'answered': True},
        )

        # 1. Attempt deletion is blocked by ProtectedError
        with pytest.raises(ProtectedError):
            attempt.delete()

        # 2. Both audit events and parent attempt remain intact
        assert AssessmentAttempt.objects.filter(pk=attempt.pk).exists()
        assert AttemptEvent.objects.filter(pk=evt1.pk).exists()
        assert AttemptEvent.objects.filter(pk=evt2.pk).exists()
        assert attempt.events.count() == 2

        # 3. Existing append-only protections continue to hold
        with pytest.raises(ValidationError):
            evt1.delete()
        with pytest.raises(ValidationError):
            AttemptEvent.objects.filter(attempt=attempt).delete()
        with pytest.raises(ValidationError):
            AttemptEvent.objects.filter(attempt=attempt).update(event_type='ALTERED')
        with pytest.raises(ValidationError):
            evt1.save()


# ==============================================================================
# 9. Foreign Key Deletion Policies Tests (PROTECT vs CASCADE)
# ==============================================================================

class TestDeletionPolicies:
    def test_protect_user_with_historical_attempts(self, db, candidate_user, published_assessment_setup):
        asm, ver, _ = published_assessment_setup
        AssessmentAttempt.objects.create(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            idempotency_key='idem-del-user',
        )
        with pytest.raises(ProtectedError):
            candidate_user.delete()

    def test_protect_assessment_with_historical_attempts(self, db, candidate_user, published_assessment_setup):
        asm, ver, _ = published_assessment_setup
        AssessmentAttempt.objects.create(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            idempotency_key='idem-del-asm',
        )
        with pytest.raises(ProtectedError):
            asm.delete()

    def test_protect_assessment_version_with_historical_attempts(self, db, candidate_user, published_assessment_setup):
        asm, ver, _ = published_assessment_setup
        AssessmentAttempt.objects.create(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            idempotency_key='idem-del-ver',
        )
        with pytest.raises(ProtectedError):
            ver.delete()

    def test_protect_question_version_in_assessment_version(self, db, published_assessment_setup):
        _, _, questions = published_assessment_setup
        qv1 = questions[0].question_version
        with pytest.raises(ProtectedError):
            qv1.delete()

    def test_protect_question_version_in_attempt(self, db, candidate_user, published_assessment_setup, question_series):
        asm, ver, _ = published_assessment_setup
        _, qv = question_series
        attempt = AssessmentAttempt.objects.create(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            idempotency_key='idem-del-qv-att',
        )
        AttemptQuestion.objects.create(
            attempt=attempt,
            question_version=qv,
            order_index=1,
            weight=Decimal('1.00'),
        )
        with pytest.raises(ProtectedError):
            qv.delete()

    def test_protect_attempt_with_audit_events_blocks_deletion(self, db, candidate_user, published_assessment_setup):
        asm, ver, _ = published_assessment_setup
        attempt = AssessmentAttempt.objects.create(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            idempotency_key='idem-prot-evt-del',
        )
        evt = AttemptEvent.objects.create(
            attempt=attempt,
            event_type='ATTEMPT_STARTED',
            payload={'step': 1},
        )
        att_id = attempt.id
        evt_id = evt.id

        # Attempt deletion must be blocked by ProtectedError
        with pytest.raises(ProtectedError):
            attempt.delete()

        # Attempt and audit events must remain completely intact
        assert AssessmentAttempt.objects.filter(id=att_id).exists()
        assert AttemptEvent.objects.filter(id=evt_id).exists()

        # QuerySet deletion of the attempt must also be blocked
        with pytest.raises(ProtectedError):
            AssessmentAttempt.objects.filter(id=att_id).delete()

        assert AssessmentAttempt.objects.filter(id=att_id).exists()
        assert AttemptEvent.objects.filter(id=evt_id).exists()

    def test_cascade_delete_attempt_without_events_removes_answers_and_reservations(self, db, candidate_user, published_assessment_setup, question_series):
        asm, ver, _ = published_assessment_setup
        _, qv = question_series
        attempt = AssessmentAttempt.objects.create(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            idempotency_key='idem-casc-1',
        )
        res = ActiveAssessmentReservation.objects.create(attempt=attempt)
        aq = AttemptQuestion.objects.create(
            attempt=attempt,
            question_version=qv,
            order_index=1,
            weight=Decimal('1.00'),
        )
        ans = AttemptAnswer.objects.create(
            attempt_question=aq,
            answer_payload={'value': 42},
        )
        att_id = attempt.id
        aq_id = aq.id
        ans_id = ans.id
        res_id = res.id

        # Without audit events, attempt can be deleted, cascading to questions, answers, and reservations
        attempt.delete()

        assert not AssessmentAttempt.objects.filter(id=att_id).exists()
        assert not AttemptQuestion.objects.filter(id=aq_id).exists()
        assert not AttemptAnswer.objects.filter(id=ans_id).exists()
        assert not ActiveAssessmentReservation.objects.filter(id=res_id).exists()


# ==============================================================================
# 10. Additional Numeric Constraints & Edge Cases
# ==============================================================================

class TestEdgeCasesAndNumericConstraints:
    def test_assessment_attempt_numeric_constraints(self, db, candidate_user, published_assessment_setup):
        asm, ver, _ = published_assessment_setup

        # current_order_index < 1 must fail at DB check constraint
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                att = AssessmentAttempt(
                    user=candidate_user,
                    assessment=asm,
                    assessment_version=ver,
                    attempt_number=1,
                    idempotency_key='idem-order-zero',
                    current_order_index=0,
                )
                super(AssessmentAttempt, att).save()

        # question_count < 0 must fail at DB check constraint
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                att = AssessmentAttempt(
                    user=candidate_user,
                    assessment=asm,
                    assessment_version=ver,
                    attempt_number=1,
                    idempotency_key='idem-q-neg',
                    question_count=-1,
                )
                super(AssessmentAttempt, att).save()

        # time_limit_seconds == 0 must fail at DB check constraint
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                att = AssessmentAttempt(
                    user=candidate_user,
                    assessment=asm,
                    assessment_version=ver,
                    attempt_number=1,
                    idempotency_key='idem-time-zero',
                    time_limit_seconds=0,
                )
                super(AssessmentAttempt, att).save()

    def test_untimed_assessment_attempt(self, db, candidate_user, author_user):
        asm = Assessment.objects.create(code='ASM-UNTIMED-01', title='Untimed Assessment')
        ver = AssessmentVersion.objects.create(
            assessment=asm,
            version_number=1,
            status='DRAFT',
            title='Untimed Version',
            time_limit_seconds=None,
        )
        ver.status = 'PUBLISHED'
        ver.save()

        att = AssessmentAttempt.objects.create(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            idempotency_key='idem-untimed-1',
        )
        assert att.time_limit_seconds is None
        assert att.deadline is None

    def test_reservation_mismatched_user_or_assessment_rejected(self, db, candidate_user, second_candidate, published_assessment_setup):
        asm, ver, _ = published_assessment_setup
        attempt = AssessmentAttempt.objects.create(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            idempotency_key='idem-res-mis',
        )
        # Reservation with user mismatch
        res_bad_user = ActiveAssessmentReservation(
            attempt=attempt,
            user=second_candidate,
            assessment=asm,
        )
        with pytest.raises(ValidationError) as exc:
            res_bad_user.clean()
        assert 'user' in exc.value.error_dict

        # Reservation with assessment mismatch
        other_asm = Assessment.objects.create(code='ASM-OTHER-RES', title='Other')
        res_bad_asm = ActiveAssessmentReservation(
            attempt=attempt,
            user=candidate_user,
            assessment=other_asm,
        )
        with pytest.raises(ValidationError) as exc:
            res_bad_asm.clean()
        assert 'assessment' in exc.value.error_dict


# ==============================================================================
# 11. Django Admin Registration Smoke Tests
# ==============================================================================

class TestAdminRegistration:
    def test_all_models_registered_in_admin(self):
        from django.contrib import admin
        from apps.assessments.models import (
            Assessment,
            AssessmentVersion,
            AssessmentVersionQuestion,
            AssessmentAttempt,
            ActiveAssessmentReservation,
            AttemptQuestion,
            AttemptAnswer,
            AttemptEvent,
        )
        for model in [
            Assessment,
            AssessmentVersion,
            AssessmentVersionQuestion,
            AssessmentAttempt,
            ActiveAssessmentReservation,
            AttemptQuestion,
            AttemptAnswer,
            AttemptEvent,
        ]:
            assert model in admin.site._registry
            assert admin.site._registry[model] is not None
