"""
Unit and regression tests for concurrency locking hierarchy, candidate-side shared locks,
composition locks, and reservation collision recovery (Milestone 4A - Phase 2D.2).

Covers:
- Candidate-side shared locks on Assessment, AssessmentVersion, Question (sorted), and QuestionVersion (sorted).
- Lock hierarchy enforcement:
    Assessment -> AssessmentVersion -> Question (sorted PK) -> QuestionVersion (sorted PK) -> Attempt -> Reservation.
- Composition-side exclusive parent locks (Assessment -> AssessmentVersion) and shared question locks (Question -> QuestionVersion).
- MySQL SQL generation: FOR SHARE clause emission when vendor == 'mysql'.
- Reservation collision recovery:
    - Nested savepoint rollback of losing attempt and reservation.
    - Fresh current locking read on ActiveAssessmentReservation via select_for_update().
    - Zero joined Attempt locking (no select_related('attempt')).
    - Preservation of reservation-before-attempt lock order restriction.
- Labeling: Simulated locking on SQLite test runner; MySQL InnoDB multi-threading verified via SQL/ORM inspection.
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch
import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import QuerySet

from apps.arena.models import Question, QuestionVersion
from apps.assessments.models import (
    ActiveAssessmentReservation,
    Assessment,
    AssessmentAttempt,
    AssessmentVersion,
    AssessmentVersionQuestion,
)
from apps.assessments.services import (
    ActiveAttemptExistsError,
    AssessmentAttemptService,
    AssessmentCompositionService,
)
from apps.assessments.services.concurrency import select_for_share
from apps.skills.models import Competency, Domain, Subdomain

User = get_user_model()


@pytest.fixture
def author_user(db):
    return User.objects.create_user(
        email='lock_author@example.com',
        password='TestPassword123!',
        is_staff=True,
    )


@pytest.fixture
def candidate_user(db):
    return User.objects.create_user(
        email='lock_candidate@example.com',
        password='TestPassword123!',
    )


@pytest.fixture
def competitor_user(db):
    return User.objects.create_user(
        email='lock_competitor@example.com',
        password='TestPassword123!',
    )


@pytest.fixture
def setup_assessment_with_questions(db, author_user):
    """Sets up an assessment with 3 questions in reverse PK order to test sorting."""
    domain = Domain.objects.create(slug='db-eng', name='Database Engineering', category='TECHNICAL')
    subdomain = Subdomain.objects.create(domain=domain, slug='locking', name='Locking')
    comp = Competency.objects.create(subdomain=subdomain, code='COMP-LOCK-01', name='Concurrency')

    questions = []
    question_versions = []
    for i in range(1, 4):
        q = Question.objects.create(code=f'QST-LK-00{i}', created_by=author_user)
        qv = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            status='DRAFT',
            title=f'Question {i}',
            prompt=f'Prompt {i}',
            question_type='SINGLE_CHOICE',
            primary_competency=comp,
            content_payload={'options': [{'id': 'a', 'text': 'A'}, {'id': 'b', 'text': 'B'}]},
            created_by=author_user,
        )
        qv.status = 'IN_REVIEW'
        qv.save()
        qv.status = 'PUBLISHED'
        qv.save()
        q.active_version = qv
        q.save()
        questions.append(q)
        question_versions.append(qv)

    asm = AssessmentCompositionService.create_assessment(
        code='ASM-LK-001',
        title='Lock Hierarchy Assessment',
        user=author_user,
    )
    ver = AssessmentCompositionService.create_draft_version(
        asm.id,
        title='Draft 1.0',
        user=author_user,
    )

    # Insert questions in reverse order (3, 2, 1) to verify sort ordering during locking
    AssessmentCompositionService.add_question_to_version(ver.id, question_versions[2].id, user=author_user)
    AssessmentCompositionService.add_question_to_version(ver.id, question_versions[1].id, user=author_user)
    AssessmentCompositionService.add_question_to_version(ver.id, question_versions[0].id, user=author_user)

    AssessmentCompositionService.publish_version(ver.id, user=author_user)
    asm.refresh_from_db()
    ver.refresh_from_db()

    return asm, ver, questions, question_versions, comp


# ==============================================================================
# 1. Candidate-Side Shared Locks & Hierarchy Tests
# ==============================================================================

class TestCandidateSideSharedLocks:
    def test_start_attempt_acquires_shared_locks_in_exact_hierarchy(
        self, db, candidate_user, setup_assessment_with_questions, monkeypatch
    ):
        """
        Verifies:
        1. Assessment acquired with share=True
        2. AssessmentVersion acquired with share=True
        3. Canonical Questions acquired with share=True in strictly ascending PK order
        4. QuestionVersions acquired with share=True in strictly ascending PK order
        5. AssessmentAttempt and ActiveAssessmentReservation created afterwards
        """
        asm, ver, questions, question_versions, _ = setup_assessment_with_questions

        lock_invocations = []
        orig_select_for_update = QuerySet.select_for_update

        def tracking_select_for_update(self, *args, **kwargs):
            model_cls = self.model
            share_val = kwargs.get('share', False)
            lock_invocations.append({
                'model': model_cls.__name__ if model_cls else 'Unknown',
                'share': share_val,
                'kwargs': kwargs,
            })
            return orig_select_for_update(self, *args, **kwargs)

        monkeypatch.setattr(QuerySet, 'select_for_update', tracking_select_for_update)

        attempt, created = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-lock-test-1',
        )

        assert created is True
        assert attempt.id is not None

        # Verify calls recorded
        # Expected sequence:
        # 1. Assessment (share=True)
        # 2. AssessmentVersion (share=True)
        # 3. Question (share=True)
        # 4. QuestionVersion (share=True)
        models_locked = [item['model'] for item in lock_invocations]
        assert 'Assessment' in models_locked
        assert 'AssessmentVersion' in models_locked
        assert 'Question' in models_locked
        assert 'QuestionVersion' in models_locked

        asm_idx = models_locked.index('Assessment')
        ver_idx = models_locked.index('AssessmentVersion')
        q_idx = models_locked.index('Question')
        qv_idx = models_locked.index('QuestionVersion')

        # Strictly ordered hierarchy
        assert asm_idx < ver_idx < q_idx < qv_idx

        # Verify share=True on candidate-side locks
        assert lock_invocations[asm_idx]['share'] is True
        assert lock_invocations[ver_idx]['share'] is True
        assert lock_invocations[q_idx]['share'] is True
        assert lock_invocations[qv_idx]['share'] is True

    def test_canonical_questions_and_versions_locked_in_sorted_pk_order(
        self, db, candidate_user, setup_assessment_with_questions, monkeypatch
    ):
        """
        Verifies canonical Questions and QuestionVersions are ordered by sorted PK
        to guarantee deadlock prevention across concurrent attempt starts.
        """
        asm, ver, questions, question_versions, _ = setup_assessment_with_questions
        expected_sorted_q_pks = sorted([q.pk for q in questions])
        expected_sorted_qv_pks = sorted([qv.pk for qv in question_versions])

        captured_q_order = None
        captured_qv_order = None
        orig_filter = QuerySet.filter

        def spy_filter(self, *args, **kwargs):
            nonlocal captured_q_order, captured_qv_order
            if self.model == Question and 'pk__in' in kwargs:
                captured_q_order = list(kwargs['pk__in'])
            elif self.model == QuestionVersion and 'pk__in' in kwargs:
                captured_qv_order = list(kwargs['pk__in'])
            return orig_filter(self, *args, **kwargs)

        monkeypatch.setattr(QuerySet, 'filter', spy_filter)

        AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-sort-order-test',
        )

        assert captured_q_order == expected_sorted_q_pks
        assert captured_qv_order == expected_sorted_qv_pks


# ==============================================================================
# 2. Composition-Side Locking Tests
# ==============================================================================

class TestCompositionSideLocks:
    def test_add_question_to_version_locks_parent_exclusive_and_questions_shared(
        self, db, author_user, setup_assessment_with_questions, monkeypatch
    ):
        """
        Verifies:
        - Assessment locked exclusively (share=False)
        - AssessmentVersion locked exclusively (share=False)
        - Canonical Question locked with shared lock (share=True)
        - Target QuestionVersion locked with shared lock (share=True)
        - Question locked BEFORE QuestionVersion
        """
        asm, _, _, _, comp = setup_assessment_with_questions
        # Create a new draft version
        draft_ver = AssessmentCompositionService.create_draft_version(
            asm.id,
            title='Draft 2.0',
            user=author_user,
        )

        # Create a new question and published version to add
        new_q = Question.objects.create(code='QST-ADD-001', created_by=author_user)
        new_qv = QuestionVersion.objects.create(
            question=new_q,
            version_number=1,
            status='DRAFT',
            title='New Question',
            prompt='New Prompt',
            question_type='SINGLE_CHOICE',
            primary_competency=comp,
            content_payload={'options': [{'id': '1', 'text': 'Option 1'}]},
            created_by=author_user,
        )
        new_qv.status = 'IN_REVIEW'
        new_qv.save()
        new_qv.status = 'PUBLISHED'
        new_qv.save()

        lock_invocations = []
        orig_select_for_update = QuerySet.select_for_update

        def tracking_select_for_update(self, *args, **kwargs):
            lock_invocations.append({
                'model': self.model.__name__ if self.model else 'Unknown',
                'share': kwargs.get('share', False),
            })
            return orig_select_for_update(self, *args, **kwargs)

        monkeypatch.setattr(QuerySet, 'select_for_update', tracking_select_for_update)

        AssessmentCompositionService.add_question_to_version(
            version_id=draft_ver.id,
            question_version_id=new_qv.id,
            user=author_user,
        )

        models_locked = [item['model'] for item in lock_invocations]
        assert 'Assessment' in models_locked
        assert 'AssessmentVersion' in models_locked
        assert 'Question' in models_locked
        assert 'QuestionVersion' in models_locked

        asm_idx = models_locked.index('Assessment')
        ver_idx = models_locked.index('AssessmentVersion')
        q_idx = models_locked.index('Question')
        qv_idx = models_locked.index('QuestionVersion')

        # Check order: Assessment -> AssessmentVersion -> Question -> QuestionVersion
        assert asm_idx < ver_idx < q_idx < qv_idx

        # Parents must be exclusive (share=False)
        assert lock_invocations[asm_idx]['share'] is False
        assert lock_invocations[ver_idx]['share'] is False

        # Target question and version must be shared (share=True)
        assert lock_invocations[q_idx]['share'] is True
        assert lock_invocations[qv_idx]['share'] is True


# ==============================================================================
# 3. MySQL SQL Syntax Generation Inspection
# ==============================================================================

class TestMySQLSharedLockSQLGeneration:
    def test_queryset_compiles_to_for_share_under_mysql_vendor(self, db):
        """
        Verifies that select_for_share / select_for_update(share=True)
        transforms 'FOR UPDATE' into 'FOR SHARE' when connection.vendor == 'mysql'.
        """
        with transaction.atomic():
            qs = Assessment.objects.select_for_update(share=True).filter(pk=1)
            compiler = qs.query.get_compiler(using='default')

            # Mock connection vendor as 'mysql'
            with patch.object(compiler.connection, 'vendor', 'mysql'):
                with patch.object(compiler.connection.features, 'has_select_for_update', True):
                    with patch.object(compiler.connection.ops, 'for_update_sql', lambda **kwargs: 'FOR UPDATE'):
                        sql, params = compiler.as_sql()

            # The compiled SQL must contain 'FOR SHARE' and NOT 'FOR UPDATE'
            assert 'FOR SHARE' in sql
            assert 'FOR UPDATE' not in sql

    def test_exclusive_queryset_preserves_for_update_under_mysql_vendor(self, db):
        """
        Verifies that standard select_for_update() (exclusive)
        maintains 'FOR UPDATE' when connection.vendor == 'mysql'.
        """
        with transaction.atomic():
            qs = Assessment.objects.select_for_update().filter(pk=1)
            compiler = qs.query.get_compiler(using='default')

            with patch.object(compiler.connection, 'vendor', 'mysql'):
                with patch.object(compiler.connection.features, 'has_select_for_update', True):
                    with patch.object(compiler.connection.ops, 'for_update_sql', lambda **kwargs: 'FOR UPDATE'):
                        sql, params = compiler.as_sql()

            assert 'FOR UPDATE' in sql
            assert 'FOR SHARE' not in sql


# ==============================================================================
# 4. Reservation Collision Recovery Tests
# ==============================================================================

class TestReservationCollisionRecovery:
    def test_reservation_collision_uses_fresh_locking_read_without_joined_attempt(
        self, db, candidate_user, setup_assessment_with_questions, monkeypatch
    ):
        """
        Simulates a concurrent race condition where ActiveAssessmentReservation.objects.create
        raises IntegrityError (due to a concurrent start slipping in).
        Verifies:
        1. Nested savepoint rollback occurs.
        2. Collision lookup performs a fresh current locking read:
           ActiveAssessmentReservation.objects.select_for_update().filter(...)
        3. No select_related('attempt') is used, avoiding joined Attempt row locks.
        4. Losing candidate attempt is rolled back completely.
        5. ActiveAttemptExistsError is raised with the winning attempt ID.
        """
        asm, ver, _, _, _ = setup_assessment_with_questions

        # Existing active reservation from a concurrent transaction
        winning_attempt = AssessmentAttempt.objects.create(
            user=candidate_user,
            assessment=asm,
            assessment_version=ver,
            attempt_number=1,
            status='IN_PROGRESS',
            idempotency_key='winner-key',
        )
        existing_res = ActiveAssessmentReservation.objects.create(
            user=candidate_user,
            assessment=asm,
            attempt=winning_attempt,
            idempotency_key='winner-key',
        )

        select_for_update_calls = []
        select_related_calls = []
        orig_sfu = QuerySet.select_for_update
        orig_sr = QuerySet.select_related

        def track_sfu(self, *args, **kwargs):
            if self.model == ActiveAssessmentReservation:
                select_for_update_calls.append({'model': self.model.__name__, 'kwargs': kwargs})
            return orig_sfu(self, *args, **kwargs)

        def track_sr(self, *args, **kwargs):
            if self.model == ActiveAssessmentReservation:
                select_related_calls.append({'fields': args})
                # Simulate step 4 racing before concurrent transaction commit (not yet visible)
                return self.none()
            return orig_sr(self, *args, **kwargs)

        monkeypatch.setattr(QuerySet, 'select_for_update', track_sfu)
        monkeypatch.setattr(QuerySet, 'select_related', track_sr)

        initial_attempt_count = AssessmentAttempt.objects.count()

        with pytest.raises(ActiveAttemptExistsError) as exc_info:
            AssessmentAttemptService.start_or_resume_attempt(
                assessment_id=asm.id,
                user=candidate_user,
                idempotency_key='loser-key',
            )

        # Verify conflict exception with winning attempt details
        assert str(winning_attempt.id) in str(exc_info.value.details.get('attempt_id'))

        # Verify fresh current locking read on ActiveAssessmentReservation
        assert len(select_for_update_calls) == 1
        assert select_for_update_calls[0]['model'] == 'ActiveAssessmentReservation'

        # Verify NO select_related was called on collision recovery query
        # Collision query performed select_for_update() without select_related('attempt')
        # to prevent joined Attempt locking and lock inversion
        assert len(select_related_calls) == 1  # Only step 4 called select_related, NOT collision query
        assert select_related_calls[0]['fields'] == ('attempt',)

        # Verify losing candidate attempt was completely rolled back
        final_attempt_count = AssessmentAttempt.objects.count()
        assert final_attempt_count == initial_attempt_count
        assert not AssessmentAttempt.objects.filter(idempotency_key='loser-key').exists()
