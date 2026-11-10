"""
Tests for ZENTIQ Arena QuestionService (Phase 2C.2).
Covers QuestionService public methods, atomic creation workflow, code generation & collision handling,
nested savepoint isolation, authorization guards, selectable question queries, deprecation, and scope discipline.
"""
from decimal import Decimal
from pathlib import Path
import sys
from unittest.mock import patch
import uuid

# Ensure backend root is on sys.path
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.arena.models import (
    Question,
    QuestionCompetencyMapping,
    QuestionEvaluationData,
    QuestionVersion,
    QuestionVersionTag,
    Tag,
)
from apps.arena.services import (
    ActiveVersionIntegrityError,
    ArenaServiceError,
    CompetencyNotFoundError,
    InactiveCompetencyError,
    QuestionAlreadyDeprecatedError,
    QuestionCodeGenerationError,
    QuestionCompositionService,
    QuestionDeprecatedError,
    QuestionNoActiveVersionError,
    QuestionNotFoundError,
    QuestionPermissionDeniedError,
    QuestionService,
    QuestionValidationError,
    TagNotFoundError,
    can_create_question,
    can_deprecate_question,
    can_view_question,
    generate_canonical_code,
)
from apps.skills.models import Competency, Domain, Subdomain

User = get_user_model()


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def author_user(db):
    user = User.objects.create_user(
        email='author@example.com',
        password='TestPassword123!',
    )
    # Grant arena.add_question so author can create questions in test scenarios
    content_type = ContentType.objects.get_for_model(Question)
    perm = Permission.objects.get(codename='add_question', content_type=content_type)
    user.user_permissions.add(perm)
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
def superuser(db):
    return User.objects.create_superuser(
        email='admin@example.com',
        password='TestPassword123!',
    )


@pytest.fixture
def domain(db):
    return Domain.objects.create(
        slug='cognitive_logic',
        name='Cognitive Logic',
        category='COGNITIVE',
        description='Logical reasoning and analysis',
        display_order=1,
    )


@pytest.fixture
def subdomain(db, domain):
    return Subdomain.objects.create(
        domain=domain,
        slug='deductive_reasoning',
        name='Deductive Reasoning',
        display_order=1,
    )


@pytest.fixture
def primary_competency(db, subdomain):
    return Competency.objects.create(
        subdomain=subdomain,
        code='NUM-ARITH-01',
        name='Arithmetic Operations',
        description='Evaluate mental arithmetic',
        bloom_level='APPLY',
        is_active=True,
    )


@pytest.fixture
def inactive_competency(db, subdomain):
    return Competency.objects.create(
        subdomain=subdomain,
        code='NUM-OLD-01',
        name='Legacy Arithmetic',
        description='Retired competency',
        bloom_level='APPLY',
        is_active=False,
    )


@pytest.fixture
def sample_tag(db):
    return Tag.objects.create(
        slug='math-foundations',
        name='Math Foundations',
        category='TOPIC',
    )


def publish_version(v: QuestionVersion) -> QuestionVersion:
    """Helper transitioning QuestionVersion through valid lifecycle state transitions to PUBLISHED."""
    v.status = 'IN_REVIEW'
    v.save()
    v.status = 'PUBLISHED'
    v.save()
    return v



# -----------------------------------------------------------------------------
# Part 1: Authentication & Active-User Invariants
# -----------------------------------------------------------------------------

class TestAuthorizationAndActiveUser:
    """Verifies authentication, active-user checks, and superuser bypass ordering."""

    def test_create_question_anonymous_rejected(self, primary_competency):
        with pytest.raises(QuestionPermissionDeniedError, match="Authentication required"):
            QuestionService.create_question(
                primary_competency=primary_competency,
                title="Test Question",
                prompt="Question stem",
                question_type="SINGLE_CHOICE",
                user=None,
            )

    def test_create_question_inactive_user_rejected(self, author_user, primary_competency):
        author_user.is_active = False
        author_user.save()
        with pytest.raises(QuestionPermissionDeniedError, match="User account is inactive"):
            QuestionService.create_question(
                primary_competency=primary_competency,
                title="Test Question",
                prompt="Question stem",
                question_type="SINGLE_CHOICE",
                user=author_user,
            )

    def test_create_question_inactive_superuser_rejected(self, superuser, primary_competency):
        superuser.is_active = False
        superuser.save()
        with pytest.raises(QuestionPermissionDeniedError, match="User account is inactive"):
            QuestionService.create_question(
                primary_competency=primary_competency,
                title="Test Question",
                prompt="Question stem",
                question_type="SINGLE_CHOICE",
                user=superuser,
            )

    def test_create_question_staff_without_perm_rejected(self, staff_user, primary_competency):
        with pytest.raises(QuestionPermissionDeniedError, match="arena.add_question"):
            QuestionService.create_question(
                primary_competency=primary_competency,
                title="Test Question",
                prompt="Question stem",
                question_type="SINGLE_CHOICE",
                user=staff_user,
            )

    def test_create_question_active_superuser_permitted(self, superuser, primary_competency):
        question, version = QuestionService.create_question(
            primary_competency=primary_competency,
            title="Superuser Question",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=superuser,
        )
        assert question.pk is not None
        assert question.created_by == superuser

    def test_get_question_anonymous_rejected(self, author_user, primary_competency):
        question, _ = QuestionService.create_question(
            primary_competency=primary_competency,
            title="Question",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )
        with pytest.raises(QuestionPermissionDeniedError, match="Authentication required"):
            QuestionService.get_question(question.pk, user=None)

    def test_get_question_inactive_superuser_rejected(self, superuser, author_user, primary_competency):
        question, _ = QuestionService.create_question(
            primary_competency=primary_competency,
            title="Question",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )
        superuser.is_active = False
        superuser.save()
        with pytest.raises(QuestionPermissionDeniedError, match="User account is inactive"):
            QuestionService.get_question(question.pk, user=superuser)

    def test_get_question_unauthorized_user_denied(self, author_user, unprivileged_user, primary_competency):
        question, _ = QuestionService.create_question(
            primary_competency=primary_competency,
            title="Question",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )
        with pytest.raises(QuestionPermissionDeniedError, match="not authorized to view"):
            QuestionService.get_question(question.pk, user=unprivileged_user)

    def test_get_question_author_permitted(self, author_user, primary_competency):
        question, _ = QuestionService.create_question(
            primary_competency=primary_competency,
            title="Author Question",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )
        retrieved = QuestionService.get_question(question.pk, user=author_user)
        assert retrieved.pk == question.pk

    def test_deprecate_question_anonymous_rejected(self, author_user, primary_competency):
        question, _ = QuestionService.create_question(
            primary_competency=primary_competency,
            title="Question",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )
        with pytest.raises(QuestionPermissionDeniedError, match="Authentication required"):
            QuestionService.deprecate_question(question.pk, user=None)

    def test_deprecate_question_inactive_superuser_rejected(self, superuser, author_user, primary_competency):
        question, _ = QuestionService.create_question(
            primary_competency=primary_competency,
            title="Question",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )
        superuser.is_active = False
        superuser.save()
        with pytest.raises(QuestionPermissionDeniedError, match="User account is inactive"):
            QuestionService.deprecate_question(question.pk, user=superuser)

    def test_deprecate_question_author_alone_rejected(self, author_user, primary_competency):
        # Authors do NOT possess deprecation privileges solely through ownership
        question, _ = QuestionService.create_question(
            primary_competency=primary_competency,
            title="Author Question",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )
        with pytest.raises(QuestionPermissionDeniedError, match="arena.change_question"):
            QuestionService.deprecate_question(question.pk, user=author_user)

    def test_deprecate_question_staff_without_perm_rejected(self, staff_user, author_user, primary_competency):
        question, _ = QuestionService.create_question(
            primary_competency=primary_competency,
            title="Question",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )
        with pytest.raises(QuestionPermissionDeniedError, match="arena.change_question"):
            QuestionService.deprecate_question(question.pk, user=staff_user)


# -----------------------------------------------------------------------------
# Part 2: Question Creation & Consistency
# -----------------------------------------------------------------------------

class TestQuestionCreation:
    """Verifies atomic question creation workflow, validations, and content payloads."""

    def test_create_question_happy_path(self, author_user, primary_competency):
        question, version = QuestionService.create_question(
            primary_competency=primary_competency,
            title="Calculate Sum",
            prompt="What is 2 + 2?",
            question_type="SINGLE_CHOICE",
            user=author_user,
            difficulty_tier="BEGINNER",
            bloom_level="UNDERSTAND",
            time_limit_seconds=45,
            explanation="2 + 2 equals 4.",
        )
        assert question.pk is not None
        assert question.code.startswith("QST-NUM-ARITH-")
        assert question.created_by == author_user
        assert question.active_version is None
        assert question.is_deprecated is False

        assert version.pk is not None
        assert version.question == question
        assert version.version_number == 1
        assert version.status == "DRAFT"
        assert version.title == "Calculate Sum"
        assert version.prompt == "What is 2 + 2?"
        assert version.difficulty_tier == "BEGINNER"
        assert version.bloom_level == "UNDERSTAND"
        assert version.time_limit_seconds == 45
        assert version.created_by == author_user
        assert version.content_payload == {}

        mapping = QuestionCompetencyMapping.objects.get(question_version=version)
        assert mapping.competency == primary_competency
        assert mapping.is_primary is True
        assert mapping.weight == Decimal("1.00")

    def test_create_question_reloads_fresh_competency(self, author_user, primary_competency):
        # Pass integer ID instead of instance to verify fresh database reload
        question, version = QuestionService.create_question(
            primary_competency=primary_competency.pk,
            title="Fresh Reload Test",
            prompt="Prompt text",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )
        assert version.primary_competency == primary_competency

    def test_create_question_rejects_inactive_competency(self, author_user, inactive_competency):
        with pytest.raises(InactiveCompetencyError) as exc_info:
            QuestionService.create_question(
                primary_competency=inactive_competency,
                title="Inactive Competency Test",
                prompt="Prompt text",
                question_type="SINGLE_CHOICE",
                user=author_user,
            )
        assert exc_info.value.code == 'inactive_competency'
        assert exc_info.value.details['is_active'] is False

    def test_create_question_missing_competency(self, author_user):
        with pytest.raises(CompetencyNotFoundError):
            QuestionService.create_question(
                primary_competency=999999,
                title="Missing Competency Test",
                prompt="Prompt text",
                question_type="SINGLE_CHOICE",
                user=author_user,
            )

    def test_create_question_content_payload_omitted_defaults_to_dict(self, author_user, primary_competency):
        _, version = QuestionService.create_question(
            primary_competency=primary_competency,
            title="Default Payload",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
            content_payload=None,
        )
        assert version.content_payload == {}

    def test_create_question_content_payload_accepts_list(self, author_user, primary_competency):
        payload = [{"id": 1, "text": "Option A"}, {"id": 2, "text": "Option B"}]
        _, version = QuestionService.create_question(
            primary_competency=primary_competency,
            title="List Payload",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
            content_payload=payload,
        )
        assert version.content_payload == payload

    def test_create_question_rejects_confidential_payload(self, author_user, primary_competency):
        leaked_payload = {"options": ["A", "B"], "correct_option_id": "opt-1"}
        with pytest.raises(QuestionValidationError, match="Confidential evaluation keys are forbidden"):
            QuestionService.create_question(
                primary_competency=primary_competency,
                title="Leaked Payload",
                prompt="Prompt",
                question_type="SINGLE_CHOICE",
                user=author_user,
                content_payload=leaked_payload,
            )

    def test_create_question_invalid_time_limit_raises_validation_error(self, author_user, primary_competency):
        with pytest.raises(QuestionValidationError) as exc_info:
            QuestionService.create_question(
                primary_competency=primary_competency,
                title="Invalid Time Limit",
                prompt="Prompt",
                question_type="SINGLE_CHOICE",
                user=author_user,
                time_limit_seconds=1,  # Below minimum (5)
            )
        assert 'time_limit_seconds' in exc_info.value.details

    def test_create_question_invalid_question_type_raises_validation_error(self, author_user, primary_competency):
        with pytest.raises(QuestionValidationError) as exc_info:
            QuestionService.create_question(
                primary_competency=primary_competency,
                title="Invalid Type",
                prompt="Prompt",
                question_type="NON_EXISTENT_TYPE",
                user=author_user,
            )
        assert 'question_type' in exc_info.value.details


# -----------------------------------------------------------------------------
# Part 3: Initial Tag Composition Integration
# -----------------------------------------------------------------------------

class TestInitialTagComposition:
    """Verifies atomic tag synchronization through QuestionCompositionService."""

    def test_create_question_with_valid_tags(self, author_user, primary_competency, sample_tag):
        question, version = QuestionService.create_question(
            primary_competency=primary_competency,
            title="Tagged Question",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
            tags=['math-foundations'],
        )
        version_tags = QuestionVersionTag.objects.filter(question_version=version)
        assert version_tags.count() == 1
        assert version_tags.first().tag == sample_tag

    def test_create_question_with_missing_tag_rolls_back_entire_creation(self, author_user, primary_competency):
        initial_q_count = Question.objects.count()
        initial_qv_count = QuestionVersion.objects.count()
        initial_m_count = QuestionCompetencyMapping.objects.count()

        with pytest.raises(TagNotFoundError):
            QuestionService.create_question(
                primary_competency=primary_competency,
                title="Rollback Tagged Question",
                prompt="Prompt",
                question_type="SINGLE_CHOICE",
                user=author_user,
                tags=['non-existent-tag-slug'],
            )

        assert Question.objects.count() == initial_q_count
        assert QuestionVersion.objects.count() == initial_qv_count
        assert QuestionCompetencyMapping.objects.count() == initial_m_count

    def test_create_question_empty_tags_list_no_op(self, author_user, primary_competency):
        _, version = QuestionService.create_question(
            primary_competency=primary_competency,
            title="Empty Tags",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
            tags=[],
        )
        assert QuestionVersionTag.objects.filter(question_version=version).count() == 0


# -----------------------------------------------------------------------------
# Part 4: Canonical Code Generation & Concurrency Resolution
# -----------------------------------------------------------------------------

class TestCanonicalCodeGenerationAndConcurrency:
    """Verifies format rules, pre-existing collision retry, concurrent DB retry, and outer transaction integrity."""

    def test_generate_canonical_code_format(self):
        code = generate_canonical_code("NUM-ARITH-01")
        assert code.startswith("QST-NUM-ARITH-")
        assert len(code) <= 40
        assert code.isupper()

    def test_generate_canonical_code_strips_suffix(self):
        code = generate_canonical_code("PROG-CTRL-99")
        assert code.startswith("QST-PROG-CTRL-")

    def test_pre_existing_code_collision_retry_success(self, author_user, primary_competency):
        # First question with fixed code
        q1, _ = QuestionService.create_question(
            primary_competency=primary_competency,
            title="First Question",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )

        with patch('apps.arena.services.question_service.generate_canonical_code') as mock_code:
            mock_code.side_effect = [q1.code, "QST-NUM-ARITH-NEW001"]
            q2, _ = QuestionService.create_question(
                primary_competency=primary_competency,
                title="Second Question",
                prompt="Prompt",
                question_type="SINGLE_CHOICE",
                user=author_user,
            )
            assert q2.code == "QST-NUM-ARITH-NEW001"
            assert mock_code.call_count == 2

    def test_savepoint_rollback_preserves_outer_transaction_on_integrity_error(
        self, author_user, primary_competency
    ):
        """
        Critical regression test:
        Simulates concurrent insertion collision where candidate code exists in DB during save().
        Proves that IntegrityError escapes the nested atomic block, rolls back the savepoint cleanly,
        leaves the outer transaction usable, and succeeds on attempt 2 without TransactionManagementError.
        """
        existing_code = "QST-NUM-ARITH-COLLIDE"
        # Pre-create the colliding question in the database
        Question.objects.create(code=existing_code, created_by=author_user)

        with patch('apps.arena.services.question_service.generate_canonical_code') as mock_code:
            # Attempt 1 produces existing_code (which will fail uniqueness), Attempt 2 produces fresh code
            mock_code.side_effect = [existing_code, "QST-NUM-ARITH-FRESH99"]

            question, version = QuestionService.create_question(
                primary_competency=primary_competency,
                title="Concurrent Collision Recovery",
                prompt="Prompt",
                question_type="SINGLE_CHOICE",
                user=author_user,
            )
            assert question.code == "QST-NUM-ARITH-FRESH99"
            assert Question.objects.filter(code=existing_code).exists()
            assert Question.objects.filter(code="QST-NUM-ARITH-FRESH99").exists()

    def test_non_code_integrity_error_raises_validation_error_without_retry(
        self, author_user, primary_competency
    ):
        """
        Proves that if an IntegrityError occurs but candidate_code does NOT exist in DB,
        the service does not misclassify it as a code collision, does not retry, and raises QuestionValidationError.
        """
        with patch('apps.arena.models.Question.save') as mock_save:
            mock_save.side_effect = IntegrityError("FOREIGN KEY constraint failed")

            with pytest.raises(QuestionValidationError, match="database integrity violation"):
                QuestionService.create_question(
                    primary_competency=primary_competency,
                    title="Foreign Key Failure",
                    prompt="Prompt",
                    question_type="SINGLE_CHOICE",
                    user=author_user,
                )
            assert mock_save.call_count == 1  # No retries!

    def test_code_collision_exhaustion_raises_code_generation_error(
        self, author_user, primary_competency
    ):
        q1, _ = QuestionService.create_question(
            primary_competency=primary_competency,
            title="Existing Question",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )

        with patch('apps.arena.services.question_service.generate_canonical_code') as mock_code:
            mock_code.return_value = q1.code  # Persistent collision
            with pytest.raises(QuestionCodeGenerationError) as exc_info:
                QuestionService.create_question(
                    primary_competency=primary_competency,
                    title="Exhaustion Question",
                    prompt="Prompt",
                    question_type="SINGLE_CHOICE",
                    user=author_user,
                )
            assert exc_info.value.code == 'code_generation_failed'
            assert mock_code.call_count == 5


# -----------------------------------------------------------------------------
# Part 5: Question Retrieval (`get_question`)
# -----------------------------------------------------------------------------

class TestGetQuestion:
    """Verifies retrieval by UUID and code, and access controls."""

    def test_get_question_by_id_success(self, author_user, primary_competency):
        q, _ = QuestionService.create_question(
            primary_competency=primary_competency,
            title="UUID Lookup",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )
        retrieved = QuestionService.get_question(q.pk, user=author_user)
        assert retrieved == q

    def test_get_question_by_code_success(self, author_user, primary_competency):
        q, _ = QuestionService.create_question(
            primary_competency=primary_competency,
            title="Code Lookup",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )
        retrieved = QuestionService.get_question(q.code, user=author_user)
        assert retrieved == q

    def test_get_question_not_found(self, author_user):
        with pytest.raises(QuestionNotFoundError):
            QuestionService.get_question(uuid.uuid4(), user=author_user)

    def test_get_question_by_perm_holder(self, author_user, unprivileged_user, primary_competency):
        q, _ = QuestionService.create_question(
            primary_competency=primary_competency,
            title="Perm Lookup",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )
        content_type = ContentType.objects.get_for_model(Question)
        perm = Permission.objects.get(codename='view_question', content_type=content_type)
        unprivileged_user.user_permissions.add(perm)

        retrieved = QuestionService.get_question(q.pk, user=unprivileged_user)
        assert retrieved == q


# -----------------------------------------------------------------------------
# Part 6: Assessment Question Retrieval (`get_assessment_question`)
# -----------------------------------------------------------------------------

class TestGetAssessmentQuestion:
    """Verifies trusted internal assessment retrieval and active-version integrity invariants."""

    def test_get_assessment_question_happy_path(self, author_user, primary_competency):
        q, v = QuestionService.create_question(
            primary_competency=primary_competency,
            title="Live Assessment Question",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )
        publish_version(v)
        q.active_version = v
        q.save()

        active_v = QuestionService.get_assessment_question(q.pk)
        assert active_v == v
        assert active_v.status == 'PUBLISHED'

    def test_get_assessment_question_not_found(self, db):
        with pytest.raises(QuestionNotFoundError):
            QuestionService.get_assessment_question(uuid.uuid4())

    def test_get_assessment_question_deprecated_raises_error(self, author_user, primary_competency):
        q, v = QuestionService.create_question(
            primary_competency=primary_competency,
            title="Deprecated Assessment Question",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )
        publish_version(v)
        q.active_version = v
        q.is_deprecated = True
        q.save()

        with pytest.raises(QuestionDeprecatedError) as exc_info:
            QuestionService.get_assessment_question(q.pk)
        assert exc_info.value.code == 'question_deprecated'

    def test_get_assessment_question_no_active_version_raises_error(self, author_user, primary_competency):
        q, _ = QuestionService.create_question(
            primary_competency=primary_competency,
            title="Draft Only Question",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )
        with pytest.raises(QuestionNoActiveVersionError) as exc_info:
            QuestionService.get_assessment_question(q.pk)
        assert exc_info.value.code == 'question_no_active_version'

    def test_get_assessment_question_status_not_published_raises_error(self, author_user, primary_competency):
        q, v = QuestionService.create_question(
            primary_competency=primary_competency,
            title="Draft Active Version",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )
        # Directly update DB to bypass model clean check for testing defensive retrieval
        Question.objects.filter(pk=q.pk).update(active_version=v)

        with pytest.raises(ActiveVersionIntegrityError) as exc_info:
            QuestionService.get_assessment_question(q.pk)
        assert exc_info.value.code == 'active_version_integrity_error'
        assert exc_info.value.details['status'] == 'DRAFT'

    def test_get_assessment_question_parent_mismatch_raises_error(self, author_user, primary_competency):
        q1, v1 = QuestionService.create_question(
            primary_competency=primary_competency,
            title="Q1",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )
        q2, _ = QuestionService.create_question(
            primary_competency=primary_competency,
            title="Q2",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )
        publish_version(v1)
        # Corrupt active_version pointer to point to another question's version
        Question.objects.filter(pk=q2.pk).update(active_version=v1)

        with pytest.raises(ActiveVersionIntegrityError) as exc_info:
            QuestionService.get_assessment_question(q2.pk)
        assert exc_info.value.code == 'active_version_integrity_error'


# -----------------------------------------------------------------------------
# Part 7: Selectable Question Queries (`list_selectable_questions`)
# -----------------------------------------------------------------------------

class TestListSelectableQuestions:
    """Verifies QuerySet filtering and exclusion of confidential evaluation data."""

    def test_list_selectable_questions_filters_ineligible(self, author_user, primary_competency):
        # 1. Eligible question
        q_valid, v_valid = QuestionService.create_question(
            primary_competency=primary_competency,
            title="Valid Question",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )
        publish_version(v_valid)
        q_valid.active_version = v_valid
        q_valid.save()

        # 2. Deprecated question
        q_dep, v_dep = QuestionService.create_question(
            primary_competency=primary_competency,
            title="Deprecated Question",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )
        publish_version(v_dep)
        q_dep.active_version = v_dep
        q_dep.is_deprecated = True
        q_dep.save()

        # 3. Question with no active version (only DRAFT)
        QuestionService.create_question(
            primary_competency=primary_competency,
            title="Draft Only",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )

        selectable = list(QuestionService.list_selectable_questions())
        assert q_valid in selectable
        assert q_dep not in selectable
        assert len(selectable) == 1

    def test_list_selectable_questions_optional_filters(self, author_user, primary_competency, subdomain):
        comp2 = Competency.objects.create(
            subdomain=subdomain,
            code='NUM-ADV-01',
            name='Advanced Math',
            bloom_level='ANALYZE',
            is_active=True,
        )
        q1, v1 = QuestionService.create_question(
            primary_competency=primary_competency,
            title="Q1 Intermediate",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
            difficulty_tier="INTERMEDIATE",
        )
        publish_version(v1)
        q1.active_version = v1
        q1.save()

        q2, v2 = QuestionService.create_question(
            primary_competency=comp2,
            title="Q2 Advanced",
            prompt="Prompt",
            question_type="CODE_OUTPUT",
            user=author_user,
            difficulty_tier="ADVANCED",
        )
        publish_version(v2)
        q2.active_version = v2
        q2.save()

        assert QuestionService.list_selectable_questions(competency_id=comp2).count() == 1
        assert QuestionService.list_selectable_questions(difficulty_tier="ADVANCED").count() == 1
        assert QuestionService.list_selectable_questions(question_type="SINGLE_CHOICE").count() == 1


# -----------------------------------------------------------------------------
# Part 8: Question Deprecation (`deprecate_question`)
# -----------------------------------------------------------------------------

class TestQuestionDeprecation:
    """Verifies deprecation idempotency, strict mode, active_version clearing, and row locking."""

    def test_deprecate_question_idempotent_default(self, author_user, superuser, primary_competency):
        q, v = QuestionService.create_question(
            primary_competency=primary_competency,
            title="To Deprecate",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )
        publish_version(v)
        q.active_version = v
        q.save()

        # First deprecation
        deprecated_q = QuestionService.deprecate_question(q.pk, user=superuser)
        assert deprecated_q.is_deprecated is True
        assert deprecated_q.active_version is None

        # Second deprecation (idempotent default returns question without error)
        repeated_q = QuestionService.deprecate_question(q.pk, user=superuser, strict=False)
        assert repeated_q.is_deprecated is True
        assert repeated_q.active_version is None

    def test_deprecate_question_strict_mode_raises_error(self, author_user, superuser, primary_competency):
        q, _ = QuestionService.create_question(
            primary_competency=primary_competency,
            title="Strict Deprecate",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )
        QuestionService.deprecate_question(q.pk, user=superuser)

        with pytest.raises(QuestionAlreadyDeprecatedError) as exc_info:
            QuestionService.deprecate_question(q.pk, user=superuser, strict=True)
        assert exc_info.value.code == 'question_already_deprecated'

    def test_deprecate_question_with_explicit_perm_holder(self, author_user, unprivileged_user, primary_competency):
        q, _ = QuestionService.create_question(
            primary_competency=primary_competency,
            title="Perm Deprecate",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )
        content_type = ContentType.objects.get_for_model(Question)
        perm = Permission.objects.get(codename='change_question', content_type=content_type)
        unprivileged_user.user_permissions.add(perm)

        deprecated_q = QuestionService.deprecate_question(q.pk, user=unprivileged_user)
        assert deprecated_q.is_deprecated is True


# -----------------------------------------------------------------------------
# Part 9: Scope Discipline Verification
# -----------------------------------------------------------------------------

class TestScopeDiscipline:
    """Verifies that QuestionService does not declare version lifecycle or draft composition methods."""

    def test_question_service_has_no_lifecycle_methods(self):
        forbidden_methods = [
            'publish_question_version',
            'publish_version',
            'transition_version_status',
            'archive_question_version',
            'bump_version',
            'create_next_version',
            'set_primary_competency',
            'add_secondary_competency',
            'set_evaluation_data',
        ]
        for method_name in forbidden_methods:
            assert not hasattr(QuestionService, method_name), (
                f"QuestionService violates scope discipline by declaring '{method_name}'"
            )
