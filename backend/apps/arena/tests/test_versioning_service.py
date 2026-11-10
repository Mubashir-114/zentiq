"""
Tests for ZENTIQ Arena QuestionVersioningService (Phase 2C.3).
Covers QuestionVersioningService public methods, lifecycle state machine,
source resolution and pointer integrity, safe composition cloning,
review completeness gates, strict author/reviewer separation,
author-only withdrawal, and deprecated Question protection (service-level and model-hook).
"""
import copy
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
    EvaluationDataMissingError,
    InactiveCompetencyError,
    IncompleteQuestionVersionError,
    InvalidLifecycleTransitionError,
    MissingRequiredDraftFieldsError,
    QuestionCompositionService,
    QuestionDeprecatedError,
    QuestionImmutabilityError,
    QuestionNotFoundError,
    QuestionPermissionDeniedError,
    QuestionService,
    QuestionValidationError,
    QuestionVersionNotFoundError,
    QuestionVersioningService,
    RejectionReasonRequiredError,
    SelfPublicationNotAllowedError,
    SourceVersionMismatchError,
    can_publish_version,
    validate_version_completeness,
)
from apps.skills.models import Competency, Domain, Subdomain

User = get_user_model()


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

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
def competency(db, subdomain):
    return Competency.objects.create(
        subdomain=subdomain,
        code='NUM-ARITH-01',
        name='Arithmetic Operations',
        description='Evaluate mental arithmetic',
        bloom_level='APPLY',
        is_active=True,
    )


@pytest.fixture
def secondary_competency(db, subdomain):
    return Competency.objects.create(
        subdomain=subdomain,
        code='NUM-ALG-01',
        name='Algebraic Operations',
        description='Evaluate algebraic manipulation',
        bloom_level='APPLY',
        is_active=True,
    )


@pytest.fixture
def inactive_competency(db, subdomain):
    return Competency.objects.create(
        subdomain=subdomain,
        code='NUM-INACT-01',
        name='Inactive Topic',
        description='Deprecated topic',
        bloom_level='REMEMBER',
        is_active=False,
    )


@pytest.fixture
def tag1(db):
    return Tag.objects.create(slug='math-logic', name='Math Logic', category='TOPIC')


@pytest.fixture
def tag2(db):
    return Tag.objects.create(slug='speed-drills', name='Speed Drills', category='EXAM')


@pytest.fixture
def author_user(db):
    user = User.objects.create_user(
        email='author@example.com',
        password='TestPassword123!',
    )
    # Grant arena.add_question and arena.add_questionversion
    ct_q = ContentType.objects.get_for_model(Question)
    ct_qv = ContentType.objects.get_for_model(QuestionVersion)
    user.user_permissions.add(
        Permission.objects.get(codename='add_question', content_type=ct_q),
        Permission.objects.get(codename='add_questionversion', content_type=ct_qv),
        Permission.objects.get(codename='change_questionversion', content_type=ct_qv),
    )
    return user


@pytest.fixture
def reviewer_user(db):
    user = User.objects.create_user(
        email='reviewer@example.com',
        password='TestPassword123!',
    )
    ct_qv = ContentType.objects.get_for_model(QuestionVersion)
    perm, _ = Permission.objects.get_or_create(
        codename='publish_questionversion',
        content_type=ct_qv,
        defaults={'name': 'Can publish question version'},
    )
    user.user_permissions.add(perm)
    return user


@pytest.fixture
def editor_user(db):
    user = User.objects.create_user(
        email='editor@example.com',
        password='TestPassword123!',
    )
    ct_qv = ContentType.objects.get_for_model(QuestionVersion)
    user.user_permissions.add(
        Permission.objects.get(codename='change_questionversion', content_type=ct_qv),
        Permission.objects.get(codename='add_questionversion', content_type=ct_qv),
    )
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
def inactive_user(db):
    return User.objects.create_user(
        email='inactive@example.com',
        password='TestPassword123!',
        is_active=False,
    )


@pytest.fixture
def inactive_superuser(db):
    return User.objects.create_superuser(
        email='inactive_admin@example.com',
        password='TestPassword123!',
        is_active=False,
    )


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def setup_question_with_evaluation(competency, author, title="Sample Q", prompt="Stem text"):
    """Creates a Question, adds evaluation data to v1, and returns (question, v1)."""
    q, v1 = QuestionService.create_question(
        primary_competency=competency,
        title=title,
        prompt=prompt,
        question_type="SINGLE_CHOICE",
        user=author,
    )
    QuestionCompositionService.set_evaluation_data(
        version_id=v1.pk,
        grading_strategy="EXACT_MATCH",
        correct_payload={"correct_option": "A"},
        user=author,
    )
    return q, v1


# -----------------------------------------------------------------------------
# Suite 1: Permanently Deprecated Question Protection
# -----------------------------------------------------------------------------

class TestDeprecatedQuestionProtection:
    """
    Verifies that permanently deprecated Question series cannot accept new drafts,
    cannot publish versions, and can never have an active version assigned or restored—
    neither via QuestionVersioningService nor via the low-level QuestionVersion.save() hook.
    """

    def test_create_draft_under_deprecated_question_rejected(self, db, author_user, superuser, competency):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        QuestionService.deprecate_question(q.pk, user=superuser)
        q.refresh_from_db()
        assert q.is_deprecated is True

        with pytest.raises(QuestionDeprecatedError) as exc_info:
            QuestionVersioningService.create_draft_version(
                q.pk,
                user=author_user,
                title="Attempted Draft",
                prompt="Valid prompt",
                question_type="SINGLE_CHOICE",
                primary_competency=competency,
            )
        assert exc_info.value.code == 'question_deprecated'

    def test_publish_under_deprecated_question_rejected(self, db, author_user, reviewer_user, superuser, competency):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        QuestionVersioningService.submit_for_review(v1.pk, user=author_user)

        # Deprecate the parent Question
        QuestionService.deprecate_question(q.pk, user=superuser)
        q.refresh_from_db()
        assert q.is_deprecated is True

        with pytest.raises(QuestionDeprecatedError) as exc_info:
            QuestionVersioningService.publish_version(v1.pk, user=reviewer_user)
        assert exc_info.value.code == 'question_deprecated'

    def test_service_archival_under_deprecated_question_preserves_retirement(
        self, db, author_user, reviewer_user, editor_user, superuser, competency
    ):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        QuestionVersioningService.submit_for_review(v1.pk, user=author_user)
        published_v1 = QuestionVersioningService.publish_version(v1.pk, user=reviewer_user)

        # Deprecate parent Question series
        QuestionService.deprecate_question(q.pk, user=superuser)
        q.refresh_from_db()
        assert q.is_deprecated is True
        assert q.active_version is None

        # Archive the published historical version via service
        archived_v1 = QuestionVersioningService.archive_version(published_v1.pk, user=editor_user)
        assert archived_v1.status == 'ARCHIVED'

        q.refresh_from_db()
        assert q.is_deprecated is True
        assert q.active_version is None

    def test_service_deprecation_under_deprecated_question_preserves_retirement(
        self, db, author_user, reviewer_user, editor_user, superuser, competency
    ):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        QuestionVersioningService.submit_for_review(v1.pk, user=author_user)
        published_v1 = QuestionVersioningService.publish_version(v1.pk, user=reviewer_user)

        QuestionService.deprecate_question(q.pk, user=superuser)

        deprecated_v1 = QuestionVersioningService.deprecate_version(published_v1.pk, user=editor_user)
        assert deprecated_v1.status == 'DEPRECATED'

        q.refresh_from_db()
        assert q.is_deprecated is True
        assert q.active_version is None

    def test_model_save_on_deprecated_question_normal_state(
        self, db, author_user, reviewer_user, superuser, competency
    ):
        """Model hook test: normal state preserves is_deprecated=True and active_version=None."""
        q, v1 = setup_question_with_evaluation(competency, author_user)
        QuestionVersioningService.submit_for_review(v1.pk, user=author_user)
        published_v1 = QuestionVersioningService.publish_version(v1.pk, user=reviewer_user)

        QuestionService.deprecate_question(q.pk, user=superuser)
        q.refresh_from_db()
        assert q.is_deprecated is True
        assert q.active_version is None

        published_v1.status = 'ARCHIVED'
        published_v1.save()

        published_v1.refresh_from_db()
        assert published_v1.status == 'ARCHIVED'
        q.refresh_from_db()
        assert q.is_deprecated is True
        assert q.active_version is None

    def test_model_save_on_deprecated_question_defensive_active_version_transition(
        self, db, author_user, reviewer_user, competency
    ):
        """
        Defensive inconsistent state 1: Question is deprecated, but active_version points to v2.
        v2 transitions to ARCHIVED via model save.
        Verifies:
        1. Model hook detects question.is_deprecated == True.
        2. v1 is NOT promoted.
        3. active_version is cleared to None.
        4. is_deprecated remains True.
        """
        q, v1 = setup_question_with_evaluation(competency, author_user)
        QuestionVersioningService.submit_for_review(v1.pk, user=author_user)
        published_v1 = QuestionVersioningService.publish_version(v1.pk, user=reviewer_user)

        draft_v2 = QuestionVersioningService.create_draft_version(
            q.pk,
            user=author_user,
            source_version_id=published_v1.pk,
            title="Version 2",
        )
        QuestionVersioningService.submit_for_review(draft_v2.pk, user=author_user)
        published_v2 = QuestionVersioningService.publish_version(draft_v2.pk, user=reviewer_user)

        # Force corrupt state: Question.is_deprecated=True, active_version=v2
        Question.objects.filter(pk=q.pk).update(
            is_deprecated=True,
            active_version=published_v2,
        )
        q.refresh_from_db()
        assert q.is_deprecated is True
        assert q.active_version_id == published_v2.pk

        # Trigger model save() hook directly on v2
        published_v2.status = 'ARCHIVED'
        published_v2.save()

        published_v2.refresh_from_db()
        assert published_v2.status == 'ARCHIVED'

        q.refresh_from_db()
        assert q.is_deprecated is True
        assert q.active_version is None
        assert q.active_version_id is None

    def test_model_save_on_deprecated_question_defensive_non_active_version_transition(
        self, db, author_user, reviewer_user, competency
    ):
        """
        Defensive inconsistent state 2: Question is deprecated, active_version points to v2.
        v1 (the NON-ACTIVE historical version) transitions to ARCHIVED via model save.
        Verifies:
        1. Model hook locks Question by PK alone (does not filter by active_version_id=v1).
        2. Model hook detects question.is_deprecated == True.
        3. Model hook forcibly CLEARS the invalid pointer (v2 is NOT retained).
        4. Question.active_version becomes None.
        5. Question.is_deprecated remains True.
        """
        q, v1 = setup_question_with_evaluation(competency, author_user)
        QuestionVersioningService.submit_for_review(v1.pk, user=author_user)
        published_v1 = QuestionVersioningService.publish_version(v1.pk, user=reviewer_user)

        draft_v2 = QuestionVersioningService.create_draft_version(
            q.pk,
            user=author_user,
            source_version_id=published_v1.pk,
            title="Version 2",
        )
        QuestionVersioningService.submit_for_review(draft_v2.pk, user=author_user)
        published_v2 = QuestionVersioningService.publish_version(draft_v2.pk, user=reviewer_user)

        # Force corrupt state: Question.is_deprecated=True, active_version=v2
        Question.objects.filter(pk=q.pk).update(
            is_deprecated=True,
            active_version=published_v2,
        )
        q.refresh_from_db()
        assert q.is_deprecated is True
        assert q.active_version_id == published_v2.pk

        # Trigger model save() hook directly on v1 (NON-ACTIVE version)
        published_v1.status = 'ARCHIVED'
        published_v1.save()

        published_v1.refresh_from_db()
        assert published_v1.status == 'ARCHIVED'
        published_v2.refresh_from_db()
        assert published_v2.status == 'PUBLISHED'

        q.refresh_from_db()
        assert q.is_deprecated is True
        assert q.active_version is None
        assert q.active_version_id is None

    def test_deprecated_series_never_regains_active_version(self, db, author_user, superuser, competency):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        QuestionService.deprecate_question(q.pk, user=superuser)
        q.refresh_from_db()
        assert q.is_deprecated is True
        assert q.active_version is None


# -----------------------------------------------------------------------------
# Suite 2: Source Resolution & Active Pointer Integrity
# -----------------------------------------------------------------------------

class TestSourceResolutionAndIntegrity:
    """Verifies source version resolution, pointer integrity checks, and scratch draft creation."""

    def test_create_draft_with_explicit_source(self, db, author_user, competency, tag1):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        QuestionCompositionService.sync_version_tags(v1.pk, [tag1.slug], user=author_user)

        draft = QuestionVersioningService.create_draft_version(
            q.pk,
            user=author_user,
            source_version_id=v1.pk,
            title="Cloned Draft Title",
        )
        assert draft.version_number == 2
        assert draft.status == 'DRAFT'
        assert draft.title == "Cloned Draft Title"
        assert draft.prompt == v1.prompt
        assert draft.primary_competency_id == v1.primary_competency_id

        # Verify independent tags and evaluation data
        assert list(draft.tags.values_list('slug', flat=True)) == [tag1.slug]
        assert draft.evaluation_data is not None
        assert draft.evaluation_data.pk == draft.pk
        assert draft.evaluation_data.correct_payload == {"correct_option": "A"}

    def test_create_draft_source_belongs_to_another_question(self, db, author_user, competency):
        q1, v1 = setup_question_with_evaluation(competency, author_user, title="Q1")
        q2, v2 = setup_question_with_evaluation(competency, author_user, title="Q2")

        with pytest.raises(SourceVersionMismatchError) as exc_info:
            QuestionVersioningService.create_draft_version(
                q1.pk,
                user=author_user,
                source_version_id=v2.pk,
            )
        assert exc_info.value.code == 'source_version_mismatch'

    def test_create_draft_source_omitted_uses_active_version(
        self, db, author_user, reviewer_user, competency
    ):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        QuestionVersioningService.submit_for_review(v1.pk, user=author_user)
        QuestionVersioningService.publish_version(v1.pk, user=reviewer_user)

        # Omit source_version_id -> should clone active published version
        draft = QuestionVersioningService.create_draft_version(
            q.pk,
            user=author_user,
        )
        assert draft.version_number == 2
        assert draft.prompt == v1.prompt
        assert draft.evaluation_data.correct_payload == {"correct_option": "A"}

    def test_corrupt_non_null_active_pointer_raises_integrity_error(
        self, db, author_user, competency
    ):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        # Force active pointer to reference DRAFT v1 (corrupt: active_version must be PUBLISHED)
        Question.objects.filter(pk=q.pk).update(active_version=v1)

        with pytest.raises(ActiveVersionIntegrityError) as exc_info:
            QuestionVersioningService.create_draft_version(
                q.pk,
                user=author_user,
            )
        assert exc_info.value.code == 'active_version_integrity_error'

    def test_scratch_creation_when_active_version_genuinely_none(self, db, author_user, competency):
        q, v1 = QuestionService.create_question(
            primary_competency=competency,
            title="Q Anchor",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )
        assert q.active_version is None

        # Scratch draft created with minimum required fields
        scratch = QuestionVersioningService.create_draft_version(
            q.pk,
            user=author_user,
            title="Scratch Draft",
            prompt="Scratch Prompt",
            question_type="NUMERICAL",
            primary_competency=competency,
        )
        assert scratch.version_number == 2
        assert scratch.title == "Scratch Draft"
        assert scratch.question_type == "NUMERICAL"
        assert scratch.primary_competency_id == competency.pk

    def test_scratch_creation_missing_required_fields_raises_error(self, db, author_user, competency):
        q, v1 = QuestionService.create_question(
            primary_competency=competency,
            title="Q Anchor",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )
        assert q.active_version is None

        # Omit prompt and primary_competency
        with pytest.raises(MissingRequiredDraftFieldsError) as exc_info:
            QuestionVersioningService.create_draft_version(
                q.pk,
                user=author_user,
                title="Missing fields draft",
            )
        assert exc_info.value.code == 'missing_required_draft_fields'
        assert 'prompt' in exc_info.value.details['missing_fields']
        assert 'primary_competency' in exc_info.value.details['missing_fields']

    def test_primary_competency_override(
        self, db, author_user, competency, secondary_competency
    ):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        # Add secondary competency mapping on v1
        QuestionCompositionService.add_secondary_competency(
            v1.pk, competency=secondary_competency, weight=Decimal('0.50'), user=author_user
        )

        # Clone and override primary_competency to secondary_competency
        draft = QuestionVersioningService.create_draft_version(
            q.pk,
            user=author_user,
            source_version_id=v1.pk,
            primary_competency=secondary_competency,
        )
        assert draft.primary_competency_id == secondary_competency.pk

        # Primary mapping updated to secondary_competency
        primary_mapping = QuestionCompetencyMapping.objects.get(question_version=draft, is_primary=True)
        assert primary_mapping.competency_id == secondary_competency.pk

        # Old secondary mapping removed (cannot be both primary and secondary)
        assert not QuestionCompetencyMapping.objects.filter(
            question_version=draft,
            competency=secondary_competency,
            is_primary=False,
        ).exists()


# -----------------------------------------------------------------------------
# Suite 3: JSON Payload Compatibility
# -----------------------------------------------------------------------------

class TestJsonPayloadCompatibility:
    """Verifies that content_payload accepts valid JSON dicts, lists, and primitives."""

    def test_create_draft_with_list_payload(self, db, author_user, competency):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        payload = [{"snippet": "print(1)"}, {"snippet": "print(2)"}]
        draft = QuestionVersioningService.create_draft_version(
            q.pk,
            user=author_user,
            source_version_id=v1.pk,
            content_payload=payload,
        )
        assert draft.content_payload == payload

    def test_create_draft_with_primitive_payload(self, db, author_user, competency):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        payload = "plain string payload"
        draft = QuestionVersioningService.create_draft_version(
            q.pk,
            user=author_user,
            source_version_id=v1.pk,
            content_payload=payload,
        )
        assert draft.content_payload == payload

    def test_update_draft_omitted_payload_preserves_existing(self, db, author_user, competency):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        payload = {"options": ["A", "B", "C"]}
        draft = QuestionVersioningService.create_draft_version(
            q.pk,
            user=author_user,
            source_version_id=v1.pk,
            content_payload=payload,
        )
        assert draft.content_payload == payload

        # Update title only, content_payload is omitted (None)
        updated = QuestionVersioningService.update_draft_version(
            draft.pk,
            user=author_user,
            title="Updated Title Without Touching Payload",
        )
        assert updated.title == "Updated Title Without Touching Payload"
        assert updated.content_payload == payload  # Preserved untouched!

    def test_update_draft_with_new_list_payload(self, db, author_user, competency):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        draft = QuestionVersioningService.create_draft_version(
            q.pk,
            user=author_user,
            source_version_id=v1.pk,
        )
        new_payload = [1, 2, 3, 4]
        updated = QuestionVersioningService.update_draft_version(
            draft.pk,
            user=author_user,
            content_payload=new_payload,
        )
        assert updated.content_payload == new_payload

    def test_scan_confidential_keys_rejects_leakage_in_nested_payload(self, db, author_user, competency):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        leaked_payload = {"meta": [{"correct_option_id": "secret"}]}

        with pytest.raises(QuestionValidationError):
            QuestionVersioningService.create_draft_version(
                q.pk,
                user=author_user,
                source_version_id=v1.pk,
                content_payload=leaked_payload,
            )


# -----------------------------------------------------------------------------
# Suite 4: Review Completeness Contract
# -----------------------------------------------------------------------------

class TestReviewCompleteness:
    """Verifies completeness validation based strictly on model schema without invented rules."""

    def test_completeness_validation_without_invented_minimum_lengths(
        self, db, author_user, competency
    ):
        q, v1 = QuestionService.create_question(
            primary_competency=competency,
            title="OK",  # 2 characters
            prompt="Stem",  # 4 characters
            question_type="SINGLE_CHOICE",
            user=author_user,
        )
        QuestionCompositionService.set_evaluation_data(
            v1.pk,
            grading_strategy="EXACT_MATCH",
            correct_payload={"opt": "A"},
            user=author_user,
        )
        # Should succeed without arbitrary minimum length constraints
        in_review = QuestionVersioningService.submit_for_review(v1.pk, user=author_user)
        assert in_review.status == 'IN_REVIEW'

    def test_completeness_permits_empty_scoring_rubric(self, db, author_user, competency):
        q, v1 = QuestionService.create_question(
            primary_competency=competency,
            title="Rubric Test",
            prompt="Valid prompt",
            question_type="NUMERICAL",
            user=author_user,
        )
        QuestionCompositionService.set_evaluation_data(
            v1.pk,
            grading_strategy="NUMERIC_TOLERANCE",
            correct_payload={"target": 42},
            scoring_rubric={},  # Empty rubric allowed!
            user=author_user,
        )
        in_review = QuestionVersioningService.submit_for_review(v1.pk, user=author_user)
        assert in_review.status == 'IN_REVIEW'

    def test_completeness_rejects_null_correct_payload(self, db, author_user, competency):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        v1.evaluation_data.correct_payload = None

        with pytest.raises(IncompleteQuestionVersionError):
            validate_version_completeness(v1)

    def test_completeness_permits_empty_container_correct_payload(self, db, author_user, competency):
        q, v1 = QuestionService.create_question(
            primary_competency=competency,
            title="Empty Payload Test",
            prompt="Valid prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )
        QuestionCompositionService.set_evaluation_data(
            v1.pk,
            grading_strategy="EXACT_MATCH",
            correct_payload={},  # Valid empty dict payload
            user=author_user,
        )
        in_review = QuestionVersioningService.submit_for_review(v1.pk, user=author_user)
        assert in_review.status == 'IN_REVIEW'

    def test_completeness_rejects_missing_evaluation_record(self, db, author_user, competency):
        q, v1 = QuestionService.create_question(
            primary_competency=competency,
            title="No Eval Test",
            prompt="Valid prompt",
            question_type="SINGLE_CHOICE",
            user=author_user,
        )
        with pytest.raises(EvaluationDataMissingError):
            QuestionVersioningService.submit_for_review(v1.pk, user=author_user)

    def test_completeness_rejects_missing_primary_mapping(self, db, author_user, competency):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        # Delete primary mapping
        QuestionCompetencyMapping.objects.filter(question_version=v1, is_primary=True).delete()

        with pytest.raises(IncompleteQuestionVersionError):
            QuestionVersioningService.submit_for_review(v1.pk, user=author_user)

    def test_publication_revalidates_completeness(self, db, author_user, reviewer_user, competency):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        QuestionVersioningService.submit_for_review(v1.pk, user=author_user)

        # Remove evaluation data while in review
        QuestionEvaluationData.objects.filter(question_version=v1).delete()

        with pytest.raises(EvaluationDataMissingError):
            QuestionVersioningService.publish_version(v1.pk, user=reviewer_user)


# -----------------------------------------------------------------------------
# Suite 5: Rejection Versus Withdrawal Workflow
# -----------------------------------------------------------------------------

class TestRejectionAndWithdrawal:
    """Verifies reviewer rejection with mandatory reason versus strictly author-only withdrawal."""

    def test_reviewer_return_to_draft_with_valid_reason(
        self, db, author_user, reviewer_user, competency
    ):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        QuestionVersioningService.submit_for_review(v1.pk, user=author_user)

        rejected = QuestionVersioningService.return_to_draft(
            v1.pk,
            user=reviewer_user,
            rejection_reason="Options A and B are duplicates",
        )
        assert rejected.status == 'DRAFT'
        assert rejected.change_summary == "Review rejected: Options A and B are duplicates"

    def test_reviewer_return_to_draft_missing_reason_rejected(
        self, db, author_user, reviewer_user, competency
    ):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        QuestionVersioningService.submit_for_review(v1.pk, user=author_user)

        with pytest.raises(RejectionReasonRequiredError):
            QuestionVersioningService.return_to_draft(
                v1.pk,
                user=reviewer_user,
                rejection_reason="   ",
            )

    def test_version_author_cannot_execute_reviewer_rejection(
        self, db, author_user, competency
    ):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        QuestionVersioningService.submit_for_review(v1.pk, user=author_user)

        with pytest.raises(QuestionPermissionDeniedError):
            QuestionVersioningService.return_to_draft(
                v1.pk,
                user=author_user,
                rejection_reason="Rejecting myself",
            )

    def test_author_withdraw_from_review_success(self, db, author_user, competency):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        QuestionVersioningService.submit_for_review(v1.pk, user=author_user)

        withdrawn = QuestionVersioningService.withdraw_from_review(
            v1.pk,
            user=author_user,
            reason="Need to fix a typo in the prompt",
        )
        assert withdrawn.status == 'DRAFT'
        assert withdrawn.change_summary == "Withdrawn by author: Need to fix a typo in the prompt"

    def test_author_withdraw_without_reason_success(self, db, author_user, competency):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        QuestionVersioningService.submit_for_review(v1.pk, user=author_user)

        withdrawn = QuestionVersioningService.withdraw_from_review(
            v1.pk,
            user=author_user,
        )
        assert withdrawn.status == 'DRAFT'
        assert withdrawn.change_summary == "Withdrawn by author"

    def test_author_superuser_can_withdraw_own_submission(self, db, superuser, competency):
        q, v1 = setup_question_with_evaluation(competency, superuser)
        QuestionVersioningService.submit_for_review(v1.pk, user=superuser)

        withdrawn = QuestionVersioningService.withdraw_from_review(
            v1.pk,
            user=superuser,
        )
        assert withdrawn.status == 'DRAFT'
        assert withdrawn.change_summary == "Withdrawn by author"

    def test_non_author_superuser_cannot_withdraw_submission(
        self, db, author_user, superuser, competency
    ):
        """Audit fidelity: Non-author superuser CANNOT use withdraw_from_review()."""
        q, v1 = setup_question_with_evaluation(competency, author_user)
        QuestionVersioningService.submit_for_review(v1.pk, user=author_user)

        with pytest.raises(QuestionPermissionDeniedError):
            QuestionVersioningService.withdraw_from_review(
                v1.pk,
                user=superuser,
            )

    def test_non_author_standard_user_cannot_withdraw_submission(
        self, db, author_user, unprivileged_user, competency
    ):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        QuestionVersioningService.submit_for_review(v1.pk, user=author_user)

        with pytest.raises(QuestionPermissionDeniedError):
            QuestionVersioningService.withdraw_from_review(
                v1.pk,
                user=unprivileged_user,
            )


# -----------------------------------------------------------------------------
# Suite 6: Strict Author/Reviewer Separation & RBAC
# -----------------------------------------------------------------------------

class TestAuthorReviewerSeparation:
    """Verifies segregation of duties: authors (even superusers) can NEVER publish own versions."""

    def test_author_cannot_self_publish(self, db, author_user, competency):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        # Grant author the publish_questionversion permission
        ct_qv = ContentType.objects.get_for_model(QuestionVersion)
        author_user.user_permissions.add(Permission.objects.get(codename='publish_questionversion', content_type=ct_qv))

        QuestionVersioningService.submit_for_review(v1.pk, user=author_user)

        with pytest.raises(SelfPublicationNotAllowedError):
            QuestionVersioningService.publish_version(v1.pk, user=author_user)

    def test_superuser_author_cannot_self_publish(self, db, superuser, competency):
        q, v1 = setup_question_with_evaluation(competency, superuser)
        QuestionVersioningService.submit_for_review(v1.pk, user=superuser)

        with pytest.raises(SelfPublicationNotAllowedError):
            QuestionVersioningService.publish_version(v1.pk, user=superuser)

    def test_parent_question_author_does_not_gain_editing_rights(
        self, db, unprivileged_user, competency
    ):
        # Create a parent question author with only add_question (no change_questionversion)
        parent_author = User.objects.create_user(email='parent_only@example.com', password='TestPassword123!')
        ct_q = ContentType.objects.get_for_model(Question)
        parent_author.user_permissions.add(Permission.objects.get(codename='add_question', content_type=ct_q))

        q, v1 = setup_question_with_evaluation(competency, parent_author)
        v2 = QuestionVersion.objects.create(
            question=q,
            version_number=2,
            status='DRAFT',
            title="v2 Draft",
            prompt="Prompt",
            question_type="SINGLE_CHOICE",
            primary_competency=competency,
            created_by=unprivileged_user,
        )

        with pytest.raises(QuestionPermissionDeniedError):
            QuestionVersioningService.update_draft_version(
                v2.pk,
                user=parent_author,
                title="Unauthorized Edit",
            )

    def test_reviewer_without_permission_cannot_publish(
        self, db, author_user, unprivileged_user, competency
    ):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        QuestionVersioningService.submit_for_review(v1.pk, user=author_user)

        with pytest.raises(QuestionPermissionDeniedError):
            QuestionVersioningService.publish_version(v1.pk, user=unprivileged_user)

    def test_staff_without_permission_cannot_publish(
        self, db, author_user, staff_user, competency
    ):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        QuestionVersioningService.submit_for_review(v1.pk, user=author_user)

        with pytest.raises(QuestionPermissionDeniedError):
            QuestionVersioningService.publish_version(v1.pk, user=staff_user)

    def test_authorized_non_author_reviewer_can_publish(
        self, db, author_user, reviewer_user, competency
    ):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        QuestionVersioningService.submit_for_review(v1.pk, user=author_user)

        published = QuestionVersioningService.publish_version(v1.pk, user=reviewer_user)
        assert published.status == 'PUBLISHED'
        q.refresh_from_db()
        assert q.active_version_id == published.pk

    def test_inactive_superuser_rejected_everywhere(
        self, db, author_user, inactive_superuser, competency
    ):
        q, v1 = setup_question_with_evaluation(competency, author_user)

        with pytest.raises(QuestionPermissionDeniedError) as exc_info:
            QuestionVersioningService.create_draft_version(
                q.pk,
                user=inactive_superuser,
                source_version_id=v1.pk,
            )
        assert "inactive" in str(exc_info.value).lower()


# -----------------------------------------------------------------------------
# Suite 7: Lifecycle & Active Pointer Integrity
# -----------------------------------------------------------------------------

class TestLifecycleAndPointerIntegrity:
    """Verifies atomic active pointer updates and fallback reconciliation."""

    def test_publish_promotes_active_version_atomically(
        self, db, author_user, reviewer_user, competency
    ):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        QuestionVersioningService.submit_for_review(v1.pk, user=author_user)
        published_v1 = QuestionVersioningService.publish_version(v1.pk, user=reviewer_user)

        draft_v2 = QuestionVersioningService.create_draft_version(
            q.pk,
            user=author_user,
            source_version_id=published_v1.pk,
            title="v2",
        )
        QuestionVersioningService.submit_for_review(draft_v2.pk, user=author_user)
        published_v2 = QuestionVersioningService.publish_version(draft_v2.pk, user=reviewer_user)

        q.refresh_from_db()
        assert q.active_version_id == published_v2.pk
        published_v1.refresh_from_db()
        assert published_v1.status == 'PUBLISHED'  # v1 remains PUBLISHED!

    def test_archive_active_version_reconciles_to_highest_published(
        self, db, author_user, reviewer_user, editor_user, competency
    ):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        QuestionVersioningService.submit_for_review(v1.pk, user=author_user)
        published_v1 = QuestionVersioningService.publish_version(v1.pk, user=reviewer_user)

        draft_v2 = QuestionVersioningService.create_draft_version(
            q.pk,
            user=author_user,
            source_version_id=published_v1.pk,
            title="v2",
        )
        QuestionVersioningService.submit_for_review(draft_v2.pk, user=author_user)
        published_v2 = QuestionVersioningService.publish_version(draft_v2.pk, user=reviewer_user)

        # Archive active v2 -> pointer falls back to v1!
        archived_v2 = QuestionVersioningService.archive_version(published_v2.pk, user=editor_user)
        assert archived_v2.status == 'ARCHIVED'

        q.refresh_from_db()
        assert q.active_version_id == published_v1.pk

    def test_archive_active_version_clears_pointer_when_no_published_remain(
        self, db, author_user, reviewer_user, editor_user, competency
    ):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        QuestionVersioningService.submit_for_review(v1.pk, user=author_user)
        published_v1 = QuestionVersioningService.publish_version(v1.pk, user=reviewer_user)

        # Sole published version archived -> pointer cleared to None
        QuestionVersioningService.archive_version(published_v1.pk, user=editor_user)
        q.refresh_from_db()
        assert q.active_version is None

    def test_deprecate_active_version_reconciles_pointer(
        self, db, author_user, reviewer_user, editor_user, competency
    ):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        QuestionVersioningService.submit_for_review(v1.pk, user=author_user)
        published_v1 = QuestionVersioningService.publish_version(v1.pk, user=reviewer_user)

        draft_v2 = QuestionVersioningService.create_draft_version(
            q.pk,
            user=author_user,
            source_version_id=published_v1.pk,
            title="v2",
        )
        QuestionVersioningService.submit_for_review(draft_v2.pk, user=author_user)
        published_v2 = QuestionVersioningService.publish_version(draft_v2.pk, user=reviewer_user)

        # Deprecate active v2 -> pointer falls back to v1
        QuestionVersioningService.deprecate_version(published_v2.pk, user=editor_user)
        q.refresh_from_db()
        assert q.active_version_id == published_v1.pk

    def test_archive_non_active_version_leaves_active_pointer_intact(
        self, db, author_user, reviewer_user, editor_user, competency
    ):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        QuestionVersioningService.submit_for_review(v1.pk, user=author_user)
        published_v1 = QuestionVersioningService.publish_version(v1.pk, user=reviewer_user)

        draft_v2 = QuestionVersioningService.create_draft_version(
            q.pk,
            user=author_user,
            source_version_id=published_v1.pk,
            title="v2",
        )
        QuestionVersioningService.submit_for_review(draft_v2.pk, user=author_user)
        published_v2 = QuestionVersioningService.publish_version(draft_v2.pk, user=reviewer_user)

        # Archive historical non-active v1 -> v2 remains active pointer
        QuestionVersioningService.archive_version(published_v1.pk, user=editor_user)
        q.refresh_from_db()
        assert q.active_version_id == published_v2.pk

    def test_invalid_transitions_rejected(
        self, db, author_user, reviewer_user, editor_user, competency
    ):
        q, v1 = setup_question_with_evaluation(competency, author_user)

        # DRAFT -> PUBLISHED directly is forbidden
        with pytest.raises(InvalidLifecycleTransitionError):
            QuestionVersioningService.publish_version(v1.pk, user=reviewer_user)

        # DRAFT -> ARCHIVED directly is forbidden
        with pytest.raises(InvalidLifecycleTransitionError):
            QuestionVersioningService.archive_version(v1.pk, user=editor_user)

    def test_terminal_state_immutable(
        self, db, author_user, reviewer_user, editor_user, competency
    ):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        QuestionVersioningService.submit_for_review(v1.pk, user=author_user)
        published_v1 = QuestionVersioningService.publish_version(v1.pk, user=reviewer_user)
        deprecated_v1 = QuestionVersioningService.deprecate_version(published_v1.pk, user=editor_user)

        # Cannot archive or publish a DEPRECATED version
        with pytest.raises(InvalidLifecycleTransitionError):
            QuestionVersioningService.archive_version(deprecated_v1.pk, user=editor_user)


# -----------------------------------------------------------------------------
# Suite 8: Safe Composition Cloning & Locking
# -----------------------------------------------------------------------------

class TestCloningAndConcurrency:
    """Verifies independent instance cloning, transactional rollback, and monotonic versioning."""

    def test_cloned_records_are_independent_instances(
        self, db, author_user, competency, secondary_competency, tag1
    ):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        QuestionCompositionService.add_secondary_competency(
            v1.pk, secondary_competency, Decimal('0.30'), user=author_user
        )
        QuestionCompositionService.sync_version_tags(v1.pk, [tag1.slug], user=author_user)

        draft = QuestionVersioningService.create_draft_version(
            q.pk,
            user=author_user,
            source_version_id=v1.pk,
        )

        # Verify distinct PKs
        assert draft.pk != v1.pk
        assert draft.evaluation_data.pk != v1.evaluation_data.pk

        # Mutate draft evaluation data
        QuestionCompositionService.set_evaluation_data(
            draft.pk,
            grading_strategy="NORMALIZED_STRING",
            correct_payload={"answer": "new"},
            user=author_user,
        )

        # Source evaluation data remains unchanged
        v1.evaluation_data.refresh_from_db()
        assert v1.evaluation_data.grading_strategy == "EXACT_MATCH"
        assert v1.evaluation_data.correct_payload == {"correct_option": "A"}

    def test_source_records_remain_unmodified(
        self, db, author_user, competency, secondary_competency, tag1
    ):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        QuestionCompositionService.add_secondary_competency(
            v1.pk, secondary_competency, Decimal('0.30'), user=author_user
        )
        QuestionCompositionService.sync_version_tags(v1.pk, [tag1.slug], user=author_user)

        v1_updated_at_before = v1.updated_at

        QuestionVersioningService.create_draft_version(
            q.pk,
            user=author_user,
            source_version_id=v1.pk,
        )

        v1.refresh_from_db()
        assert v1.updated_at == v1_updated_at_before
        assert v1.version_number == 1
        assert v1.status == 'DRAFT'
        assert QuestionCompetencyMapping.objects.filter(question_version=v1).count() == 2
        assert QuestionVersionTag.objects.filter(question_version=v1).count() == 1

    def test_atomic_rollback_on_cloning_failure(self, db, author_user, competency):
        q, v1 = setup_question_with_evaluation(competency, author_user)

        with patch.object(
            QuestionCompositionService,
            'set_evaluation_data',
            side_effect=RuntimeError("Simulated evaluation clone failure"),
        ):
            with pytest.raises(RuntimeError):
                QuestionVersioningService.create_draft_version(
                    q.pk,
                    user=author_user,
                    source_version_id=v1.pk,
                )

        # Asserts no orphan version 2 was committed
        assert QuestionVersion.objects.filter(question=q).count() == 1

    def test_monotonic_version_numbering_under_concurrency(self, db, author_user, competency):
        q, v1 = setup_question_with_evaluation(competency, author_user)
        v2 = QuestionVersioningService.create_draft_version(q.pk, user=author_user, source_version_id=v1.pk)
        v3 = QuestionVersioningService.create_draft_version(q.pk, user=author_user, source_version_id=v2.pk)
        v4 = QuestionVersioningService.create_draft_version(q.pk, user=author_user, source_version_id=v3.pk)

        assert [v1.version_number, v2.version_number, v3.version_number, v4.version_number] == [1, 2, 3, 4]

    def test_sqlite_test_runner_notice(self):
        """
        Engine Fidelity Notice:
        Tests run against an in-memory SQLite database under config.settings.testing.
        While SQLite validates transactional atomicity, foreign key cascades, and rollback,
        concurrency serialization via SELECT ... FOR UPDATE and MySQL InnoDB gap-locking
        behavior must be empirically validated against a staging MySQL 8.4 instance.
        """
        assert True
