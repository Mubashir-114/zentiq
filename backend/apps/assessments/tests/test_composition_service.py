"""
Unit and integration tests for AssessmentCompositionService (Milestone 4A - Phase 2D.2 Stage A).
Covers:
- Assessment creation, metadata updates, and deprecation.
- AssessmentVersion draft creation and configuration updates.
- Pinned QuestionVersion addition, removal, and reordering.
- Canonical question deduplication.
- Pinned question status and parent question deprecation validation.
- Positive weight validation.
- Contiguous order enforcement and compaction.
- DRAFT -> PUBLISHED and PUBLISHED -> ARCHIVED lifecycle transitions.
- Assessment.active_version maintenance and reconciliation.
- Version immutability upon publication or archiving.
- Authorization checks.
"""
from decimal import Decimal
from pathlib import Path
import sys
import uuid

# Ensure backend root is on sys.path
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from apps.arena.models import Question, QuestionVersion
from apps.assessments.models import (
    Assessment,
    AssessmentVersion,
    AssessmentVersionQuestion,
)
from apps.assessments.services import (
    AssessmentCompositionService,
    AssessmentDeprecatedError,
    AssessmentNotFoundError,
    AssessmentPermissionDeniedError,
    AssessmentValidationError,
    AssessmentVersionImmutabilityError,
    AssessmentVersionNotFoundError,
    DuplicateCanonicalQuestionError,
    IncompleteAssessmentVersionError,
    InvalidQuestionOrderError,
    InvalidQuestionWeightError,
    InvalidVersionTransitionError,
    QuestionDeprecatedError,
    QuestionNotPublishedError,
)
from apps.skills.models import Competency, Domain, Subdomain

User = get_user_model()


@pytest.fixture
def author_user(db):
    user = User.objects.create_user(
        email='assessment_author@example.com',
        password='TestPassword123!',
    )
    content_type = ContentType.objects.get_for_model(Assessment)
    perm_change = Permission.objects.get(codename='change_assessment', content_type=content_type)
    perm_add = Permission.objects.get(codename='add_assessment', content_type=content_type)
    user.user_permissions.add(perm_change, perm_add)
    return user


@pytest.fixture
def unprivileged_user(db):
    return User.objects.create_user(
        email='unprivileged@example.com',
        password='TestPassword123!',
    )


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        email='staff@example.com',
        password='TestPassword123!',
        is_staff=True,
    )


@pytest.fixture
def competency(db):
    domain = Domain.objects.create(
        slug='architecture-comp',
        name='Architecture',
        category='TECHNICAL',
        description='Architecture domain',
        display_order=1,
    )
    subdomain = Subdomain.objects.create(
        domain=domain,
        slug='database-comp',
        name='Database',
        display_order=1,
    )
    return Competency.objects.create(
        subdomain=subdomain,
        code='COMP-DB-01',
        name='Database ACID',
        description='Transactions and isolation',
        bloom_level='APPLY',
    )


def create_published_question(author, comp, code, title='Sample Question'):
    q = Question.objects.create(code=code, created_by=author)
    qv = QuestionVersion.objects.create(
        question=q,
        version_number=1,
        status='DRAFT',
        title=title,
        prompt='Sample prompt text',
        question_type='SINGLE_CHOICE',
        primary_competency=comp,
        content_payload={'options': [{'id': '1', 'text': 'Option A'}, {'id': '2', 'text': 'Option B'}]},
        created_by=author,
    )
    qv.status = 'IN_REVIEW'
    qv.save()
    qv.status = 'PUBLISHED'
    qv.save()
    q.active_version = qv
    q.save()
    return q, qv


# ==============================================================================
# Assessment Series Tests
# ==============================================================================

class TestAssessmentCompositionCreation:
    def test_create_assessment_success(self, db, author_user):
        asm = AssessmentCompositionService.create_assessment(
            code='ASM-TEST-001',
            title='Test Assessment',
            description='Test scope description',
            user=author_user,
        )
        assert asm.code == 'ASM-TEST-001'
        assert asm.title == 'Test Assessment'
        assert asm.description == 'Test scope description'
        assert asm.is_deprecated is False
        assert asm.active_version is None
        assert asm.created_by == author_user

    def test_create_assessment_duplicate_code_rejected(self, db, author_user):
        AssessmentCompositionService.create_assessment(
            code='ASM-DUP-001',
            title='First',
            user=author_user,
        )
        with pytest.raises(AssessmentValidationError) as exc:
            AssessmentCompositionService.create_assessment(
                code='ASM-DUP-001',
                title='Second',
                user=author_user,
            )
        assert 'already exists' in str(exc.value)

    def test_create_assessment_unprivileged_rejected(self, db, unprivileged_user):
        with pytest.raises(AssessmentPermissionDeniedError):
            AssessmentCompositionService.create_assessment(
                code='ASM-UNP-001',
                title='Unprivileged',
                user=unprivileged_user,
            )

    def test_update_assessment_success(self, db, author_user):
        asm = AssessmentCompositionService.create_assessment(
            code='ASM-UPD-001',
            title='Old Title',
            user=author_user,
        )
        updated = AssessmentCompositionService.update_assessment(
            asm.id,
            title='New Title',
            description='Updated Description',
            user=author_user,
        )
        assert updated.title == 'New Title'
        assert updated.description == 'Updated Description'

    def test_deprecate_assessment(self, db, author_user):
        asm = AssessmentCompositionService.create_assessment(
            code='ASM-DEP-001',
            title='To Deprecate',
            user=author_user,
        )
        deprecated = AssessmentCompositionService.deprecate_assessment(asm.id, user=author_user)
        assert deprecated.is_deprecated is True
        assert deprecated.active_version is None


# ==============================================================================
# Version & Question Composition Tests
# ==============================================================================

class TestAssessmentVersionComposition:
    def test_create_draft_version(self, db, author_user):
        asm = AssessmentCompositionService.create_assessment(
            code='ASM-VER-001',
            title='Assessment',
            user=author_user,
        )
        ver = AssessmentCompositionService.create_draft_version(
            asm.id,
            title='Version 1.0',
            description='Initial syllabus',
            time_limit_seconds=1800,
            allow_backtracking=False,
            user=author_user,
        )
        assert ver.version_number == 1
        assert ver.status == 'DRAFT'
        assert ver.time_limit_seconds == 1800
        assert ver.allow_backtracking is False

    def test_create_draft_version_on_deprecated_assessment_rejected(self, db, author_user):
        asm = AssessmentCompositionService.create_assessment(
            code='ASM-DEP-VER',
            title='Assessment',
            user=author_user,
        )
        AssessmentCompositionService.deprecate_assessment(asm.id, user=author_user)
        with pytest.raises(AssessmentDeprecatedError):
            AssessmentCompositionService.create_draft_version(
                asm.id,
                title='Version on Deprecated',
                user=author_user,
            )

    def test_add_questions_and_sequential_ordering(self, db, author_user, competency):
        asm = AssessmentCompositionService.create_assessment(
            code='ASM-ORD-001',
            title='Ordering Test',
            user=author_user,
        )
        ver = AssessmentCompositionService.create_draft_version(
            asm.id,
            title='v1',
            user=author_user,
        )
        _, qv1 = create_published_question(author_user, competency, 'QST-001')
        _, qv2 = create_published_question(author_user, competency, 'QST-002')

        avq1 = AssessmentCompositionService.add_question_to_version(
            ver.id,
            qv1.id,
            weight=Decimal('1.50'),
            user=author_user,
        )
        assert avq1.order_index == 1
        assert avq1.weight == Decimal('1.50')

        avq2 = AssessmentCompositionService.add_question_to_version(
            ver.id,
            qv2.id,
            weight=Decimal('2.00'),
            user=author_user,
        )
        assert avq2.order_index == 2
        assert avq2.weight == Decimal('2.00')

    def test_reject_duplicate_canonical_question(self, db, author_user, competency):
        q, qv1 = create_published_question(author_user, competency, 'QST-DUP-C')

        # Create v2 of the same Question
        qv2 = QuestionVersion.objects.create(
            question=q,
            version_number=2,
            status='DRAFT',
            title='v2 Question',
            prompt='v2 Prompt',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
            created_by=author_user,
        )
        qv2.status = 'IN_REVIEW'
        qv2.save()
        qv2.status = 'PUBLISHED'
        qv2.save()

        asm = AssessmentCompositionService.create_assessment(code='ASM-DUP-C', title='Title', user=author_user)
        ver = AssessmentCompositionService.create_draft_version(asm.id, title='v1', user=author_user)

        AssessmentCompositionService.add_question_to_version(ver.id, qv1.id, user=author_user)

        with pytest.raises(DuplicateCanonicalQuestionError):
            AssessmentCompositionService.add_question_to_version(ver.id, qv2.id, user=author_user)

    def test_reject_unpublished_question_version(self, db, author_user, competency):
        q = Question.objects.create(code='QST-UNPUB', created_by=author_user)
        qv_draft = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            status='DRAFT',
            title='Draft Question',
            prompt='Prompt',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
            created_by=author_user,
        )
        asm = AssessmentCompositionService.create_assessment(code='ASM-UNPUB', title='Title', user=author_user)
        ver = AssessmentCompositionService.create_draft_version(asm.id, title='v1', user=author_user)

        with pytest.raises(QuestionNotPublishedError):
            AssessmentCompositionService.add_question_to_version(ver.id, qv_draft.id, user=author_user)

    def test_reject_deprecated_question(self, db, author_user, competency):
        q, qv = create_published_question(author_user, competency, 'QST-DEP-Q')
        q.is_deprecated = True
        q.save()

        asm = AssessmentCompositionService.create_assessment(code='ASM-DEP-Q', title='Title', user=author_user)
        ver = AssessmentCompositionService.create_draft_version(asm.id, title='v1', user=author_user)

        with pytest.raises(QuestionDeprecatedError):
            AssessmentCompositionService.add_question_to_version(ver.id, qv.id, user=author_user)

    def test_reject_invalid_weight(self, db, author_user, competency):
        _, qv = create_published_question(author_user, competency, 'QST-WT')
        asm = AssessmentCompositionService.create_assessment(code='ASM-WT', title='Title', user=author_user)
        ver = AssessmentCompositionService.create_draft_version(asm.id, title='v1', user=author_user)

        for bad_weight in [0, -1, Decimal('0.00'), 'abc', None, True, False]:
            with pytest.raises(InvalidQuestionWeightError):
                AssessmentCompositionService.add_question_to_version(
                    ver.id, qv.id, weight=bad_weight, user=author_user
                )

    def test_remove_question_and_recompact_order(self, db, author_user, competency):
        asm = AssessmentCompositionService.create_assessment(code='ASM-RM', title='Title', user=author_user)
        ver = AssessmentCompositionService.create_draft_version(asm.id, title='v1', user=author_user)

        _, qv1 = create_published_question(author_user, competency, 'QST-RM-1')
        _, qv2 = create_published_question(author_user, competency, 'QST-RM-2')
        _, qv3 = create_published_question(author_user, competency, 'QST-RM-3')

        AssessmentCompositionService.add_question_to_version(ver.id, qv1.id, user=author_user)
        AssessmentCompositionService.add_question_to_version(ver.id, qv2.id, user=author_user)
        AssessmentCompositionService.add_question_to_version(ver.id, qv3.id, user=author_user)

        # Remove middle question qv2
        AssessmentCompositionService.remove_question_from_version(ver.id, qv2.id, user=author_user)

        remaining = list(
            AssessmentVersionQuestion.objects.filter(assessment_version=ver).order_by('order_index')
        )
        assert len(remaining) == 2
        assert remaining[0].question_version == qv1
        assert remaining[0].order_index == 1
        assert remaining[1].question_version == qv3
        assert remaining[1].order_index == 2  # Compacted from 3 to 2

    def test_reorder_questions(self, db, author_user, competency):
        asm = AssessmentCompositionService.create_assessment(code='ASM-REORD', title='Title', user=author_user)
        ver = AssessmentCompositionService.create_draft_version(asm.id, title='v1', user=author_user)

        _, qv1 = create_published_question(author_user, competency, 'QST-RO-1')
        _, qv2 = create_published_question(author_user, competency, 'QST-RO-2')
        _, qv3 = create_published_question(author_user, competency, 'QST-RO-3')

        AssessmentCompositionService.add_question_to_version(ver.id, qv1.id, user=author_user)
        AssessmentCompositionService.add_question_to_version(ver.id, qv2.id, user=author_user)
        AssessmentCompositionService.add_question_to_version(ver.id, qv3.id, user=author_user)

        # Reverse the order: qv3, qv2, qv1
        updated = AssessmentCompositionService.reorder_questions(
            ver.id,
            [qv3.id, qv2.id, qv1.id],
            user=author_user,
        )
        assert len(updated) == 3
        q_map = {q.question_version_id: q.order_index for q in AssessmentVersionQuestion.objects.filter(assessment_version=ver)}
        assert q_map[qv3.id] == 1
        assert q_map[qv2.id] == 2
        assert q_map[qv1.id] == 3


# ==============================================================================
# Publication and Archiving Tests
# ==============================================================================

class TestAssessmentPublicationAndArchiving:
    def test_publish_version_promotes_active_version(self, db, author_user, competency):
        asm = AssessmentCompositionService.create_assessment(code='ASM-PUB', title='Title', user=author_user)
        ver = AssessmentCompositionService.create_draft_version(asm.id, title='v1', user=author_user)
        _, qv = create_published_question(author_user, competency, 'QST-PUB')
        AssessmentCompositionService.add_question_to_version(ver.id, qv.id, user=author_user)

        published = AssessmentCompositionService.publish_version(ver.id, user=author_user)
        assert published.status == 'PUBLISHED'
        assert published.published_at is not None

        asm.refresh_from_db()
        assert asm.active_version == published

    def test_publish_empty_version_fails(self, db, author_user):
        asm = AssessmentCompositionService.create_assessment(code='ASM-EMP', title='Title', user=author_user)
        ver = AssessmentCompositionService.create_draft_version(asm.id, title='v1', user=author_user)

        with pytest.raises(IncompleteAssessmentVersionError) as exc:
            AssessmentCompositionService.publish_version(ver.id, user=author_user)
        assert 'at least one question' in str(exc.value)

    def test_published_version_is_immutable(self, db, author_user, competency):
        asm = AssessmentCompositionService.create_assessment(code='ASM-IMM', title='Title', user=author_user)
        ver = AssessmentCompositionService.create_draft_version(asm.id, title='v1', user=author_user)
        _, qv1 = create_published_question(author_user, competency, 'QST-IMM-1')
        _, qv2 = create_published_question(author_user, competency, 'QST-IMM-2')
        AssessmentCompositionService.add_question_to_version(ver.id, qv1.id, user=author_user)
        AssessmentCompositionService.publish_version(ver.id, user=author_user)

        with pytest.raises(AssessmentVersionImmutabilityError):
            AssessmentCompositionService.add_question_to_version(ver.id, qv2.id, user=author_user)

        with pytest.raises(AssessmentVersionImmutabilityError):
            AssessmentCompositionService.remove_question_from_version(ver.id, qv1.id, user=author_user)

        with pytest.raises(AssessmentVersionImmutabilityError):
            AssessmentCompositionService.update_draft_version(ver.id, title='Mutated', user=author_user)

    def test_archive_version_reconciles_active_version(self, db, author_user, competency):
        asm = AssessmentCompositionService.create_assessment(code='ASM-ARC', title='Title', user=author_user)
        ver1 = AssessmentCompositionService.create_draft_version(asm.id, title='v1', user=author_user)
        _, qv1 = create_published_question(author_user, competency, 'QST-ARC-1')
        AssessmentCompositionService.add_question_to_version(ver1.id, qv1.id, user=author_user)
        AssessmentCompositionService.publish_version(ver1.id, user=author_user)

        asm.refresh_from_db()
        assert asm.active_version == ver1

        # Archive version 1
        archived = AssessmentCompositionService.archive_version(ver1.id, user=author_user)
        assert archived.status == 'ARCHIVED'

        asm.refresh_from_db()
        # No remaining published version, active_version should be None
        assert asm.active_version is None

