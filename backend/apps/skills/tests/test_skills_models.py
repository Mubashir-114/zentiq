"""
Tests for ZENTIQ Skill Taxonomy & Mastery Models.
Covers Domain, Subdomain, Competency, SkillPrerequisite, UserDomainMastery,
UserCompetencyMastery, PrerequisiteService cycle detection, database check constraints,
semantic identifier immutability, and safe seeder idempotency with --overwrite.
"""
from decimal import Decimal
import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError
from apps.skills.models import (
    Competency,
    Domain,
    SkillPrerequisite,
    Subdomain,
    UserCompetencyMastery,
    UserDomainMastery,
)
from apps.skills.services import PrerequisiteService

User = get_user_model()


@pytest.fixture
def test_user(db):
    return User.objects.create_user(
        email='pilot@zentiq.io',
        password='ValidPassword123!',
    )


@pytest.fixture
def sample_domain(db):
    return Domain.objects.create(
        slug='programming_logic',
        name='Programming Logic',
        category='TECHNICAL',
        description='Algorithmic execution and data structure reasoning.',
        icon_key='Code2',
        display_order=6,
    )


@pytest.fixture
def sample_subdomain(db, sample_domain):
    return Subdomain.objects.create(
        domain=sample_domain,
        slug='algorithmic-tracing',
        name='Algorithmic Tracing',
        description='State tracing and recursion analysis.',
        display_order=1,
    )


@pytest.fixture
def sample_competency(db, sample_subdomain):
    return Competency.objects.create(
        subdomain=sample_subdomain,
        code='PROG-TRACE-01',
        name='Iteration State Tracing',
        description='Tracing accumulator state through loops.',
        bloom_level='APPLY',
    )


@pytest.mark.django_db
class TestSkillDomainModel:
    def test_create_domain_success(self, sample_domain):
        assert sample_domain.id is not None
        assert sample_domain.slug == 'programming_logic'
        assert str(sample_domain) == 'Programming Logic (Technical)'

    def test_duplicate_slug_raises_integrity_error(self, sample_domain):
        with pytest.raises(IntegrityError):
            Domain.objects.create(
                slug='programming_logic',
                name='Duplicate Domain',
                category='COGNITIVE',
            )

    def test_domain_slug_is_immutable_on_update(self, sample_domain):
        sample_domain.name = 'Updated Programming Logic'
        sample_domain.save()  # Valid: updating other attributes is permitted
        sample_domain.refresh_from_db()
        assert sample_domain.name == 'Updated Programming Logic'

        sample_domain.slug = 'altered_slug'
        with pytest.raises(ValidationError) as exc_info:
            sample_domain.save()
        assert 'slug' in exc_info.value.message_dict


@pytest.mark.django_db
class TestSubdomainModel:
    def test_create_subdomain_success(self, sample_subdomain):
        assert sample_subdomain.id is not None
        assert str(sample_subdomain) == 'Programming Logic → Algorithmic Tracing'

    def test_duplicate_subdomain_slug_in_same_domain_fails(self, sample_subdomain, sample_domain):
        with pytest.raises(IntegrityError):
            Subdomain.objects.create(
                domain=sample_domain,
                slug='algorithmic-tracing',
                name='Duplicate Slug Subdomain',
            )

    def test_same_subdomain_slug_in_different_domain_allowed(self, sample_subdomain):
        other_domain = Domain.objects.create(
            slug='numerical_intelligence',
            name='Numerical Intelligence',
            category='COGNITIVE',
        )
        subdomain2 = Subdomain.objects.create(
            domain=other_domain,
            slug='algorithmic-tracing',
            name='Numerical Tracing',
        )
        assert subdomain2.id is not None


@pytest.mark.django_db
class TestCompetencyModel:
    def test_create_competency_success(self, sample_competency):
        assert sample_competency.id is not None
        assert str(sample_competency) == '[PROG-TRACE-01] Iteration State Tracing'
        assert sample_competency.bloom_level == 'APPLY'

    def test_duplicate_competency_code_fails(self, sample_competency, sample_subdomain):
        with pytest.raises(IntegrityError):
            Competency.objects.create(
                subdomain=sample_subdomain,
                code='PROG-TRACE-01',
                name='Another Competency with same code',
                bloom_level='ANALYZE',
            )

    def test_competency_code_is_immutable_on_update(self, sample_competency):
        sample_competency.name = 'Updated Title'
        sample_competency.save()  # Valid: updating non-code attributes permitted
        sample_competency.refresh_from_db()
        assert sample_competency.name == 'Updated Title'

        sample_competency.code = 'PROG-TRACE-99'
        with pytest.raises(ValidationError) as exc_info:
            sample_competency.save()
        assert 'code' in exc_info.value.message_dict


@pytest.mark.django_db
class TestSkillPrerequisiteAndCycleDetection:
    def test_valid_prerequisite_creation_service(self, sample_subdomain, sample_competency):
        comp_b = Competency.objects.create(
            subdomain=sample_subdomain,
            code='PROG-TRACE-02',
            name='Recursion Stack Unwinding',
            bloom_level='ANALYZE',
        )
        prereq = PrerequisiteService.create_prerequisite(
            competency=comp_b,
            prerequisite_competency=sample_competency,
            min_mastery_percentage=Decimal('75.00'),
        )
        assert prereq.id is not None
        assert 'PROG-TRACE-02 requires PROG-TRACE-01' in str(prereq)

    def test_duplicate_prerequisite_edge_fails(self, sample_subdomain, sample_competency):
        comp_b = Competency.objects.create(
            subdomain=sample_subdomain,
            code='PROG-TRACE-02',
            name='Recursion Stack Unwinding',
            bloom_level='ANALYZE',
        )
        SkillPrerequisite.objects.create(
            competency=comp_b,
            prerequisite_competency=sample_competency,
        )
        with pytest.raises(IntegrityError):
            SkillPrerequisite.objects.create(
                competency=comp_b,
                prerequisite_competency=sample_competency,
            )

    def test_self_referencing_prerequisite_fails(self, sample_competency):
        # Service level
        with pytest.raises(ValidationError) as exc_info:
            PrerequisiteService.create_prerequisite(
                competency=sample_competency,
                prerequisite_competency=sample_competency,
            )
        assert "cannot require itself" in str(exc_info.value)

        # Model save() / create() validation
        with pytest.raises(ValidationError):
            SkillPrerequisite.objects.create(
                competency=sample_competency,
                prerequisite_competency=sample_competency,
            )

        # Database CheckConstraint level (tested via bulk_create bypassing model save/clean)
        with pytest.raises(IntegrityError):
            SkillPrerequisite.objects.bulk_create([
                SkillPrerequisite(
                    competency=sample_competency,
                    prerequisite_competency=sample_competency,
                )
            ])

    def test_multi_node_cycle_rejection_three_nodes(self, sample_subdomain):
        """
        Tests cycle detection for A -> B -> C -> A.
        A requires B, B requires C, adding C requires A must fail with ValidationError.
        """
        comp_a = Competency.objects.create(
            subdomain=sample_subdomain, code='NODE-A', name='Node A', bloom_level='APPLY'
        )
        comp_b = Competency.objects.create(
            subdomain=sample_subdomain, code='NODE-B', name='Node B', bloom_level='APPLY'
        )
        comp_c = Competency.objects.create(
            subdomain=sample_subdomain, code='NODE-C', name='Node C', bloom_level='APPLY'
        )

        # A requires B
        PrerequisiteService.create_prerequisite(competency=comp_a, prerequisite_competency=comp_b)
        # B requires C
        PrerequisiteService.create_prerequisite(competency=comp_b, prerequisite_competency=comp_c)

        # Now C requires A -> Creates cycle A -> B -> C -> A
        assert PrerequisiteService.has_cycle(comp_c, comp_a) is True

        with pytest.raises(ValidationError) as exc_info:
            PrerequisiteService.create_prerequisite(competency=comp_c, prerequisite_competency=comp_a)
        assert "Circular prerequisite detected" in str(exc_info.value)

        # Also verify ModelForm/model.clean() catches the cycle
        candidate_prereq = SkillPrerequisite(competency=comp_c, prerequisite_competency=comp_a)
        with pytest.raises(ValidationError):
            candidate_prereq.clean()

    def test_valid_acyclic_multi_branch_graph(self, sample_subdomain):
        """
        Tests that valid DAG structures (diamond / tree) are accepted without false positive cycles.
        D requires B and C; both B and C require A.
        """
        comp_a = Competency.objects.create(subdomain=sample_subdomain, code='DAG-A', name='A')
        comp_b = Competency.objects.create(subdomain=sample_subdomain, code='DAG-B', name='B')
        comp_c = Competency.objects.create(subdomain=sample_subdomain, code='DAG-C', name='C')
        comp_d = Competency.objects.create(subdomain=sample_subdomain, code='DAG-D', name='D')

        PrerequisiteService.create_prerequisite(comp_b, comp_a)
        PrerequisiteService.create_prerequisite(comp_c, comp_a)
        PrerequisiteService.create_prerequisite(comp_d, comp_b)
        PrerequisiteService.create_prerequisite(comp_d, comp_c)

        assert SkillPrerequisite.objects.filter(competency=comp_d).count() == 2
        chain = PrerequisiteService.get_prerequisite_chain(comp_d)
        chain_codes = [c.code for c in chain]
        assert 'DAG-A' in chain_codes
        assert 'DAG-B' in chain_codes
        assert 'DAG-C' in chain_codes


@pytest.mark.django_db
class TestMasteryDatabaseConstraints:
    def test_mastery_score_boundaries_accepted(self, test_user, sample_domain, sample_competency):
        # Exactly 0.00 is valid
        dom_min = UserDomainMastery.objects.create(
            user=test_user, domain=sample_domain, mastery_score=Decimal('0.00')
        )
        assert dom_min.mastery_score == Decimal('0.00')

        # Exactly 100.00 is valid
        comp_max = UserCompetencyMastery.objects.create(
            user=test_user, competency=sample_competency, mastery_score=Decimal('100.00')
        )
        assert comp_max.mastery_score == Decimal('100.00')

    def test_user_domain_mastery_negative_score_rejected_by_db(self, test_user, sample_domain):
        with pytest.raises(IntegrityError):
            UserDomainMastery.objects.create(
                user=test_user,
                domain=sample_domain,
                mastery_score=Decimal('-0.01'),
            )

    def test_user_domain_mastery_over_100_score_rejected_by_db(self, test_user, sample_domain):
        with pytest.raises(IntegrityError):
            UserDomainMastery.objects.create(
                user=test_user,
                domain=sample_domain,
                mastery_score=Decimal('100.01'),
            )

    def test_user_domain_mastery_negative_counter_rejected_by_db(self, test_user, sample_domain):
        with pytest.raises(IntegrityError):
            UserDomainMastery.objects.create(
                user=test_user,
                domain=sample_domain,
                mastery_score=Decimal('50.00'),
                total_assessments_completed=-1,
            )

    def test_user_competency_mastery_negative_score_rejected_by_db(self, test_user, sample_competency):
        with pytest.raises(IntegrityError):
            UserCompetencyMastery.objects.create(
                user=test_user,
                competency=sample_competency,
                mastery_score=Decimal('-5.00'),
            )

    def test_user_competency_mastery_over_100_score_rejected_by_db(self, test_user, sample_competency):
        with pytest.raises(IntegrityError):
            UserCompetencyMastery.objects.create(
                user=test_user,
                competency=sample_competency,
                mastery_score=Decimal('105.00'),
            )

    def test_user_competency_mastery_negative_evals_rejected_by_db(self, test_user, sample_competency):
        with pytest.raises(IntegrityError):
            UserCompetencyMastery.objects.create(
                user=test_user,
                competency=sample_competency,
                evaluations_count=-1,
            )

    def test_skill_prerequisite_mastery_percentage_db_range_rejected(self, sample_competency, sample_subdomain):
        comp_b = Competency.objects.create(subdomain=sample_subdomain, code='PROG-P1', name='P1')
        with pytest.raises(IntegrityError):
            SkillPrerequisite.objects.create(
                competency=comp_b,
                prerequisite_competency=sample_competency,
                min_mastery_percentage=Decimal('100.50'),
            )


@pytest.mark.django_db
class TestTaxonomySeederSafetyAndOverwrite:
    def test_seed_skills_taxonomy_creates_all_eight_domains(self):
        call_command('seed_skills_taxonomy')

        assert Domain.objects.count() == 8
        assert Subdomain.objects.count() >= 20
        assert Competency.objects.count() >= 40

        expected_slugs = {
            'numerical_intelligence',
            'logical_reasoning',
            'verbal_intelligence',
            'analytical_thinking',
            'spatial_intelligence',
            'programming_logic',
            'critical_thinking',
            'career_readiness',
        }
        db_slugs = set(Domain.objects.values_list('slug', flat=True))
        assert expected_slugs == db_slugs

    def test_seeder_preserves_customizations_by_default(self):
        call_command('seed_skills_taxonomy')

        # Admin customizes an entry and deactivates a competency
        domain = Domain.objects.get(slug='programming_logic')
        domain.name = 'Customized Programming Logic'
        domain.save()

        comp = Competency.objects.get(code='PROG-TRACE-01')
        comp.is_active = False
        comp.description = 'Customized admin instructions.'
        comp.save()

        # Run seeder in default safe mode
        call_command('seed_skills_taxonomy')

        domain.refresh_from_db()
        comp.refresh_from_db()

        assert domain.name == 'Customized Programming Logic'
        assert comp.is_active is False
        assert comp.description == 'Customized admin instructions.'

    def test_seeder_overwrite_updates_customizations_when_requested(self):
        call_command('seed_skills_taxonomy')

        # Admin customizes an entry
        domain = Domain.objects.get(slug='programming_logic')
        domain.name = 'Customized Programming Logic'
        domain.save()

        comp = Competency.objects.get(code='PROG-TRACE-01')
        comp.is_active = False
        comp.save()

        # Run seeder with explicit --overwrite
        call_command('seed_skills_taxonomy', overwrite=True)

        domain.refresh_from_db()
        comp.refresh_from_db()

        # Overwrite restored defaults
        assert domain.name == 'Programming Logic'
        assert comp.is_active is True
