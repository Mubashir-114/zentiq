"""
Tests for ZENTIQ Arena Domain Services (Phase 2C.1).
Covers QuestionCompositionService, exception hierarchy, authorization guards,
concurrency serialization, Decimal normalization, and transactional rollback.
"""
from decimal import Decimal
from pathlib import Path
import sys
from unittest.mock import patch

# Ensure backend root is on sys.path
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
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
    ArenaServiceError,
    CompetencyMappingInvalidError,
    CompetencyNotFoundError,
    EvaluationDataMissingError,
    QuestionCompositionService,
    QuestionImmutabilityError,
    QuestionNotFoundError,
    QuestionPermissionDeniedError,
    QuestionVersionNotFoundError,
    TagNotFoundError,
    can_modify_draft,
    can_view_evaluation_data,
)
from apps.skills.models import Competency, Domain, Subdomain

User = get_user_model()


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def author_user(db):
    return User.objects.create_user(
        email='author@example.com',
        password='TestPassword123!',
    )


@pytest.fixture
def other_user(db):
    return User.objects.create_user(
        email='other@example.com',
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
        slug='deductive-reasoning',
        name='Deductive Reasoning',
        display_order=1,
    )


@pytest.fixture
def comp_primary(db, subdomain):
    return Competency.objects.create(
        subdomain=subdomain,
        code='LOG-DED-01',
        name='Categorical Syllogisms',
        description='Evaluate validity of syllogistic arguments.',
        bloom_level='ANALYZE',
    )


@pytest.fixture
def comp_secondary_a(db, subdomain):
    return Competency.objects.create(
        subdomain=subdomain,
        code='LOG-DED-02',
        name='Propositional Fallacies',
        description='Detect logical fallacies in conditional statements.',
        bloom_level='EVALUATE',
    )


@pytest.fixture
def comp_secondary_b(db, subdomain):
    return Competency.objects.create(
        subdomain=subdomain,
        code='LOG-DED-03',
        name='Modal Logic Operators',
        description='Analyze necessity and possibility operators.',
        bloom_level='APPLY',
    )


@pytest.fixture
def draft_question_and_version(db, author_user, comp_primary):
    question = Question.objects.create(
        code='QST-LOG-TEST-001',
        created_by=author_user,
    )
    version = QuestionVersion.objects.create(
        question=question,
        version_number=1,
        status='DRAFT',
        title='Syllogism Analysis Challenge',
        prompt='Which conclusion follows from the given premises?',
        question_type='SINGLE_CHOICE',
        primary_competency=comp_primary,
        created_by=author_user,
    )
    # Provision matching initial primary competency mapping
    primary_mapping = QuestionCompetencyMapping.objects.create(
        question_version=version,
        competency=comp_primary,
        is_primary=True,
        weight=Decimal('1.00'),
    )
    return question, version, primary_mapping


@pytest.fixture
def tags(db):
    t1 = Tag.objects.create(slug='logic', name='Logic', category='TOPIC')
    t2 = Tag.objects.create(slug='syllogism', name='Syllogism', category='TOPIC')
    t3 = Tag.objects.create(slug='lsat', name='LSAT Exam', category='EXAM')
    return [t1, t2, t3]


# -----------------------------------------------------------------------------
# 1. Authorization & RBAC Tests
# -----------------------------------------------------------------------------

class TestCompositionServicePermissions:

    def test_author_can_modify_draft(self, draft_question_and_version, author_user):
        _, version, _ = draft_question_and_version
        assert can_modify_draft(author_user, version) is True

    def test_superuser_can_modify_draft(self, draft_question_and_version, superuser):
        _, version, _ = draft_question_and_version
        assert can_modify_draft(superuser, version) is True

    def test_user_with_change_permission_can_modify_draft(self, draft_question_and_version, other_user):
        _, version, _ = draft_question_and_version
        ct = ContentType.objects.get_for_model(QuestionVersion)
        perm = Permission.objects.get(codename='change_questionversion', content_type=ct)
        other_user.user_permissions.add(perm)
        # Reload user permissions cache
        other_user = User.objects.get(pk=other_user.pk)
        assert can_modify_draft(other_user, version) is True

    def test_staff_without_explicit_permission_cannot_modify_draft(self, draft_question_and_version, staff_user):
        _, version, _ = draft_question_and_version
        # is_staff alone must not grant draft modification
        assert can_modify_draft(staff_user, version) is False
        with pytest.raises(QuestionPermissionDeniedError):
            QuestionCompositionService.add_secondary_competency(
                version_id=version.pk,
                competency=version.primary_competency,
                weight=Decimal('0.20'),
                user=staff_user,
            )

    def test_unrelated_user_cannot_modify_draft(self, draft_question_and_version, other_user):
        _, version, _ = draft_question_and_version
        assert can_modify_draft(other_user, version) is False
        with pytest.raises(QuestionPermissionDeniedError):
            QuestionCompositionService.add_secondary_competency(
                version_id=version.pk,
                competency=version.primary_competency,
                weight=Decimal('0.20'),
                user=other_user,
            )

    def test_unauthenticated_or_none_user_cannot_modify_draft(self, draft_question_and_version):
        _, version, _ = draft_question_and_version
        assert can_modify_draft(None, version) is False
        with pytest.raises(QuestionPermissionDeniedError):
            QuestionCompositionService.add_secondary_competency(
                version_id=version.pk,
                competency=version.primary_competency,
                weight=Decimal('0.20'),
                user=None,
            )

    def test_author_can_view_evaluation_data(self, draft_question_and_version, author_user):
        _, version, _ = draft_question_and_version
        assert can_view_evaluation_data(author_user, version) is True

    def test_superuser_can_view_evaluation_data(self, draft_question_and_version, superuser):
        _, version, _ = draft_question_and_version
        assert can_view_evaluation_data(superuser, version) is True

    def test_user_with_view_permission_can_view_evaluation_data(self, draft_question_and_version, other_user):
        _, version, _ = draft_question_and_version
        ct = ContentType.objects.get_for_model(QuestionEvaluationData)
        perm = Permission.objects.get(codename='view_questionevaluationdata', content_type=ct)
        other_user.user_permissions.add(perm)
        other_user = User.objects.get(pk=other_user.pk)
        assert can_view_evaluation_data(other_user, version) is True

    def test_staff_without_view_permission_cannot_view_evaluation_data(self, draft_question_and_version, staff_user):
        _, version, _ = draft_question_and_version
        assert can_view_evaluation_data(staff_user, version) is False
        with pytest.raises(QuestionPermissionDeniedError):
            QuestionCompositionService.get_evaluation_data(version.pk, user=staff_user)

    def test_unrelated_user_cannot_view_evaluation_data(self, draft_question_and_version, other_user):
        _, version, _ = draft_question_and_version
        assert can_view_evaluation_data(other_user, version) is False
        with pytest.raises(QuestionPermissionDeniedError):
            QuestionCompositionService.get_evaluation_data(version.pk, user=other_user)


# -----------------------------------------------------------------------------
# 2. Evaluation Data Validation & Isolation Tests
# -----------------------------------------------------------------------------

class TestEvaluationDataComposition:

    def test_set_evaluation_data_valid_strategy_succeeds(self, draft_question_and_version, author_user):
        _, version, _ = draft_question_and_version
        eval_data = QuestionCompositionService.set_evaluation_data(
            version_id=version.pk,
            grading_strategy='EXACT_MATCH',
            correct_payload={'correct_option_id': 'opt_1'},
            scoring_rubric={'max_score': 10},
            user=author_user,
        )
        assert eval_data.pk == version.pk
        assert eval_data.grading_strategy == 'EXACT_MATCH'
        assert eval_data.correct_payload == {'correct_option_id': 'opt_1'}
        assert eval_data.scoring_rubric == {'max_score': 10}

        # Verify retrieval
        retrieved = QuestionCompositionService.get_evaluation_data(version.pk, user=author_user)
        assert retrieved.pk == eval_data.pk

    def test_set_evaluation_data_invalid_strategy_rejected(self, draft_question_and_version, author_user):
        _, version, _ = draft_question_and_version
        with pytest.raises(ArenaServiceError) as exc_info:
            QuestionCompositionService.set_evaluation_data(
                version_id=version.pk,
                grading_strategy='INVALID_NONEXISTENT_STRATEGY',
                correct_payload={'target': 42},
                user=author_user,
            )
        assert "Invalid grading strategy" in str(exc_info.value)

    def test_set_evaluation_data_supports_non_dict_json_payloads(self, draft_question_and_version, author_user):
        _, version, _ = draft_question_and_version
        # Test integer payload
        eval_data = QuestionCompositionService.set_evaluation_data(
            version_id=version.pk,
            grading_strategy='NUMERIC_TOLERANCE',
            correct_payload=42,
            user=author_user,
        )
        assert eval_data.correct_payload == 42

        # Test list payload
        eval_data_list = QuestionCompositionService.set_evaluation_data(
            version_id=version.pk,
            grading_strategy='SET_MATCH',
            correct_payload=['opt_a', 'opt_c'],
            user=author_user,
        )
        assert eval_data_list.correct_payload == ['opt_a', 'opt_c']

    def test_get_evaluation_data_missing_raises_error(self, draft_question_and_version, author_user):
        _, version, _ = draft_question_and_version
        with pytest.raises(EvaluationDataMissingError):
            QuestionCompositionService.get_evaluation_data(version.pk, user=author_user)

    def test_evaluation_data_modification_rejected_on_non_draft(self, draft_question_and_version, author_user):
        _, version, _ = draft_question_and_version
        version.status = 'IN_REVIEW'
        version.save()

        with pytest.raises(QuestionImmutabilityError):
            QuestionCompositionService.set_evaluation_data(
                version_id=version.pk,
                grading_strategy='EXACT_MATCH',
                correct_payload={'correct': True},
                user=author_user,
            )


# -----------------------------------------------------------------------------
# 3. Decimal Normalization & Bound Tests
# -----------------------------------------------------------------------------

class TestDecimalNormalization:

    def test_reject_boolean_weight(self, draft_question_and_version, comp_secondary_a, author_user):
        _, version, _ = draft_question_and_version
        with pytest.raises(CompetencyMappingInvalidError) as exc:
            QuestionCompositionService.add_secondary_competency(
                version_id=version.pk,
                competency=comp_secondary_a,
                weight=True,
                user=author_user,
            )
        assert "boolean values are not valid weights" in str(exc.value)

    def test_reject_none_weight(self, draft_question_and_version, comp_secondary_a, author_user):
        _, version, _ = draft_question_and_version
        with pytest.raises(CompetencyMappingInvalidError) as exc:
            QuestionCompositionService.add_secondary_competency(
                version_id=version.pk,
                competency=comp_secondary_a,
                weight=None,
                user=author_user,
            )
        assert "weight cannot be None" in str(exc.value)

    def test_reject_nan_and_infinity_weight(self, draft_question_and_version, comp_secondary_a, author_user):
        _, version, _ = draft_question_and_version
        with pytest.raises(CompetencyMappingInvalidError):
            QuestionCompositionService.add_secondary_competency(
                version_id=version.pk,
                competency=comp_secondary_a,
                weight=float('nan'),
                user=author_user,
            )
        with pytest.raises(CompetencyMappingInvalidError):
            QuestionCompositionService.add_secondary_competency(
                version_id=version.pk,
                competency=comp_secondary_a,
                weight=float('inf'),
                user=author_user,
            )

    def test_reject_out_of_bounds_weight(self, draft_question_and_version, comp_secondary_a, author_user):
        _, version, _ = draft_question_and_version
        # Below 0.05
        with pytest.raises(CompetencyMappingInvalidError) as exc:
            QuestionCompositionService.add_secondary_competency(
                version_id=version.pk,
                competency=comp_secondary_a,
                weight='0.04',
                user=author_user,
            )
        assert "must be between 0.05 and 1.00" in str(exc.value)

        # Above 1.00
        with pytest.raises(CompetencyMappingInvalidError) as exc:
            QuestionCompositionService.add_secondary_competency(
                version_id=version.pk,
                competency=comp_secondary_a,
                weight='1.01',
                user=author_user,
            )
        assert "must be between 0.05 and 1.00" in str(exc.value)


# -----------------------------------------------------------------------------
# 4. Primary Competency Workflow Tests
# -----------------------------------------------------------------------------

class TestPrimaryCompetencyWorkflow:

    def test_set_primary_competency_missing_record_raises_competency_not_found(
        self, draft_question_and_version, author_user
    ):
        _, version, _ = draft_question_and_version
        fake_uuid = '00000000-0000-0000-0000-000000009999'
        with pytest.raises(CompetencyNotFoundError):
            QuestionCompositionService.set_primary_competency(
                version_id=version.pk,
                competency=fake_uuid,
                user=author_user,
            )

    def test_set_primary_competency_updates_version_and_reconciles_mapping(
        self, draft_question_and_version, comp_secondary_a, author_user
    ):
        _, version, initial_primary = draft_question_and_version
        updated_version, primary_map = QuestionCompositionService.set_primary_competency(
            version_id=version.pk,
            competency=comp_secondary_a,
            user=author_user,
        )
        assert updated_version.primary_competency == comp_secondary_a
        assert primary_map.competency == comp_secondary_a
        assert primary_map.is_primary is True
        # Preserved previous primary weight (Decimal('1.00'))
        assert primary_map.weight == Decimal('1.00')

        # Verify exactly one primary mapping exists in DB
        primaries = QuestionCompetencyMapping.objects.filter(
            question_version=version,
            is_primary=True,
        )
        assert primaries.count() == 1
        assert primaries.first().competency == comp_secondary_a

    def test_set_primary_competency_preserves_custom_primary_weight(
        self, draft_question_and_version, comp_secondary_a, author_user
    ):
        _, version, initial_primary = draft_question_and_version
        initial_primary.weight = Decimal('0.85')
        initial_primary.save()

        # Update without specifying weight: should preserve 0.85
        _, primary_map = QuestionCompositionService.set_primary_competency(
            version_id=version.pk,
            competency=comp_secondary_a,
            user=author_user,
        )
        assert primary_map.weight == Decimal('0.85')

        # Update with explicit weight
        _, primary_map_custom = QuestionCompositionService.set_primary_competency(
            version_id=version.pk,
            competency=comp_secondary_a,
            weight='0.75',
            user=author_user,
        )
        assert primary_map_custom.weight == Decimal('0.75')

    def test_set_primary_competency_removes_existing_secondary_collision(
        self, draft_question_and_version, comp_secondary_a, author_user
    ):
        _, version, _ = draft_question_and_version
        # Add comp_secondary_a as a secondary mapping first
        QuestionCompositionService.add_secondary_competency(
            version_id=version.pk,
            competency=comp_secondary_a,
            weight=Decimal('0.30'),
            user=author_user,
        )
        assert QuestionCompetencyMapping.objects.filter(
            question_version=version,
            competency=comp_secondary_a,
            is_primary=False,
        ).exists()

        # Now promote comp_secondary_a to primary
        _, primary_map = QuestionCompositionService.set_primary_competency(
            version_id=version.pk,
            competency=comp_secondary_a,
            user=author_user,
        )
        assert primary_map.competency == comp_secondary_a
        assert primary_map.is_primary is True

        # Secondary mapping for comp_secondary_a must be gone
        assert not QuestionCompetencyMapping.objects.filter(
            question_version=version,
            competency=comp_secondary_a,
            is_primary=False,
        ).exists()

    def test_set_primary_competency_excluded_from_secondary_aggregate(
        self, draft_question_and_version, comp_secondary_a, comp_secondary_b, author_user
    ):
        _, version, primary_map = draft_question_and_version
        # Primary mapping has weight 1.00
        assert primary_map.weight == Decimal('1.00')

        # Adding secondary competencies should still be permitted up to sum <= 1.00
        sec_a = QuestionCompositionService.add_secondary_competency(
            version_id=version.pk,
            competency=comp_secondary_a,
            weight=Decimal('0.60'),
            user=author_user,
        )
        sec_b = QuestionCompositionService.add_secondary_competency(
            version_id=version.pk,
            competency=comp_secondary_b,
            weight=Decimal('0.40'),
            user=author_user,
        )
        assert sec_a.weight + sec_b.weight == Decimal('1.00')

    def test_set_primary_competency_rejected_on_non_draft(
        self, draft_question_and_version, comp_secondary_a, author_user
    ):
        _, version, _ = draft_question_and_version
        version.status = 'IN_REVIEW'
        version.save()

        with pytest.raises(QuestionImmutabilityError):
            QuestionCompositionService.set_primary_competency(
                version_id=version.pk,
                competency=comp_secondary_a,
                user=author_user,
            )


# -----------------------------------------------------------------------------
# 5. Secondary Competency Composition & Aggregate Weight Tests
# -----------------------------------------------------------------------------

class TestSecondaryCompetenciesComposition:

    def test_add_secondary_competency_success(
        self, draft_question_and_version, comp_secondary_a, author_user
    ):
        _, version, _ = draft_question_and_version
        mapping = QuestionCompositionService.add_secondary_competency(
            version_id=version.pk,
            competency=comp_secondary_a,
            weight=Decimal('0.45'),
            user=author_user,
        )
        assert mapping.competency == comp_secondary_a
        assert mapping.weight == Decimal('0.45')
        assert mapping.is_primary is False

    def test_add_secondary_competency_aggregate_exceeds_cap_rejected(
        self, draft_question_and_version, comp_secondary_a, comp_secondary_b, author_user
    ):
        _, version, _ = draft_question_and_version
        QuestionCompositionService.add_secondary_competency(
            version_id=version.pk,
            competency=comp_secondary_a,
            weight=Decimal('0.60'),
            user=author_user,
        )

        # 0.60 + 0.50 = 1.10 > 1.00 -> Rejected
        with pytest.raises(CompetencyMappingInvalidError) as exc:
            QuestionCompositionService.add_secondary_competency(
                version_id=version.pk,
                competency=comp_secondary_b,
                weight=Decimal('0.50'),
                user=author_user,
            )
        assert "exceeds the maximum allowed of 1.00" in str(exc.value)

    def test_update_secondary_competency_weight_aggregate_validation(
        self, draft_question_and_version, comp_secondary_a, comp_secondary_b, author_user
    ):
        _, version, _ = draft_question_and_version
        QuestionCompositionService.add_secondary_competency(
            version_id=version.pk,
            competency=comp_secondary_a,
            weight=Decimal('0.40'),
            user=author_user,
        )
        QuestionCompositionService.add_secondary_competency(
            version_id=version.pk,
            competency=comp_secondary_b,
            weight=Decimal('0.40'),
            user=author_user,
        )

        # Update comp_secondary_a to 0.60 -> total is 0.60 + 0.40 = 1.00 -> Succeeded
        updated = QuestionCompositionService.update_secondary_competency_weight(
            version_id=version.pk,
            competency=comp_secondary_a,
            weight=Decimal('0.60'),
            user=author_user,
        )
        assert updated.weight == Decimal('0.60')

        # Update comp_secondary_a to 0.70 -> total is 0.70 + 0.40 = 1.10 -> Rejected
        with pytest.raises(CompetencyMappingInvalidError) as exc:
            QuestionCompositionService.update_secondary_competency_weight(
                version_id=version.pk,
                competency=comp_secondary_a,
                weight=Decimal('0.70'),
                user=author_user,
            )
        assert "exceeds the maximum allowed of 1.00" in str(exc.value)

    def test_add_secondary_competency_matching_primary_rejected(
        self, draft_question_and_version, comp_primary, author_user
    ):
        _, version, _ = draft_question_and_version
        with pytest.raises(CompetencyMappingInvalidError) as exc:
            QuestionCompositionService.add_secondary_competency(
                version_id=version.pk,
                competency=comp_primary,
                weight=Decimal('0.20'),
                user=author_user,
            )
        assert "primary competency" in str(exc.value)

    def test_add_duplicate_secondary_competency_rejected(
        self, draft_question_and_version, comp_secondary_a, author_user
    ):
        _, version, _ = draft_question_and_version
        QuestionCompositionService.add_secondary_competency(
            version_id=version.pk,
            competency=comp_secondary_a,
            weight=Decimal('0.20'),
            user=author_user,
        )
        with pytest.raises(CompetencyMappingInvalidError) as exc:
            QuestionCompositionService.add_secondary_competency(
                version_id=version.pk,
                competency=comp_secondary_a,
                weight=Decimal('0.30'),
                user=author_user,
            )
        assert "already mapped" in str(exc.value)

    def test_set_secondary_competencies_batch_rejects_duplicates(
        self, draft_question_and_version, comp_secondary_a, author_user
    ):
        _, version, _ = draft_question_and_version
        spec = [
            {'competency': comp_secondary_a, 'weight': Decimal('0.20')},
            {'competency': comp_secondary_a, 'weight': Decimal('0.30')},
        ]
        with pytest.raises(CompetencyMappingInvalidError) as exc:
            QuestionCompositionService.set_secondary_competencies(
                version_id=version.pk,
                mappings_spec=spec,
                user=author_user,
            )
        assert "Duplicate competency" in str(exc.value)

    def test_set_secondary_competencies_batch_atomic_success(
        self, draft_question_and_version, comp_secondary_a, comp_secondary_b, author_user
    ):
        _, version, _ = draft_question_and_version
        # Initial secondary mapping
        QuestionCompositionService.add_secondary_competency(
            version_id=version.pk,
            competency=comp_secondary_a,
            weight=Decimal('0.30'),
            user=author_user,
        )

        # Batch synchronize: update secondary_a, add secondary_b
        spec = [
            {'competency': comp_secondary_a, 'weight': Decimal('0.50')},
            {'competency': comp_secondary_b, 'weight': Decimal('0.40')},
        ]
        results = QuestionCompositionService.set_secondary_competencies(
            version_id=version.pk,
            mappings_spec=spec,
            user=author_user,
        )
        assert len(results) == 2
        weights = {r.competency.code: r.weight for r in results}
        assert weights['LOG-DED-02'] == Decimal('0.50')
        assert weights['LOG-DED-03'] == Decimal('0.40')

        # Now synchronize with only secondary_b: secondary_a should be removed
        spec2 = [{'competency': comp_secondary_b, 'weight': Decimal('0.80')}]
        results2 = QuestionCompositionService.set_secondary_competencies(
            version_id=version.pk,
            mappings_spec=spec2,
            user=author_user,
        )
        assert len(results2) == 1
        assert results2[0].competency == comp_secondary_b
        assert not QuestionCompetencyMapping.objects.filter(
            question_version=version,
            competency=comp_secondary_a,
        ).exists()

    def test_remove_secondary_competency_deletes_instance(
        self, draft_question_and_version, comp_secondary_a, author_user
    ):
        _, version, _ = draft_question_and_version
        QuestionCompositionService.add_secondary_competency(
            version_id=version.pk,
            competency=comp_secondary_a,
            weight=Decimal('0.25'),
            user=author_user,
        )
        assert QuestionCompetencyMapping.objects.filter(
            question_version=version,
            competency=comp_secondary_a,
        ).exists()

        QuestionCompositionService.remove_secondary_competency(
            version_id=version.pk,
            competency=comp_secondary_a,
            user=author_user,
        )
        assert not QuestionCompetencyMapping.objects.filter(
            question_version=version,
            competency=comp_secondary_a,
        ).exists()

    def test_remove_primary_competency_via_secondary_method_rejected(
        self, draft_question_and_version, comp_primary, author_user
    ):
        _, version, _ = draft_question_and_version
        with pytest.raises(CompetencyMappingInvalidError) as exc:
            QuestionCompositionService.remove_secondary_competency(
                version_id=version.pk,
                competency=comp_primary,
                user=author_user,
            )
        assert "primary competency mapping" in str(exc.value)


# -----------------------------------------------------------------------------
# 6. Tag Synchronization Tests
# -----------------------------------------------------------------------------

class TestTagComposition:

    def test_sync_version_tags_missing_slug_raises_tag_not_found(
        self, draft_question_and_version, tags, author_user
    ):
        _, version, _ = draft_question_and_version
        with pytest.raises(TagNotFoundError) as exc_info:
            QuestionCompositionService.sync_version_tags(
                version_id=version.pk,
                tag_slugs=['logic', 'non-existent-tag-xyz'],
                user=author_user,
            )
        assert 'non-existent-tag-xyz' in exc_info.value.details['missing_slugs']
        # No tags should have been attached
        assert QuestionVersionTag.objects.filter(question_version=version).count() == 0

    def test_sync_version_tags_deduplicates_input_slugs(
        self, draft_question_and_version, tags, author_user
    ):
        _, version, _ = draft_question_and_version
        result = QuestionCompositionService.sync_version_tags(
            version_id=version.pk,
            tag_slugs=['logic', 'syllogism', 'logic', 'syllogism'],
            user=author_user,
        )
        assert len(result) == 2
        assert QuestionVersionTag.objects.filter(question_version=version).count() == 2

    def test_sync_version_tags_additive_subtractive_atomic(
        self, draft_question_and_version, tags, author_user
    ):
        _, version, _ = draft_question_and_version
        # Initial sync: logic + syllogism
        QuestionCompositionService.sync_version_tags(
            version_id=version.pk,
            tag_slugs=['logic', 'syllogism'],
            user=author_user,
        )
        assert QuestionVersionTag.objects.filter(question_version=version).count() == 2

        # Subsequent sync: syllogism + lsat (logic should be removed)
        result = QuestionCompositionService.sync_version_tags(
            version_id=version.pk,
            tag_slugs=['syllogism', 'lsat'],
            user=author_user,
        )
        assert len(result) == 2
        slugs = {t.slug for t in result}
        assert slugs == {'syllogism', 'lsat'}
        assert not QuestionVersionTag.objects.filter(
            question_version=version,
            tag__slug='logic',
        ).exists()

    def test_sync_version_tags_rejected_on_non_draft(
        self, draft_question_and_version, tags, author_user
    ):
        _, version, _ = draft_question_and_version
        version.status = 'IN_REVIEW'
        version.save()

        with pytest.raises(QuestionImmutabilityError):
            QuestionCompositionService.sync_version_tags(
                version_id=version.pk,
                tag_slugs=['logic'],
                user=author_user,
            )


# -----------------------------------------------------------------------------
# 7. Transaction Rollback & Stale State Tests
# -----------------------------------------------------------------------------

class TestCompositionServiceAtomicityAndStaleState:

    def test_failure_halfway_through_set_secondary_competencies_rolls_back_all(
        self, draft_question_and_version, comp_secondary_a, comp_secondary_b, author_user
    ):
        _, version, _ = draft_question_and_version
        # Pre-populate secondary_a
        QuestionCompositionService.add_secondary_competency(
            version_id=version.pk,
            competency=comp_secondary_a,
            weight=Decimal('0.25'),
            user=author_user,
        )
        assert QuestionCompetencyMapping.objects.filter(
            question_version=version,
            is_primary=False,
        ).count() == 1

        # Attempt batch update where the second spec causes aggregate weight to exceed 1.00
        spec = [
            {'competency': comp_secondary_a, 'weight': Decimal('0.50')},
            {'competency': comp_secondary_b, 'weight': Decimal('0.60')},  # 0.50 + 0.60 = 1.10
        ]
        with pytest.raises(CompetencyMappingInvalidError):
            QuestionCompositionService.set_secondary_competencies(
                version_id=version.pk,
                mappings_spec=spec,
                user=author_user,
            )

        # Confirm rollback: initial mapping is preserved exactly as 0.25
        mappings = QuestionCompetencyMapping.objects.filter(
            question_version=version,
            is_primary=False,
        )
        assert mappings.count() == 1
        assert mappings.first().weight == Decimal('0.25')
        assert not mappings.filter(competency=comp_secondary_b).exists()

    def test_stale_question_version_instance_cannot_override_fresh_database_state(
        self, draft_question_and_version, comp_secondary_a, author_user
    ):
        _, version, _ = draft_question_and_version
        # Stale in-memory reference retains status='DRAFT'
        stale_in_memory_version = QuestionVersion.objects.get(pk=version.pk)
        assert stale_in_memory_version.status == 'DRAFT'

        # Directly update DB status to PUBLISHED behind its back
        QuestionVersion.objects.filter(pk=version.pk).update(status='PUBLISHED')

        # Calling service with the stale in-memory instance must re-query and raise QuestionImmutabilityError
        with pytest.raises(QuestionImmutabilityError):
            QuestionCompositionService.add_secondary_competency(
                version_id=stale_in_memory_version,  # passing stale instance
                competency=comp_secondary_a,
                weight=Decimal('0.20'),
                user=author_user,
            )

    def test_failure_during_set_primary_competency_rolls_back_version_and_mappings(
        self, draft_question_and_version, comp_primary, comp_secondary_a, author_user
    ):
        _, version, initial_primary = draft_question_and_version
        initial_comp_id = version.primary_competency_id

        # Patch QuestionCompetencyMapping.save to fail simulating a mid-operation DB error
        with patch.object(QuestionCompetencyMapping, 'save', side_effect=IntegrityError("Simulated DB error")):
            with pytest.raises(IntegrityError):
                QuestionCompositionService.set_primary_competency(
                    version_id=version.pk,
                    competency=comp_secondary_a,
                    user=author_user,
                )

        # Verify rollback: QuestionVersion primary_competency did not change
        version.refresh_from_db()
        assert version.primary_competency_id == initial_comp_id

        # Primary mapping did not change
        initial_primary.refresh_from_db()
        assert initial_primary.competency_id == initial_comp_id

    def test_failure_during_sync_version_tags_does_not_leave_partial_associations(
        self, draft_question_and_version, tags, author_user
    ):
        _, version, _ = draft_question_and_version
        # Initial tag
        QuestionCompositionService.sync_version_tags(
            version_id=version.pk,
            tag_slugs=['logic'],
            user=author_user,
        )
        assert QuestionVersionTag.objects.filter(question_version=version).count() == 1

        # Attempt sync where second tag slug is invalid
        with pytest.raises(TagNotFoundError):
            QuestionCompositionService.sync_version_tags(
                version_id=version.pk,
                tag_slugs=['syllogism', 'nonexistent-tag'],
                user=author_user,
            )

        # Confirm rollback: only 'logic' tag remains
        current_tags = QuestionVersionTag.objects.filter(question_version=version)
        assert current_tags.count() == 1
        assert current_tags.first().tag.slug == 'logic'
