"""
Tests for apps.arena data models, immutabili`ty guarantees, constraints, and relationships.
"""
import sys
import uuid
from decimal import Decimal
from pathlib import Path

# Ensure backend root is on sys.path for standalone test runners and IDE language servers
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models.deletion import ProtectedError
from django.test import RequestFactory
from django.utils import timezone

from apps.arena.admin import (
    QuestionCompetencyMappingInline,
    QuestionEvaluationDataInline,
    QuestionVersionAdmin,
    QuestionVersionTagInline,
)
from apps.arena.models import (
    Question,
    QuestionCompetencyMapping,
    QuestionEvaluationData,
    QuestionVersion,
    QuestionVersionTag,
    Tag,
    reconcile_active_version_on_lifecycle_transition,
)
from apps.skills.models import Competency, Domain, Subdomain

User = get_user_model()


def transition_to_published(qv: QuestionVersion) -> QuestionVersion:
    """Helper to transition a draft QuestionVersion through the required lifecycle to PUBLISHED."""
    qv.status = 'IN_REVIEW'
    qv.save()
    qv.status = 'PUBLISHED'
    qv.save()
    return qv


@pytest.fixture
def test_user(db):
    return User.objects.create_user(
        email='arena_author@example.com',
        password='TestPassword123!',
    )


@pytest.fixture
def other_user(db):
    return User.objects.create_user(
        email='other_author@example.com',
        password='TestPassword123!',
    )


@pytest.fixture
def competency(db):
    domain = Domain.objects.create(
        slug='numerical_intelligence',
        name='Numerical Intelligence',
        category='COGNITIVE',
        description='Quantitative skills',
        display_order=1,
    )
    subdomain = Subdomain.objects.create(
        domain=domain,
        slug='quantitative-arithmetic',
        name='Quantitative Arithmetic',
        display_order=1,
    )
    return Competency.objects.create(
        subdomain=subdomain,
        code='NUM-ARITH-01',
        name='Mental Arithmetic & Ratio Operations',
        description='Rapid calculation and proportional scaling.',
        bloom_level='APPLY',
    )


@pytest.fixture
def secondary_competency(db, competency):
    return Competency.objects.create(
        subdomain=competency.subdomain,
        code='NUM-ARITH-02',
        name='Percentage & Compounded Rate Dynamics',
        description='Financial compounding.',
        bloom_level='APPLY',
    )


# ============================================================================
# 1. QUESTION MODEL TESTS
# ============================================================================

@pytest.mark.django_db
class TestQuestionModel:
    def test_create_question_success(self, test_user):
        q = Question.objects.create(
            code='QST-TEST-001',
            created_by=test_user,
        )
        assert isinstance(q.id, uuid.UUID)
        assert q.code == 'QST-TEST-001'
        assert q.is_deprecated is False
        assert q.active_version is None
        assert str(q) == 'QST-TEST-001'

    def test_question_code_unique_constraint(self, test_user):
        Question.objects.create(code='QST-UNIQUE-001', created_by=test_user)
        with pytest.raises(IntegrityError):
            Question.objects.create(code='QST-UNIQUE-001', created_by=test_user)

    def test_question_code_is_immutable(self, test_user):
        q = Question.objects.create(code='QST-IMMUTABLE-001', created_by=test_user)
        q.code = 'QST-MUTATED-001'
        with pytest.raises(ValidationError) as excinfo:
            q.save()
        assert 'code' in excinfo.value.message_dict


# ============================================================================
# 2. QUESTION VERSION MODEL TESTS (RETAINED & EXPANDED)
# ============================================================================

@pytest.mark.django_db
class TestQuestionVersionModel:
    def test_create_draft_question_version(self, test_user, competency):
        q = Question.objects.create(code='QST-VER-001', created_by=test_user)
        qv = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            title='Sample Version 1',
            prompt='What is 2 + 2?',
            question_type='SINGLE_CHOICE',
            difficulty_tier='BEGINNER',
            primary_competency=competency,
            bloom_level='APPLY',
            time_limit_seconds=45,
            content_payload={'options': [{'id': 'opt_1', 'text': '4'}]},
            created_by=test_user,
        )
        assert qv.status == 'DRAFT'
        assert qv.published_at is None
        assert str(qv) == 'QST-VER-001 (v1) [DRAFT]'

    def test_version_number_unique_together(self, test_user, competency):
        q = Question.objects.create(code='QST-UQ-001', created_by=test_user)
        QuestionVersion.objects.create(
            question=q,
            version_number=1,
            title='V1',
            prompt='P1',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
        )
        with pytest.raises(IntegrityError):
            QuestionVersion.objects.create(
                question=q,
                version_number=1,
                title='V1 Duplicate',
                prompt='P1 Dup',
                question_type='SINGLE_CHOICE',
                primary_competency=competency,
            )

    def test_draft_version_is_mutable(self, test_user, competency):
        q = Question.objects.create(code='QST-MUT-001', created_by=test_user)
        qv = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            title='Draft V1',
            prompt='Initial Prompt',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
        )
        qv.prompt = 'Updated Prompt'
        qv.content_payload = {'updated': True}
        qv.save()
        qv.refresh_from_db()
        assert qv.prompt == 'Updated Prompt'
        assert qv.content_payload == {'updated': True}

    def test_publishing_version_sets_published_at(self, test_user, competency):
        q = Question.objects.create(code='QST-PUB-001', created_by=test_user)
        qv = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            title='Draft to Publish',
            prompt='Prompt',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
            status='DRAFT',
        )
        transition_to_published(qv)
        assert qv.status == 'PUBLISHED'
        assert qv.published_at is not None
        assert (timezone.now() - qv.published_at).total_seconds() < 5

    def test_published_version_is_strictly_immutable(self, test_user, competency, secondary_competency, other_user):
        q = Question.objects.create(code='QST-IMM-001', created_by=test_user)
        qv = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            title='Published Title',
            prompt='Original Published Prompt',
            question_type='SINGLE_CHOICE',
            difficulty_tier='INTERMEDIATE',
            primary_competency=competency,
            time_limit_seconds=60,
            content_payload={'options': [{'id': '1', 'text': 'Option A'}]},
            explanation='Original explanation',
            created_by=test_user,
            change_summary='Initial commit',
            status='DRAFT',
        )
        transition_to_published(qv)

        # Attempt to modify prompt
        qv.prompt = 'Hacked Prompt'
        with pytest.raises(ValidationError) as excinfo:
            qv.save()
        assert 'prompt' in str(excinfo.value)
        qv.refresh_from_db()

        # Attempt to modify content_payload
        qv.content_payload = {'options': []}
        with pytest.raises(ValidationError) as excinfo:
            qv.save()
        assert 'content_payload' in str(excinfo.value)
        qv.refresh_from_db()

        # Attempt to modify question_type
        qv.question_type = 'NUMERICAL'
        with pytest.raises(ValidationError) as excinfo:
            qv.save()
        assert 'question_type' in str(excinfo.value)
        qv.refresh_from_db()

        # Attempt to modify primary_competency
        qv.primary_competency = secondary_competency
        with pytest.raises(ValidationError) as excinfo:
            qv.save()
        assert 'primary_competency' in str(excinfo.value)
        qv.refresh_from_db()

        # Attempt to modify difficulty_tier
        qv.difficulty_tier = 'EXPERT'
        with pytest.raises(ValidationError) as excinfo:
            qv.save()
        assert 'difficulty_tier' in str(excinfo.value)
        qv.refresh_from_db()

        # Attempt to modify time_limit_seconds
        qv.time_limit_seconds = 120
        with pytest.raises(ValidationError) as excinfo:
            qv.save()
        assert 'time_limit_seconds' in str(excinfo.value)
        qv.refresh_from_db()

        # Attempt to modify explanation
        qv.explanation = 'Modified explanation'
        with pytest.raises(ValidationError) as excinfo:
            qv.save()
        assert 'explanation' in str(excinfo.value)
        qv.refresh_from_db()

        # Attempt to modify created_by (author immutability)
        qv.created_by = other_user
        with pytest.raises(ValidationError) as excinfo:
            qv.save()
        assert 'created_by_id' in str(excinfo.value)
        qv.refresh_from_db()

        # Attempt to modify published_at timestamp
        qv.published_at = timezone.now() - timezone.timedelta(days=10)
        with pytest.raises(ValidationError) as excinfo:
            qv.save()
        assert 'published_at' in str(excinfo.value)
        qv.refresh_from_db()

        # Attempt to modify historical change_summary
        qv.change_summary = 'Tampered changelog'
        with pytest.raises(ValidationError) as excinfo:
            qv.save()
        assert 'change_summary' in str(excinfo.value)
        qv.refresh_from_db()

    def test_published_version_allows_lifecycle_transitions(self, test_user, competency):
        q = Question.objects.create(code='QST-LIFECYCLE-001', created_by=test_user)
        qv = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            title='Published Title',
            prompt='Prompt',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
            status='DRAFT',
        )
        transition_to_published(qv)

        # Transition to ARCHIVED is permitted
        qv.status = 'ARCHIVED'
        qv.save()
        qv.refresh_from_db()
        assert qv.status == 'ARCHIVED'

        # Substantive edit on ARCHIVED raises ValidationError
        qv.prompt = 'Changed on archived'
        with pytest.raises(ValidationError):
            qv.save()
        qv.refresh_from_db()

        # Transition from ARCHIVED to DEPRECATED is permitted
        qv.status = 'DEPRECATED'
        qv.save()
        qv.refresh_from_db()
        assert qv.status == 'DEPRECATED'


# ============================================================================
# 3. LIFECYCLE STATE MACHINE & TRANSITION TESTS
# ============================================================================

@pytest.mark.django_db
class TestLifecycleTransitions:
    def test_new_version_must_be_draft(self, test_user, competency):
        q = Question.objects.create(code='QST-NEW-001', created_by=test_user)
        for invalid_status in ['IN_REVIEW', 'PUBLISHED', 'ARCHIVED', 'DEPRECATED']:
            with pytest.raises(ValidationError) as excinfo:
                QuestionVersion.objects.create(
                    question=q,
                    version_number=1,
                    title='Invalid Init',
                    prompt='Prompt',
                    question_type='SINGLE_CHOICE',
                    primary_competency=competency,
                    status=invalid_status,
                )
            assert 'status' in excinfo.value.message_dict

    def test_draft_to_in_review_and_back(self, test_user, competency):
        q = Question.objects.create(code='QST-TR-001', created_by=test_user)
        qv = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            title='TR 1',
            prompt='P',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
            status='DRAFT',
        )
        # DRAFT -> IN_REVIEW allowed
        qv.status = 'IN_REVIEW'
        qv.save()
        qv.refresh_from_db()
        assert qv.status == 'IN_REVIEW'

        # IN_REVIEW -> DRAFT allowed (request changes)
        qv.status = 'DRAFT'
        qv.save()
        qv.refresh_from_db()
        assert qv.status == 'DRAFT'

    def test_cannot_publish_directly_from_draft(self, test_user, competency):
        q = Question.objects.create(code='QST-DIRECT-PUB', created_by=test_user)
        qv = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            title='Direct Pub',
            prompt='P',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
            status='DRAFT',
        )
        # Direct DRAFT -> PUBLISHED rejected
        qv.status = 'PUBLISHED'
        with pytest.raises(ValidationError) as excinfo:
            qv.save()
        assert 'status' in excinfo.value.message_dict
        assert 'DRAFT' in str(excinfo.value)

    def test_published_cannot_downgrade_to_draft_or_in_review(self, test_user, competency):
        q = Question.objects.create(code='QST-DOWN-001', created_by=test_user)
        qv = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            title='Downgrade test',
            prompt='P',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
            status='DRAFT',
        )
        transition_to_published(qv)

        # PUBLISHED -> DRAFT forbidden
        qv.status = 'DRAFT'
        with pytest.raises(ValidationError) as excinfo:
            qv.save()
        assert 'status' in excinfo.value.message_dict
        qv.refresh_from_db()

        # PUBLISHED -> IN_REVIEW forbidden
        qv.status = 'IN_REVIEW'
        with pytest.raises(ValidationError) as excinfo:
            qv.save()
        assert 'status' in excinfo.value.message_dict

    def test_archived_cannot_reactivate(self, test_user, competency):
        q = Question.objects.create(code='QST-REACT-001', created_by=test_user)
        qv = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            title='Archive Reactivate',
            prompt='P',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
            status='DRAFT',
        )
        transition_to_published(qv)
        qv.status = 'ARCHIVED'
        qv.save()

        # ARCHIVED -> DRAFT forbidden
        qv.status = 'DRAFT'
        with pytest.raises(ValidationError):
            qv.save()
        qv.refresh_from_db()

        # ARCHIVED -> PUBLISHED forbidden
        qv.status = 'PUBLISHED'
        with pytest.raises(ValidationError):
            qv.save()
        qv.refresh_from_db()

        # ARCHIVED -> IN_REVIEW forbidden
        qv.status = 'IN_REVIEW'
        with pytest.raises(ValidationError):
            qv.save()

    def test_deprecated_is_terminal_state(self, test_user, competency):
        q = Question.objects.create(code='QST-DEP-001', created_by=test_user)
        qv = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            title='Deprecated Test',
            prompt='P',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
            status='DRAFT',
        )
        transition_to_published(qv)
        qv.status = 'DEPRECATED'
        qv.save()

        # DEPRECATED -> any other status forbidden
        for target in ['DRAFT', 'IN_REVIEW', 'PUBLISHED', 'ARCHIVED']:
            qv.status = target
            with pytest.raises(ValidationError):
                qv.save()
            qv.refresh_from_db()


# ============================================================================
# 4. ACTIVE-VERSION INTEGRITY TESTS
# ============================================================================

@pytest.mark.django_db
class TestActiveVersionIntegrity:
    def test_active_version_success_when_published_and_same_question(self, test_user, competency):
        q = Question.objects.create(code='QST-ACT-001', created_by=test_user)
        qv = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            title='Published V1',
            prompt='P',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
            status='DRAFT',
        )
        transition_to_published(qv)

        q.active_version = qv
        q.save()
        q.refresh_from_db()
        assert q.active_version == qv

    def test_active_version_rejected_if_cross_question(self, test_user, competency):
        q1 = Question.objects.create(code='QST-ACT-Q1', created_by=test_user)
        q2 = Question.objects.create(code='QST-ACT-Q2', created_by=test_user)
        qv2 = QuestionVersion.objects.create(
            question=q2,
            version_number=1,
            title='Q2 V1',
            prompt='P',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
            status='DRAFT',
        )
        transition_to_published(qv2)

        # Assign q2's version as q1's active version
        q1.active_version = qv2
        with pytest.raises(ValidationError) as excinfo:
            q1.save()
        assert 'active_version' in excinfo.value.message_dict
        assert 'belong to this question' in str(excinfo.value)

    def test_active_version_rejected_if_not_published(self, test_user, competency):
        q = Question.objects.create(code='QST-ACT-UNPUB', created_by=test_user)
        qv = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            title='Draft V1',
            prompt='P',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
            status='DRAFT',
        )
        # Attempt to set DRAFT as active version
        q.active_version = qv
        with pytest.raises(ValidationError) as excinfo:
            q.save()
        assert 'active_version' in excinfo.value.message_dict
        assert 'PUBLISHED' in str(excinfo.value)

        # Attempt to set IN_REVIEW as active version
        qv.status = 'IN_REVIEW'
        qv.save()
        q.active_version = qv
        with pytest.raises(ValidationError) as excinfo:
            q.save()
        assert 'active_version' in excinfo.value.message_dict


# ============================================================================
# 5. PUBLIC CONTENT PAYLOAD CONFIDENTIALITY TESTS
# ============================================================================

@pytest.mark.django_db
class TestContentPayloadConfidentiality:
    def test_reject_top_level_confidential_keys(self, test_user, competency):
        q = Question.objects.create(code='QST-PAYLOAD-001', created_by=test_user)
        forbidden_keys = [
            'correct_payload',
            'correct_option_id',
            'correct_option_ids',
            'correct_value',
            'target_value',
            'expected_stdout',
            'scoring_rubric',
        ]
        for key in forbidden_keys:
            with pytest.raises(ValidationError) as excinfo:
                QuestionVersion.objects.create(
                    question=q,
                    version_number=1,
                    title='Leak Test',
                    prompt='Prompt',
                    question_type='SINGLE_CHOICE',
                    primary_competency=competency,
                    content_payload={key: 'forbidden'},
                )
            assert 'content_payload' in excinfo.value.message_dict
            assert key in str(excinfo.value)

    def test_reject_nested_confidential_keys(self, test_user, competency):
        q = Question.objects.create(code='QST-PAYLOAD-NEST', created_by=test_user)
        # Nested inside options list of dicts
        nested_payload = {
            'options': [
                {'id': 'opt_1', 'text': 'Option A'},
                {'id': 'opt_2', 'text': 'Option B', 'correct_option_id': 'opt_2'},
            ]
        }
        with pytest.raises(ValidationError) as excinfo:
            QuestionVersion.objects.create(
                question=q,
                version_number=1,
                title='Nested Leak',
                prompt='Prompt',
                question_type='SINGLE_CHOICE',
                primary_competency=competency,
                content_payload=nested_payload,
            )
        assert 'content_payload' in excinfo.value.message_dict
        assert 'correct_option_id' in str(excinfo.value)

    def test_valid_public_content_payload_succeeds(self, test_user, competency):
        q = Question.objects.create(code='QST-PAYLOAD-OK', created_by=test_user)
        valid_payload = {
            'options': [
                {'id': 'opt_1', 'text': 'Paris'},
                {'id': 'opt_2', 'text': 'London'},
            ],
            'unit': 'km',
            'placeholder': 'Type your answer',
        }
        qv = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            title='Valid Payload',
            prompt='Prompt',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
            content_payload=valid_payload,
        )
        assert qv.content_payload == valid_payload


# ============================================================================
# 6. COMPETENCY MAPPING CONSISTENCY TESTS
# ============================================================================

@pytest.mark.django_db
class TestQuestionCompetencyMappingModel:
    def test_create_mapping_success(self, test_user, competency, secondary_competency):
        q = Question.objects.create(code='QST-MAP-001', created_by=test_user)
        qv = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            title='Mapping Test',
            prompt='Prompt',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
            status='DRAFT',
        )
        mapping = QuestionCompetencyMapping.objects.create(
            question_version=qv,
            competency=secondary_competency,
            weight=Decimal('0.50'),
            is_primary=False,
        )
        assert mapping.weight == Decimal('0.50')
        assert mapping.is_primary is False

    def test_competency_protected_from_deletion(self, test_user, competency):
        q = Question.objects.create(code='QST-PROT-001', created_by=test_user)
        QuestionVersion.objects.create(
            question=q,
            version_number=1,
            title='Protected Test',
            prompt='Prompt',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
            status='DRAFT',
        )
        with pytest.raises(ProtectedError):
            competency.delete()

    def test_mapping_immutable_when_version_published(self, test_user, competency, secondary_competency):
        q = Question.objects.create(code='QST-MAP-IMM-001', created_by=test_user)
        qv = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            title='Mapping Imm Test',
            prompt='Prompt',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
            status='DRAFT',
        )
        m = QuestionCompetencyMapping.objects.create(
            question_version=qv,
            competency=secondary_competency,
            weight=Decimal('0.30'),
            is_primary=False,
        )
        transition_to_published(qv)

        # Modify mapping on published version raises ValidationError
        m.weight = Decimal('0.80')
        with pytest.raises(ValidationError):
            m.save()

        # Adding new mapping to published version raises ValidationError
        with pytest.raises(ValidationError):
            QuestionCompetencyMapping.objects.create(
                question_version=qv,
                competency=competency,
                weight=Decimal('1.00'),
                is_primary=True,
            )

    def test_primary_mapping_must_match_question_primary_competency(self, test_user, competency, secondary_competency):
        q = Question.objects.create(code='QST-MAP-PRI-001', created_by=test_user)
        qv = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            title='Primary Map Test',
            prompt='P',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
            status='DRAFT',
        )
        # Setting is_primary=True for secondary_competency (which is NOT qv.primary_competency) fails
        with pytest.raises(ValidationError) as excinfo:
            QuestionCompetencyMapping.objects.create(
                question_version=qv,
                competency=secondary_competency,
                weight=Decimal('1.00'),
                is_primary=True,
            )
        assert 'competency' in excinfo.value.message_dict

    def test_cannot_have_multiple_primary_mappings(self, test_user, competency):
        q = Question.objects.create(code='QST-MAP-DUP-PRI', created_by=test_user)
        qv = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            title='Dup Pri Test',
            prompt='P',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
            status='DRAFT',
        )
        # First primary mapping succeeds
        QuestionCompetencyMapping.objects.create(
            question_version=qv,
            competency=competency,
            weight=Decimal('1.00'),
            is_primary=True,
        )
        # Attempting second primary mapping raises ValidationError
        m2 = QuestionCompetencyMapping(
            question_version=qv,
            competency=competency,
            weight=Decimal('1.00'),
            is_primary=True,
        )
        with pytest.raises(ValidationError) as excinfo:
            m2.clean()
        assert 'is_primary' in excinfo.value.message_dict

    def test_primary_competency_cannot_be_secondary_mapping(self, test_user, competency):
        q = Question.objects.create(code='QST-MAP-SEC-CONF', created_by=test_user)
        qv = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            title='Conflicting Sec Map',
            prompt='P',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
            status='DRAFT',
        )
        # Mapping qv.primary_competency with is_primary=False raises ValidationError
        with pytest.raises(ValidationError) as excinfo:
            QuestionCompetencyMapping.objects.create(
                question_version=qv,
                competency=competency,
                weight=Decimal('0.50'),
                is_primary=False,
            )
        assert 'competency' in excinfo.value.message_dict


# ============================================================================
# 7. EVALUATION DATA & TABLE ISOLATION TESTS
# ============================================================================

@pytest.mark.django_db
class TestQuestionEvaluationDataModel:
    def test_evaluation_data_creation_and_isolation(self, test_user, competency):
        q = Question.objects.create(code='QST-EVAL-001', created_by=test_user)
        qv = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            title='Eval Test',
            prompt='Prompt',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
            status='DRAFT',
        )
        ed = QuestionEvaluationData.objects.create(
            question_version=qv,
            grading_strategy='EXACT_MATCH',
            correct_payload={'correct_option_id': 'opt_1'},
            scoring_rubric={'base_score': 10.0},
        )
        assert ed.question_version == qv
        assert str(ed) == f"EvaluationData for {qv}"
        assert ed.correct_payload['correct_option_id'] == 'opt_1'

    def test_evaluation_data_immutable_when_version_published(self, test_user, competency):
        q = Question.objects.create(code='QST-EVAL-IMM-001', created_by=test_user)
        qv = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            title='Published Eval',
            prompt='Prompt',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
            status='DRAFT',
        )
        ed = QuestionEvaluationData.objects.create(
            question_version=qv,
            grading_strategy='EXACT_MATCH',
            correct_payload={'correct_option_id': 'opt_1'},
        )
        transition_to_published(qv)

        # Attempt to edit evaluation data on published version
        ed.correct_payload = {'correct_option_id': 'opt_hacked'}
        with pytest.raises(ValidationError) as excinfo:
            ed.save()
        assert 'immutable' in str(excinfo.value)


# ============================================================================
# 8. TAG & VERSION-TAG TESTS
# ============================================================================

@pytest.mark.django_db
class TestTagAndQuestionVersionTag:
    def test_tag_creation_and_m2m_association(self, test_user, competency):
        q = Question.objects.create(code='QST-TAG-001', created_by=test_user)
        qv = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            title='Tag Test',
            prompt='Prompt',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
            status='DRAFT',
        )
        tag1 = Tag.objects.create(slug='recursion', name='Recursion', category='TOPIC')
        tag2 = Tag.objects.create(slug='python', name='Python', category='LANGUAGE')

        qv.tags.add(tag1, tag2)
        assert qv.tags.count() == 2
        assert tag1.tagged_versions.count() == 1

    def test_duplicate_version_tag_rejected(self, test_user, competency):
        q = Question.objects.create(code='QST-TAG-UQ-001', created_by=test_user)
        qv = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            title='Tag UQ Test',
            prompt='Prompt',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
            status='DRAFT',
        )
        tag = Tag.objects.create(slug='algorithms', name='Algorithms', category='TOPIC')
        QuestionVersionTag.objects.create(question_version=qv, tag=tag)

        with pytest.raises(IntegrityError):
            QuestionVersionTag.objects.create(question_version=qv, tag=tag)


# ============================================================================
# 9. DJANGO ADMIN PROTECTIONS & INLINE PERMISSIONS
# ============================================================================

@pytest.mark.django_db
class TestAdminProtections:
    def test_admin_readonly_fields_for_published_version(self, test_user, competency):
        q = Question.objects.create(code='QST-ADM-001', created_by=test_user)
        qv = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            title='Admin Readonly Test',
            prompt='P',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
            status='DRAFT',
        )
        site = AdminSite()
        admin_obj = QuestionVersionAdmin(QuestionVersion, site)
        rf = RequestFactory()
        req = rf.get('/admin/arena/questionversion/')
        req.user = test_user

        # Draft version: only published_at, created_at, updated_at are read-only
        draft_readonly = admin_obj.get_readonly_fields(req, qv)
        assert 'status' not in draft_readonly
        assert 'prompt' not in draft_readonly

        # Published version: status, prompt, created_by, published_at, etc. are read-only
        transition_to_published(qv)
        pub_readonly = admin_obj.get_readonly_fields(req, qv)
        assert 'status' in pub_readonly
        assert 'prompt' in pub_readonly
        assert 'created_by' in pub_readonly
        assert 'change_summary' in pub_readonly
        assert 'published_at' in pub_readonly

    def test_admin_inline_permissions_locked_on_published_version(self, test_user, competency):
        q = Question.objects.create(code='QST-ADM-INL', created_by=test_user)
        qv = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            title='Admin Inline Test',
            prompt='P',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
            status='DRAFT',
        )
        site = AdminSite()
        eval_inline = QuestionEvaluationDataInline(QuestionVersion, site)
        comp_inline = QuestionCompetencyMappingInline(QuestionVersion, site)
        tag_inline = QuestionVersionTagInline(QuestionVersion, site)

        rf = RequestFactory()
        req = rf.get('/admin/arena/questionversion/')
        test_user.is_staff = True
        test_user.is_superuser = True
        test_user.save()
        req.user = test_user

        # In draft, inlines are editable
        assert eval_inline.has_change_permission(req, qv) is True
        assert comp_inline.has_add_permission(req, qv) is True
        assert tag_inline.has_add_permission(req, qv) is True

        # In published, all inlines are strictly locked
        transition_to_published(qv)
        assert eval_inline.has_change_permission(req, qv) is False
        assert eval_inline.has_delete_permission(req, qv) is False
        assert comp_inline.has_add_permission(req, qv) is False
        assert comp_inline.has_change_permission(req, qv) is False
        assert comp_inline.has_delete_permission(req, qv) is False
        assert tag_inline.has_add_permission(req, qv) is False
        assert tag_inline.has_change_permission(req, qv) is False
        assert tag_inline.has_delete_permission(req, qv) is False

    def test_admin_archive_and_deprecate_actions(self, test_user, competency):
        q = Question.objects.create(code='QST-ADM-ACT', created_by=test_user)
        qv = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            title='Admin Action Test',
            prompt='P',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
            status='DRAFT',
        )
        transition_to_published(qv)

        site = AdminSite()
        admin_obj = QuestionVersionAdmin(QuestionVersion, site)
        rf = RequestFactory()
        req = rf.post('/admin/arena/questionversion/')
        req.user = test_user
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(req, 'session', {})
        setattr(req, '_messages', FallbackStorage(req))

        # Test archive action
        qs = QuestionVersion.objects.filter(pk=qv.pk)
        admin_obj.archive_versions(req, qs)
        qv.refresh_from_db()
        assert qv.status == 'ARCHIVED'

        # Test deprecate action
        admin_obj.deprecate_versions(req, qs)
        qv.refresh_from_db()
        assert qv.status == 'DEPRECATED'


# ============================================================================
# 10. WRITE PATHS & BYPASS LIMITATIONS DOCUMENTATION TESTS
# ============================================================================

@pytest.mark.django_db
class TestBypassLimitations:
    def test_raw_queryset_update_bypasses_model_clean(self, test_user, competency):
        """
        Documents the architectural boundary:
        Django's QuerySet.update() issues raw SQL and does NOT call model clean() or save().
        Therefore, immutability is an application/model-level invariant on standard write paths,
        not an in-engine database trigger.
        """
        q = Question.objects.create(code='QST-BYPASS-001', created_by=test_user)
        qv = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            title='Bypass Test',
            prompt='Original Prompt',
            question_type='SINGLE_CHOICE',
            primary_competency=competency,
            status='DRAFT',
        )
        transition_to_published(qv)

        # Standard save() is blocked
        qv.prompt = 'Modified Prompt'
        with pytest.raises(ValidationError):
            qv.save()

        # QuerySet.update() executes direct SQL
        updated_rows = QuestionVersion.objects.filter(pk=qv.pk).update(prompt='Direct SQL Update')
        assert updated_rows == 1
        qv.refresh_from_db()
        assert qv.prompt == 'Direct SQL Update'


# ============================================================================
# 11. LIFECYCLE ACTION ACTIVE-VERSION RECONCILIATION & ATOMICITY TESTS
# ============================================================================

@pytest.mark.django_db
class TestLifecycleActionActiveVersionReconciliation:
    def _create_admin_request(self, user):
        rf = RequestFactory()
        req = rf.post('/admin/arena/questionversion/')
        user.is_staff = True
        user.is_superuser = True
        user.save()
        req.user = user
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(req, 'session', {})
        setattr(req, '_messages', FallbackStorage(req))
        return req

    def test_archive_active_version_with_replacement(self, test_user, competency):
        """1. Archiving an active version with another published version available."""
        q = Question.objects.create(code='QST-RECON-001', created_by=test_user)
        v1 = QuestionVersion.objects.create(
            question=q, version_number=1, title='V1', prompt='P1',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        transition_to_published(v1)

        v2 = QuestionVersion.objects.create(
            question=q, version_number=2, title='V2', prompt='P2',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        transition_to_published(v2)

        # q's active version is v2
        q.active_version = v2
        q.save()

        site = AdminSite()
        admin_obj = QuestionVersionAdmin(QuestionVersion, site)
        req = self._create_admin_request(test_user)

        # Archive v2
        admin_obj.archive_versions(req, QuestionVersion.objects.filter(pk=v2.pk))
        v2.refresh_from_db()
        q.refresh_from_db()

        assert v2.status == 'ARCHIVED'
        assert q.active_version == v1  # Reconciled to v1!

    def test_archive_active_version_without_replacement(self, test_user, competency):
        """2. Archiving an active version without a replacement."""
        q = Question.objects.create(code='QST-RECON-002', created_by=test_user)
        v1 = QuestionVersion.objects.create(
            question=q, version_number=1, title='V1', prompt='P1',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        transition_to_published(v1)
        q.active_version = v1
        q.save()

        site = AdminSite()
        admin_obj = QuestionVersionAdmin(QuestionVersion, site)
        req = self._create_admin_request(test_user)

        # Archive v1 (only version)
        admin_obj.archive_versions(req, QuestionVersion.objects.filter(pk=v1.pk))
        v1.refresh_from_db()
        q.refresh_from_db()

        assert v1.status == 'ARCHIVED'
        assert q.active_version is None  # Safely cleared!

    def test_deprecate_active_version_with_replacement(self, test_user, competency):
        """3. Deprecating an active version with another published version available."""
        q = Question.objects.create(code='QST-RECON-003', created_by=test_user)
        v1 = QuestionVersion.objects.create(
            question=q, version_number=1, title='V1', prompt='P1',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        transition_to_published(v1)

        v2 = QuestionVersion.objects.create(
            question=q, version_number=2, title='V2', prompt='P2',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        transition_to_published(v2)
        q.active_version = v2
        q.save()

        site = AdminSite()
        admin_obj = QuestionVersionAdmin(QuestionVersion, site)
        req = self._create_admin_request(test_user)

        # Deprecate v2
        admin_obj.deprecate_versions(req, QuestionVersion.objects.filter(pk=v2.pk))
        v2.refresh_from_db()
        q.refresh_from_db()

        assert v2.status == 'DEPRECATED'
        assert q.active_version == v1  # Reconciled to v1!

    def test_deprecate_active_version_without_replacement(self, test_user, competency):
        """4. Deprecating an active version without a replacement."""
        q = Question.objects.create(code='QST-RECON-004', created_by=test_user)
        v1 = QuestionVersion.objects.create(
            question=q, version_number=1, title='V1', prompt='P1',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        transition_to_published(v1)
        q.active_version = v1
        q.save()

        site = AdminSite()
        admin_obj = QuestionVersionAdmin(QuestionVersion, site)
        req = self._create_admin_request(test_user)

        # Deprecate v1
        admin_obj.deprecate_versions(req, QuestionVersion.objects.filter(pk=v1.pk))
        v1.refresh_from_db()
        q.refresh_from_db()

        assert v1.status == 'DEPRECATED'
        assert q.active_version is None  # Cleared!

    def test_replacement_never_selects_another_question_version(self, test_user, competency):
        """5. Ensuring the replacement belongs to the same Question."""
        q1 = Question.objects.create(code='QST-RECON-Q1', created_by=test_user)
        v1_q1 = QuestionVersion.objects.create(
            question=q1, version_number=1, title='Q1 V1', prompt='P1',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        transition_to_published(v1_q1)
        q1.active_version = v1_q1
        q1.save()

        q2 = Question.objects.create(code='QST-RECON-Q2', created_by=test_user)
        v1_q2 = QuestionVersion.objects.create(
            question=q2, version_number=1, title='Q2 V1', prompt='P2',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        transition_to_published(v1_q2)
        q2.active_version = v1_q2
        q2.save()

        site = AdminSite()
        admin_obj = QuestionVersionAdmin(QuestionVersion, site)
        req = self._create_admin_request(test_user)

        # Archive Q1's version. Even though Q2 has a published version, Q1 must NOT select Q2's version!
        admin_obj.archive_versions(req, QuestionVersion.objects.filter(pk=v1_q1.pk))
        q1.refresh_from_db()
        q2.refresh_from_db()

        assert q1.active_version is None
        assert q2.active_version == v1_q2

    def test_unpublished_version_never_selected_as_replacement(self, test_user, competency):
        """6. Ensuring an unpublished version is never selected."""
        q = Question.objects.create(code='QST-RECON-UNPUB', created_by=test_user)
        # v1 is DRAFT
        v1 = QuestionVersion.objects.create(
            question=q, version_number=1, title='V1', prompt='P1',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        # v2 is IN_REVIEW
        v2 = QuestionVersion.objects.create(
            question=q, version_number=2, title='V2', prompt='P2',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        v2.status = 'IN_REVIEW'
        v2.save()
        # v3 is PUBLISHED (active)
        v3 = QuestionVersion.objects.create(
            question=q, version_number=3, title='V3', prompt='P3',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        transition_to_published(v3)
        q.active_version = v3
        q.save()

        site = AdminSite()
        admin_obj = QuestionVersionAdmin(QuestionVersion, site)
        req = self._create_admin_request(test_user)

        admin_obj.archive_versions(req, QuestionVersion.objects.filter(pk=v3.pk))
        q.refresh_from_db()

        assert q.active_version is None  # Did not pick v1 (DRAFT) or v2 (IN_REVIEW)
        assert q.active_version not in (v1, v2)

    def test_bulk_archive_atomic_rollback_on_failure(self, test_user, competency, monkeypatch):
        """7. Bulk archive rollback when one record fails."""
        q1 = Question.objects.create(code='QST-ROLL-001', created_by=test_user)
        v1 = QuestionVersion.objects.create(
            question=q1, version_number=1, title='V1', prompt='P1',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        transition_to_published(v1)
        q1.active_version = v1
        q1.save()

        q2 = Question.objects.create(code='QST-ROLL-002', created_by=test_user)
        v2 = QuestionVersion.objects.create(
            question=q2, version_number=1, title='V2', prompt='P2',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        transition_to_published(v2)
        q2.active_version = v2
        q2.save()

        site = AdminSite()
        admin_obj = QuestionVersionAdmin(QuestionVersion, site)
        req = self._create_admin_request(test_user)

        # Force save on v2 to raise an unexpected database exception
        orig_save = QuestionVersion.save
        def faulty_save(self_instance, *args, **kwargs):
            if self_instance.pk == v2.pk and self_instance.status == 'ARCHIVED':
                raise RuntimeError("Simulated database failure during bulk archive")
            return orig_save(self_instance, *args, **kwargs)

        monkeypatch.setattr(QuestionVersion, 'save', faulty_save)

        qs = QuestionVersion.objects.filter(pk__in=[v1.pk, v2.pk]).order_by('version_number')
        with pytest.raises(RuntimeError):
            admin_obj.archive_versions(req, qs)

        # Confirm atomic rollback: v1 was NOT archived, and q1.active_version is unchanged!
        v1.refresh_from_db()
        v2.refresh_from_db()
        q1.refresh_from_db()
        q2.refresh_from_db()

        assert v1.status == 'PUBLISHED'
        assert v2.status == 'PUBLISHED'
        assert q1.active_version == v1
        assert q2.active_version == v2

    def test_bulk_deprecate_atomic_rollback_on_failure(self, test_user, competency, monkeypatch):
        """8. Bulk deprecate rollback when one record fails."""
        q1 = Question.objects.create(code='QST-ROLL-DEP-001', created_by=test_user)
        v1 = QuestionVersion.objects.create(
            question=q1, version_number=1, title='V1', prompt='P1',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        transition_to_published(v1)
        q1.active_version = v1
        q1.save()

        q2 = Question.objects.create(code='QST-ROLL-DEP-002', created_by=test_user)
        v2 = QuestionVersion.objects.create(
            question=q2, version_number=1, title='V2', prompt='P2',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        transition_to_published(v2)
        q2.active_version = v2
        q2.save()

        site = AdminSite()
        admin_obj = QuestionVersionAdmin(QuestionVersion, site)
        req = self._create_admin_request(test_user)

        orig_save = QuestionVersion.save
        def faulty_save(self_instance, *args, **kwargs):
            if self_instance.pk == v2.pk and self_instance.status == 'DEPRECATED':
                raise RuntimeError("Simulated database failure during bulk deprecate")
            return orig_save(self_instance, *args, **kwargs)

        monkeypatch.setattr(QuestionVersion, 'save', faulty_save)

        qs = QuestionVersion.objects.filter(pk__in=[v1.pk, v2.pk]).order_by('version_number')
        with pytest.raises(RuntimeError):
            admin_obj.deprecate_versions(req, qs)

        # Confirm rollback: both remain PUBLISHED and active
        v1.refresh_from_db()
        v2.refresh_from_db()
        q1.refresh_from_db()
        q2.refresh_from_db()

        assert v1.status == 'PUBLISHED'
        assert v2.status == 'PUBLISHED'
        assert q1.active_version == v1
        assert q2.active_version == v2

    def test_active_pointers_remain_unchanged_when_operation_rejected(self, test_user, competency):
        """9. Confirming existing active pointers remain unchanged when an operation is rejected."""
        q = Question.objects.create(code='QST-RECON-REJ', created_by=test_user)
        v1 = QuestionVersion.objects.create(
            question=q, version_number=1, title='V1', prompt='P1',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        transition_to_published(v1)
        q.active_version = v1
        q.save()

        # Attempt to transition v1 to an invalid status (e.g. DRAFT)
        with pytest.raises(ValidationError):
            reconcile_active_version_on_lifecycle_transition(v1, 'DRAFT')

        q.refresh_from_db()
        v1.refresh_from_db()

        assert v1.status == 'PUBLISHED'
        assert q.active_version == v1  # Active pointer completely intact!


# ============================================================================
# 12. DIRECT MODEL SAVE ACTIVE-VERSION RECONCILIATION TESTS (PHASE 2B.3.2)
# ============================================================================

@pytest.mark.django_db
class TestDirectModelSaveActiveVersionReconciliation:
    def test_direct_save_archives_active_version_with_replacement(self, test_user, competency):
        """Direct model save archives an active version and selects a valid replacement."""
        q = Question.objects.create(code='QST-DSAVE-001', created_by=test_user)
        v1 = QuestionVersion.objects.create(
            question=q, version_number=1, title='V1', prompt='P1',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        transition_to_published(v1)

        v2 = QuestionVersion.objects.create(
            question=q, version_number=2, title='V2', prompt='P2',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        transition_to_published(v2)

        q.active_version = v2
        q.save()

        # Direct Model.save() call (no admin action, no helper function)
        v2.status = 'ARCHIVED'
        v2.save()

        v2.refresh_from_db()
        q.refresh_from_db()

        assert v2.status == 'ARCHIVED'
        assert q.active_version == v1  # Reconciled automatically to v1!

    def test_direct_save_archives_active_version_clears_pointer_when_no_replacement(self, test_user, competency):
        """Direct model save archives an active version and clears the pointer when no replacement exists."""
        q = Question.objects.create(code='QST-DSAVE-002', created_by=test_user)
        v1 = QuestionVersion.objects.create(
            question=q, version_number=1, title='V1', prompt='P1',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        transition_to_published(v1)
        q.active_version = v1
        q.save()

        # Direct Model.save() call
        v1.status = 'ARCHIVED'
        v1.save()

        v1.refresh_from_db()
        q.refresh_from_db()

        assert v1.status == 'ARCHIVED'
        assert q.active_version is None  # Pointer cleared!

    def test_direct_save_deprecates_active_version_and_reconciles(self, test_user, competency):
        """Direct model save deprecates an active version and reconciles the pointer."""
        q = Question.objects.create(code='QST-DSAVE-003', created_by=test_user)
        v1 = QuestionVersion.objects.create(
            question=q, version_number=1, title='V1', prompt='P1',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        transition_to_published(v1)

        v2 = QuestionVersion.objects.create(
            question=q, version_number=2, title='V2', prompt='P2',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        transition_to_published(v2)
        q.active_version = v2
        q.save()

        # Direct Model.save() deprecating v2
        v2.status = 'DEPRECATED'
        v2.save()

        v2.refresh_from_db()
        q.refresh_from_db()

        assert v2.status == 'DEPRECATED'
        assert q.active_version == v1  # Reconciled to v1!

        # Direct Model.save() deprecating v1 (no replacements remain)
        v1.status = 'DEPRECATED'
        v1.save()

        v1.refresh_from_db()
        q.refresh_from_db()

        assert v1.status == 'DEPRECATED'
        assert q.active_version is None  # Cleared!

    def test_direct_save_failed_version_transition_rolls_back_pointer(self, test_user, competency, monkeypatch):
        """A failed version transition rolls back pointer changes."""
        q = Question.objects.create(code='QST-DSAVE-FAIL', created_by=test_user)
        v1 = QuestionVersion.objects.create(
            question=q, version_number=1, title='V1', prompt='P1',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        transition_to_published(v1)

        v2 = QuestionVersion.objects.create(
            question=q, version_number=2, title='V2', prompt='P2',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        transition_to_published(v2)

        q.active_version = v2
        q.save()

        # Cause Model.save on v2 to fail during persistence
        from django.db.models import Model
        orig_model_save = Model.save
        def broken_model_save(self_instance, *args, **kwargs):
            if isinstance(self_instance, QuestionVersion) and self_instance.pk == v2.pk and self_instance.status == 'ARCHIVED':
                raise RuntimeError("Simulated failure during version row persistence")
            return orig_model_save(self_instance, *args, **kwargs)

        monkeypatch.setattr(Model, 'save', broken_model_save)

        v2.status = 'ARCHIVED'
        with pytest.raises(RuntimeError):
            v2.save()

        # Both v2 and q.active_version must remain untouched (rolled back!)
        v2.refresh_from_db()
        q.refresh_from_db()

        assert v2.status == 'PUBLISHED'
        assert q.active_version == v2  # Did not prematurely change to v1!


class TestUpdateFieldsActiveVersionReconciliation:
    """
    Focused regression tests for QuestionVersion.save(update_fields=...) behavior.
    Verifies that active-version reconciliation occurs only when the status field
    will actually be persisted to the database.
    """

    def test_archived_in_memory_save_without_status_in_update_fields_skips_reconciliation(self, test_user, competency):
        """Active version changed in memory to ARCHIVED with update_fields omitting status does not reconcile."""
        q = Question.objects.create(code='QST-UF-001', created_by=test_user)
        v1 = QuestionVersion.objects.create(
            question=q, version_number=1, title='V1', prompt='P1',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        transition_to_published(v1)

        v2 = QuestionVersion.objects.create(
            question=q, version_number=2, title='V2', prompt='P2',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
            change_summary='Initial v2',
        )
        transition_to_published(v2)

        q.active_version = v2
        q.save()

        # In-memory change to ARCHIVED, but save with update_fields=['change_summary']
        v2.status = 'ARCHIVED'
        v2.change_summary = 'Initial v2'  # Keep substantive value unchanged to satisfy clean()
        v2.save(update_fields=['change_summary'])

        v2.refresh_from_db()
        q.refresh_from_db()

        # Database status must remain PUBLISHED, active pointer must remain v2
        assert v2.status == 'PUBLISHED'
        assert q.active_version == v2

    def test_deprecated_in_memory_save_without_status_in_update_fields_skips_reconciliation(self, test_user, competency):
        """Active version changed in memory to DEPRECATED with update_fields omitting status does not reconcile."""
        q = Question.objects.create(code='QST-UF-002', created_by=test_user)
        v1 = QuestionVersion.objects.create(
            question=q, version_number=1, title='V1', prompt='P1',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        transition_to_published(v1)

        v2 = QuestionVersion.objects.create(
            question=q, version_number=2, title='V2', prompt='P2',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        transition_to_published(v2)

        q.active_version = v2
        q.save()

        # In-memory change to DEPRECATED, but save with update_fields=['title']
        v2.status = 'DEPRECATED'
        v2.title = 'V2'  # Keep substantive value unchanged to satisfy clean()
        v2.save(update_fields=['title'])

        v2.refresh_from_db()
        q.refresh_from_db()

        # Database status must remain PUBLISHED, active pointer must remain v2
        assert v2.status == 'PUBLISHED'
        assert q.active_version == v2

    def test_archiving_with_status_in_update_fields_persists_and_reconciles(self, test_user, competency):
        """Active version archived using save(update_fields=['status']) persists status and reconciles pointer."""
        q = Question.objects.create(code='QST-UF-003', created_by=test_user)
        v1 = QuestionVersion.objects.create(
            question=q, version_number=1, title='V1', prompt='P1',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        transition_to_published(v1)

        v2 = QuestionVersion.objects.create(
            question=q, version_number=2, title='V2', prompt='P2',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        transition_to_published(v2)

        q.active_version = v2
        q.save()

        # Archive using update_fields=['status']
        v2.status = 'ARCHIVED'
        v2.save(update_fields=['status'])

        v2.refresh_from_db()
        q.refresh_from_db()

        # Status persists as ARCHIVED, active pointer is reconciled to v1
        assert v2.status == 'ARCHIVED'
        assert q.active_version == v1

    def test_normal_full_save_after_active_version_archived_reconciles(self, test_user, competency):
        """Normal full save() after an active version is archived preserves existing reconciliation behavior."""
        q = Question.objects.create(code='QST-UF-004', created_by=test_user)
        v1 = QuestionVersion.objects.create(
            question=q, version_number=1, title='V1', prompt='P1',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        transition_to_published(v1)

        v2 = QuestionVersion.objects.create(
            question=q, version_number=2, title='V2', prompt='P2',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        transition_to_published(v2)

        q.active_version = v2
        q.save()

        # Full save without update_fields (update_fields=None)
        v2.status = 'ARCHIVED'
        v2.save()

        v2.refresh_from_db()
        q.refresh_from_db()

        assert v2.status == 'ARCHIVED'
        assert q.active_version == v1

    def test_positional_update_fields_invocation_matches_keyword_form(self, test_user, competency):
        """Positional update_fields invocation behaves identically to the keyword form."""
        q = Question.objects.create(code='QST-UF-005', created_by=test_user)
        v1 = QuestionVersion.objects.create(
            question=q, version_number=1, title='V1', prompt='P1',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
        )
        transition_to_published(v1)

        v2 = QuestionVersion.objects.create(
            question=q, version_number=2, title='V2', prompt='P2',
            question_type='SINGLE_CHOICE', primary_competency=competency, status='DRAFT',
            change_summary='Positional test',
        )
        transition_to_published(v2)

        q.active_version = v2
        q.save()

        # 1. Positional invocation omitting 'status' at index 3: (force_insert, force_update, using, update_fields)
        v2.status = 'ARCHIVED'
        v2.change_summary = 'Positional test'
        v2.save(False, False, None, ['change_summary'])

        v2.refresh_from_db()
        q.refresh_from_db()

        assert v2.status == 'PUBLISHED'
        assert q.active_version == v2

        # 2. Positional invocation including 'status' at index 3
        v2.status = 'ARCHIVED'
        v2.save(False, False, None, ['status'])

        v2.refresh_from_db()
        q.refresh_from_db()

        assert v2.status == 'ARCHIVED'
        assert q.active_version == v1

