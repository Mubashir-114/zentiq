"""
Focused API Tests for ZENTIQ Assessment Execution REST API (Milestone 4A - Phase 2D.3).
Covers:
- Anonymous access denial and authentication enforcement
- CSRF behavior with session cookies
- Assessment catalog listing and detail retrieval
- Exclusion of deprecated and unready assessments
- Attempt start and idempotent replay with mandatory Idempotency-Key header
- Missing, blank, and oversized Idempotency-Key validation
- Active-attempt conflict (409 Conflict)
- Attempt ownership and IDOR prevention (403 Forbidden)
- Candidate-safe response sanitization (zero leakage of confidential keys)
- All supported answer types validation and submission
- Invalid answer payloads handling
- Question navigation with and without backtracking
- Explicit question skip behavior
- Server-authoritative deadline expiration (400 Bad Request)
- Successful submission and terminal attempt protection (409 Conflict)
- Exception-to-HTTP mapping and database lock timeout (503 Service Unavailable)
- Explicit testing of POST /api/v1/assessments/attempts/{attempt_id}/navigate/
"""
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import sys
from unittest.mock import patch
import uuid

# Ensure backend directory is in sys.path
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.arena.models import Question, QuestionVersion
from apps.assessments.models import (
    ActiveAssessmentReservation,
    Assessment,
    AssessmentAttempt,
    AssessmentVersion,
    AssessmentVersionQuestion,
)
from apps.assessments.services import (
    AssessmentAttemptService,
    AssessmentCompositionService,
    LockTimeoutError,
)
from apps.skills.models import Competency, Domain, Subdomain

User = get_user_model()


# ==============================================================================
# Pytest Fixtures
# ==============================================================================

@pytest.fixture
def author_user(db):
    """Staff author permitted to create assessments and questions."""
    return User.objects.create_user(
        email='author_api@zentiq.com',
        password='TestPassword123!',
        is_staff=True,
    )


@pytest.fixture
def candidate_user(db):
    """Primary candidate user."""
    return User.objects.create_user(
        email='candidate_api1@zentiq.com',
        password='TestPassword123!',
    )


@pytest.fixture
def second_candidate(db):
    """Secondary candidate user for IDOR testing."""
    return User.objects.create_user(
        email='candidate_api2@zentiq.com',
        password='TestPassword123!',
    )


@pytest.fixture
def competency(db):
    """Standard competency for question association."""
    domain = Domain.objects.create(
        slug='api-test-domain',
        name='API Domain',
        category='TECHNICAL',
        description='API Test Domain',
        display_order=1,
    )
    subdomain = Subdomain.objects.create(
        domain=domain,
        slug='api-test-subdomain',
        name='API Subdomain',
        display_order=1,
    )
    return Competency.objects.create(
        subdomain=subdomain,
        code='COMP-API-01',
        name='API Design Competency',
        description='API testing skills',
        bloom_level='APPLY',
    )


@pytest.fixture
def standard_assessment(db, author_user, competency):
    """
    Published assessment with 3 pinned questions and backtracking ALLOWED.
    Duration: 1800 seconds (30 mins).
    """
    # 1. Single Choice
    q1 = Question.objects.create(code='QST-API-001', created_by=author_user)
    qv1 = QuestionVersion.objects.create(
        question=q1,
        version_number=1,
        status='DRAFT',
        title='Single Choice Question',
        prompt='Select the correct database isolation level.',
        question_type='SINGLE_CHOICE',
        primary_competency=competency,
        time_limit_seconds=60,
        content_payload={
            'options': [
                {'id': 'opt_read_committed', 'text': 'Read Committed'},
                {'id': 'opt_read_uncommitted', 'text': 'Read Uncommitted'},
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

    # 2. True / False
    q2 = Question.objects.create(code='QST-API-002', created_by=author_user)
    qv2 = QuestionVersion.objects.create(
        question=q2,
        version_number=1,
        status='DRAFT',
        title='True False Question',
        prompt='Optimistic locking uses database row locks.',
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

    # 3. Numerical
    q3 = Question.objects.create(code='QST-API-003', created_by=author_user)
    qv3 = QuestionVersion.objects.create(
        question=q3,
        version_number=1,
        status='DRAFT',
        title='Numerical Question',
        prompt='How many ACID properties are there?',
        question_type='NUMERICAL',
        primary_competency=competency,
        time_limit_seconds=30,
        content_payload={},
        created_by=author_user,
    )
    qv3.status = 'IN_REVIEW'
    qv3.save()
    qv3.status = 'PUBLISHED'
    qv3.save()
    q3.active_version = qv3
    q3.save()

    asm = AssessmentCompositionService.create_assessment(
        code='ASM-STD-001',
        title='Standard Assessment',
        description='Assessment with backtracking enabled.',
        user=author_user,
    )
    ver = AssessmentCompositionService.create_draft_version(
        asm.id,
        title='Standard v1.0',
        time_limit_seconds=1800,
        allow_backtracking=True,
        user=author_user,
    )
    AssessmentCompositionService.add_question_to_version(ver.id, qv1.id, weight=Decimal('1.00'), user=author_user)
    AssessmentCompositionService.add_question_to_version(ver.id, qv2.id, weight=Decimal('1.00'), user=author_user)
    AssessmentCompositionService.add_question_to_version(ver.id, qv3.id, weight=Decimal('1.00'), user=author_user)
    AssessmentCompositionService.publish_version(ver.id, user=author_user)
    asm.refresh_from_db()
    return asm, ver


@pytest.fixture
def forward_only_assessment(db, author_user, competency):
    """
    Published assessment with 3 pinned questions and backtracking DISABLED.
    Duration: 1800 seconds.
    """
    q1 = Question.objects.create(code='QST-FWD-001', created_by=author_user)
    qv1 = QuestionVersion.objects.create(
        question=q1,
        version_number=1,
        status='DRAFT',
        title='Forward Q1',
        prompt='Question 1 in forward only test.',
        question_type='SINGLE_CHOICE',
        primary_competency=competency,
        content_payload={'options': [{'id': 'opt1', 'text': 'A'}, {'id': 'opt2', 'text': 'B'}]},
        created_by=author_user,
    )
    qv1.status = 'IN_REVIEW'
    qv1.save()
    qv1.status = 'PUBLISHED'
    qv1.save()
    q1.active_version = qv1
    q1.save()

    q2 = Question.objects.create(code='QST-FWD-002', created_by=author_user)
    qv2 = QuestionVersion.objects.create(
        question=q2,
        version_number=1,
        status='DRAFT',
        title='Forward Q2',
        prompt='Question 2 in forward only test.',
        question_type='SINGLE_CHOICE',
        primary_competency=competency,
        content_payload={'options': [{'id': 'opt1', 'text': 'C'}, {'id': 'opt2', 'text': 'D'}]},
        created_by=author_user,
    )
    qv2.status = 'IN_REVIEW'
    qv2.save()
    qv2.status = 'PUBLISHED'
    qv2.save()
    q2.active_version = qv2
    q2.save()

    q3 = Question.objects.create(code='QST-FWD-003', created_by=author_user)
    qv3 = QuestionVersion.objects.create(
        question=q3,
        version_number=1,
        status='DRAFT',
        title='Forward Q3',
        prompt='Question 3 in forward only test.',
        question_type='SHORT_TEXT',
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

    asm = AssessmentCompositionService.create_assessment(
        code='ASM-FWD-001',
        title='Forward Only Assessment',
        description='Assessment with backtracking disabled.',
        user=author_user,
    )
    ver = AssessmentCompositionService.create_draft_version(
        asm.id,
        title='Forward v1.0',
        time_limit_seconds=1800,
        allow_backtracking=False,
        user=author_user,
    )
    AssessmentCompositionService.add_question_to_version(ver.id, qv1.id, weight=Decimal('1.00'), user=author_user)
    AssessmentCompositionService.add_question_to_version(ver.id, qv2.id, weight=Decimal('1.00'), user=author_user)
    AssessmentCompositionService.add_question_to_version(ver.id, qv3.id, weight=Decimal('1.00'), user=author_user)
    AssessmentCompositionService.publish_version(ver.id, user=author_user)
    asm.refresh_from_db()
    return asm, ver


@pytest.fixture
def multi_type_assessment(db, author_user, competency):
    """
    Assessment containing all 6 supported question types to test validation and execution.
    """
    def _create_published_qv(code, q_type, title, prompt, payload):
        q = Question.objects.create(code=code, created_by=author_user)
        qv = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            status='DRAFT',
            title=title,
            prompt=prompt,
            question_type=q_type,
            primary_competency=competency,
            content_payload=payload,
            created_by=author_user,
        )
        qv.status = 'IN_REVIEW'
        qv.save()
        qv.status = 'PUBLISHED'
        qv.save()
        q.active_version = qv
        q.save()
        return qv

    # 1. SINGLE_CHOICE
    qv1 = _create_published_qv(
        'QST-ALL-001', 'SINGLE_CHOICE', 'Single Choice', 'Pick the correct answer.',
        {'options': [{'id': 'c1', 'text': 'Option A'}, {'id': 'c2', 'text': 'Option B'}]}
    )
    # 2. MULTIPLE_CHOICE
    qv2 = _create_published_qv(
        'QST-ALL-002', 'MULTIPLE_CHOICE', 'Multiple Choice', 'Select all prime numbers.',
        {'options': [{'id': 'm1', 'text': '2'}, {'id': 'm2', 'text': '3'}, {'id': 'm3', 'text': '4'}]}
    )
    # 3. TRUE_FALSE
    qv3 = _create_published_qv(
        'QST-ALL-003', 'TRUE_FALSE', 'True False', 'Is Python dynamically typed?',
        {'options': [{'id': 'true', 'text': 'True'}, {'id': 'false', 'text': 'False'}]}
    )
    # 4. NUMERICAL
    qv4 = _create_published_qv(
        'QST-ALL-004', 'NUMERICAL', 'Numerical', 'What is 20 + 22?', {}
    )
    # 5. SHORT_TEXT
    qv5 = _create_published_qv(
        'QST-ALL-005', 'SHORT_TEXT', 'Short Text', 'Enter the primary protocol of the web.', {}
    )
    # 6. CODE_OUTPUT
    qv6 = _create_published_qv(
        'QST-ALL-006', 'CODE_OUTPUT', 'Code Output', 'What does print("hello") output?', {}
    )

    asm = AssessmentCompositionService.create_assessment(
        code='ASM-ALL-001',
        title='All Types Assessment',
        description='Assessment with all question types.',
        user=author_user,
    )
    ver = AssessmentCompositionService.create_draft_version(
        asm.id,
        title='All Types v1.0',
        time_limit_seconds=3600,
        allow_backtracking=True,
        user=author_user,
    )
    for qv in [qv1, qv2, qv3, qv4, qv5, qv6]:
        AssessmentCompositionService.add_question_to_version(ver.id, qv.id, weight=Decimal('1.00'), user=author_user)
    AssessmentCompositionService.publish_version(ver.id, user=author_user)
    asm.refresh_from_db()
    return asm, ver


@pytest.fixture
def untimed_assessment(db, author_user, competency):
    """
    Published assessment with time_limit_seconds=None (untimed).
    Has 3 pinned questions and allow_backtracking=True.
    """
    q1 = Question.objects.create(code='QST-UNT-001', created_by=author_user)
    qv1 = QuestionVersion.objects.create(
        question=q1,
        version_number=1,
        status='DRAFT',
        title='Untimed Q1',
        prompt='Select untimed option.',
        question_type='SINGLE_CHOICE',
        primary_competency=competency,
        content_payload={'options': [{'id': 'opt1', 'text': 'A'}, {'id': 'opt2', 'text': 'B'}]},
        created_by=author_user,
    )
    qv1.status = 'IN_REVIEW'
    qv1.save()
    qv1.status = 'PUBLISHED'
    qv1.save()
    q1.active_version = qv1
    q1.save()

    q2 = Question.objects.create(code='QST-UNT-002', created_by=author_user)
    qv2 = QuestionVersion.objects.create(
        question=q2,
        version_number=1,
        status='DRAFT',
        title='Untimed Q2',
        prompt='Untimed question 2',
        question_type='TRUE_FALSE',
        primary_competency=competency,
        content_payload={'options': [{'id': 'true', 'text': 'True'}, {'id': 'false', 'text': 'False'}]},
        created_by=author_user,
    )
    qv2.status = 'IN_REVIEW'
    qv2.save()
    qv2.status = 'PUBLISHED'
    qv2.save()
    q2.active_version = qv2
    q2.save()

    q3 = Question.objects.create(code='QST-UNT-003', created_by=author_user)
    qv3 = QuestionVersion.objects.create(
        question=q3,
        version_number=1,
        status='DRAFT',
        title='Untimed Q3',
        prompt='Untimed question 3',
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

    asm = AssessmentCompositionService.create_assessment(
        code='ASM-UNT-001',
        title='Untimed Assessment',
        description='Untimed assessment series without deadlines.',
        user=author_user,
    )
    ver = AssessmentCompositionService.create_draft_version(
        asm.id,
        title='Untimed v1.0',
        time_limit_seconds=None,
        allow_backtracking=True,
        user=author_user,
    )
    AssessmentCompositionService.add_question_to_version(ver.id, qv1.id, weight=Decimal('1.00'), user=author_user)
    AssessmentCompositionService.add_question_to_version(ver.id, qv2.id, weight=Decimal('1.00'), user=author_user)
    AssessmentCompositionService.add_question_to_version(ver.id, qv3.id, weight=Decimal('1.00'), user=author_user)
    AssessmentCompositionService.publish_version(ver.id, user=author_user)
    asm.refresh_from_db()
    return asm, ver


# ==============================================================================
# 1. Authentication and Security Tests
# ==============================================================================

class TestAuthenticationAndSecurity:
    """Verifies authentication enforcement, CSRF behavior, and session handling."""

    def test_anonymous_access_denied_across_all_endpoints(self, db, standard_assessment):
        """All candidate assessment endpoints strictly require authentication."""
        asm, _ = standard_assessment
        client = APIClient()
        fake_uuid = uuid.uuid4()

        endpoints = [
            ('get', reverse('assessments:assessment-list'), {}),
            ('get', reverse('assessments:assessment-detail', kwargs={'assessment_id': asm.id}), {}),
            ('post', reverse('assessments:attempt-start', kwargs={'assessment_id': asm.id}), {'HTTP_IDEMPOTENCY_KEY': 'idem-anon'}),
            ('get', reverse('assessments:attempt-detail', kwargs={'attempt_id': fake_uuid}), {}),
            ('post', reverse('assessments:attempt-submit', kwargs={'attempt_id': fake_uuid}), {}),
            ('post', reverse('assessments:attempt-navigate', kwargs={'attempt_id': fake_uuid}), {'order_index': 1}),
            ('get', reverse('assessments:attempt-current-question', kwargs={'attempt_id': fake_uuid}), {}),
            ('get', reverse('assessments:attempt-question-detail', kwargs={'attempt_id': fake_uuid, 'order_index': 1}), {}),
            ('post', reverse('assessments:attempt-question-answer', kwargs={'attempt_id': fake_uuid, 'order_index': 1}), {'answer_payload': {'selected_option_id': 'opt1'}}),
            ('post', reverse('assessments:attempt-question-skip', kwargs={'attempt_id': fake_uuid, 'order_index': 1}), {}),
        ]

        for method, url, kwargs in endpoints:
            if method == 'get':
                resp = client.get(url, **kwargs)
            else:
                resp = client.post(url, kwargs, format='json')
            assert resp.status_code == status.HTTP_401_UNAUTHORIZED, f"Expected 401 for {url}, got {resp.status_code}"
            assert 'error' in resp.data
            assert resp.data['error']['code'] in ('not_authenticated', 'authentication_failed')

    def test_inactive_user_rejected(self, db, standard_assessment, candidate_user):
        """Inactive candidates are barred from assessment endpoints."""
        asm, _ = standard_assessment
        candidate_user.is_active = False
        candidate_user.save()

        client = APIClient()
        client.force_login(candidate_user)

        resp = client.get(reverse('assessments:assessment-list'))
        assert resp.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_csrf_protection_with_session_cookies(self, db, standard_assessment, candidate_user):
        """Mutating POST endpoints enforce CSRF when accessed via standard session cookie."""
        asm, _ = standard_assessment
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(candidate_user)

        # 1. Mutating POST without CSRF token fails with 403
        start_url = reverse('assessments:attempt-start', kwargs={'assessment_id': asm.id})
        resp_no_csrf = client.post(start_url, {}, format='json', HTTP_IDEMPOTENCY_KEY='idem-csrf-test')
        assert resp_no_csrf.status_code == status.HTTP_403_FORBIDDEN

        # 2. Mutating POST with valid CSRF token succeeds
        csrf_url = reverse('accounts:auth-csrf')
        csrf_resp = client.get(csrf_url)
        csrf_token = csrf_resp.cookies['csrftoken'].value

        resp_with_csrf = client.post(
            start_url,
            {},
            format='json',
            HTTP_IDEMPOTENCY_KEY='idem-csrf-test',
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        assert resp_with_csrf.status_code == status.HTTP_201_CREATED


# ==============================================================================
# 2. Assessment Catalog Tests
# ==============================================================================

class TestAssessmentCatalogAPI:
    """Verifies catalog listing, filtering of deprecated assessments, and detail view."""

    def test_catalog_listing_and_deprecated_exclusion(self, db, author_user, candidate_user, standard_assessment):
        asm, ver = standard_assessment

        # Create a second assessment that is deprecated
        asm_dep = AssessmentCompositionService.create_assessment(
            code='ASM-DEP-001',
            title='Deprecated Assessment',
            user=author_user,
        )
        ver_dep = AssessmentCompositionService.create_draft_version(asm_dep.id, title='Dep v1', user=author_user)
        # Add question and publish
        qv = QuestionVersion.objects.filter(status='PUBLISHED').first()
        AssessmentCompositionService.add_question_to_version(ver_dep.id, qv.id, user=author_user)
        AssessmentCompositionService.publish_version(ver_dep.id, user=author_user)
        AssessmentCompositionService.deprecate_assessment(asm_dep.id, user=author_user)

        # Create a third assessment that has no published version (draft only)
        asm_draft = AssessmentCompositionService.create_assessment(
            code='ASM-DRF-001',
            title='Draft Only Assessment',
            user=author_user,
        )

        client = APIClient()
        client.force_login(candidate_user)

        resp = client.get(reverse('assessments:assessment-list'))
        assert resp.status_code == status.HTTP_200_OK
        data = resp.data
        codes = [item['code'] for item in data]

        assert asm.code in codes
        assert asm_dep.code not in codes
        assert asm_draft.code not in codes

        # Verify safe serializer fields
        std_item = next(item for item in data if item['code'] == asm.code)
        assert 'id' in std_item
        assert std_item['title'] == asm.title
        assert std_item['time_limit_seconds'] == 1800
        assert std_item['allow_backtracking'] is True
        assert std_item['question_count'] == 3

    def test_catalog_detail_success(self, db, candidate_user, standard_assessment):
        asm, _ = standard_assessment
        client = APIClient()
        client.force_login(candidate_user)

        url = reverse('assessments:assessment-detail', kwargs={'assessment_id': asm.id})
        resp = client.get(url)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data['code'] == asm.code
        assert resp.data['question_count'] == 3

    def test_catalog_detail_not_found(self, db, candidate_user):
        client = APIClient()
        client.force_login(candidate_user)

        url = reverse('assessments:assessment-detail', kwargs={'assessment_id': uuid.uuid4()})
        resp = client.get(url)
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert resp.data['error']['code'] == 'assessment_not_found'

    def test_catalog_detail_deprecated_returns_409(self, db, author_user, candidate_user):
        """Requesting detail of a deprecated assessment returns 409 Conflict."""
        asm_dep = AssessmentCompositionService.create_assessment(
            code='ASM-DEP-002',
            title='Deprecated Assessment 2',
            user=author_user,
        )
        AssessmentCompositionService.deprecate_assessment(asm_dep.id, user=author_user)

        client = APIClient()
        client.force_login(candidate_user)

        url = reverse('assessments:assessment-detail', kwargs={'assessment_id': asm_dep.id})
        resp = client.get(url)
        assert resp.status_code == status.HTTP_409_CONFLICT
        assert resp.data['error']['code'] == 'assessment_deprecated'

    def test_catalog_detail_no_active_version_returns_409(self, db, author_user, candidate_user):
        """Requesting detail of an assessment without an active published version returns 409 Conflict."""
        asm_no_ver = AssessmentCompositionService.create_assessment(
            code='ASM-NOVER-001',
            title='Assessment No Active Version',
            user=author_user,
        )

        client = APIClient()
        client.force_login(candidate_user)

        url = reverse('assessments:assessment-detail', kwargs={'assessment_id': asm_no_ver.id})
        resp = client.get(url)
        assert resp.status_code == status.HTTP_409_CONFLICT
        assert resp.data['error']['code'] == 'no_active_version'


# ==============================================================================
# 3. Attempt Start and Idempotency Tests
# ==============================================================================

class TestAttemptStartAndIdempotency:
    """Verifies mandatory Idempotency-Key header, start, replay, and active reservation conflict."""

    def test_missing_idempotency_key_header_rejected(self, db, candidate_user, standard_assessment):
        asm, _ = standard_assessment
        client = APIClient()
        client.force_login(candidate_user)

        url = reverse('assessments:attempt-start', kwargs={'assessment_id': asm.id})
        resp = client.post(url, {}, format='json')
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data['error']['code'] == 'validation_error'
        assert 'idempotency_key' in resp.data['error']['details']

    def test_empty_or_whitespace_idempotency_key_rejected(self, db, candidate_user, standard_assessment):
        asm, _ = standard_assessment
        client = APIClient()
        client.force_login(candidate_user)

        url = reverse('assessments:attempt-start', kwargs={'assessment_id': asm.id})
        resp = client.post(url, {}, format='json', HTTP_IDEMPOTENCY_KEY='   ')
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data['error']['code'] == 'validation_error'

    def test_oversized_idempotency_key_rejected(self, db, candidate_user, standard_assessment):
        asm, _ = standard_assessment
        client = APIClient()
        client.force_login(candidate_user)

        url = reverse('assessments:attempt-start', kwargs={'assessment_id': asm.id})
        resp = client.post(url, {}, format='json', HTTP_IDEMPOTENCY_KEY='x' * 65)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data['error']['code'] == 'validation_error'

    def test_json_body_idempotency_key_not_accepted(self, db, candidate_user, standard_assessment):
        """Idempotency-Key in JSON body must NOT be accepted as a fallback when header is missing."""
        asm, _ = standard_assessment
        client = APIClient()
        client.force_login(candidate_user)

        url = reverse('assessments:attempt-start', kwargs={'assessment_id': asm.id})
        resp = client.post(url, {'idempotency_key': 'body-key-attempt'}, format='json')
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data['error']['code'] == 'validation_error'

    def test_attempt_start_success_201_and_idempotent_replay_200(self, db, candidate_user, standard_assessment):
        asm, _ = standard_assessment
        client = APIClient()
        client.force_login(candidate_user)

        url = reverse('assessments:attempt-start', kwargs={'assessment_id': asm.id})
        key = 'unique-idem-key-001'

        # 1. First invocation creates new attempt (201 Created)
        r1 = client.post(url, {}, format='json', HTTP_IDEMPOTENCY_KEY=key)
        assert r1.status_code == status.HTTP_201_CREATED
        attempt_id = r1.data['attempt_id']
        assert r1.data['status'] == 'IN_PROGRESS'
        assert r1.data['attempt_number'] == 1
        assert r1.data['question_count'] == 3
        assert r1.data['answer_count'] == 0
        assert r1.data['current_order_index'] == 1

        # 2. Replay with exact same key returns existing attempt (200 OK)
        r2 = client.post(url, {}, format='json', HTTP_IDEMPOTENCY_KEY=key)
        assert r2.status_code == status.HTTP_200_OK
        assert r2.data['attempt_id'] == attempt_id

    def test_active_attempt_conflict_409(self, db, candidate_user, standard_assessment):
        """Starting a new attempt with a different key while one is active returns 409 Conflict."""
        asm, _ = standard_assessment
        client = APIClient()
        client.force_login(candidate_user)

        url = reverse('assessments:attempt-start', kwargs={'assessment_id': asm.id})

        # Start first attempt
        r1 = client.post(url, {}, format='json', HTTP_IDEMPOTENCY_KEY='key-first')
        assert r1.status_code == status.HTTP_201_CREATED

        # Attempt to start second attempt with a DIFFERENT key
        r2 = client.post(url, {}, format='json', HTTP_IDEMPOTENCY_KEY='key-second-different')
        assert r2.status_code == status.HTTP_409_CONFLICT
        assert r2.data['error']['code'] == 'active_attempt_exists'

    def test_attempt_start_deprecated_returns_409(self, db, author_user, candidate_user):
        """Starting an attempt on a deprecated assessment returns 409 Conflict."""
        asm_dep = AssessmentCompositionService.create_assessment(
            code='ASM-DEP-003',
            title='Deprecated Assessment 3',
            user=author_user,
        )
        AssessmentCompositionService.deprecate_assessment(asm_dep.id, user=author_user)

        client = APIClient()
        client.force_login(candidate_user)

        url = reverse('assessments:attempt-start', kwargs={'assessment_id': asm_dep.id})
        resp = client.post(url, {}, format='json', HTTP_IDEMPOTENCY_KEY='idem-start-dep')
        assert resp.status_code == status.HTTP_409_CONFLICT
        assert resp.data['error']['code'] == 'assessment_deprecated'

    def test_attempt_start_no_active_version_returns_409(self, db, author_user, candidate_user):
        """Starting an attempt on an assessment without an active published version returns 409 Conflict."""
        asm_no_ver = AssessmentCompositionService.create_assessment(
            code='ASM-NOVER-002',
            title='Assessment No Active Version 2',
            user=author_user,
        )

        client = APIClient()
        client.force_login(candidate_user)

        url = reverse('assessments:attempt-start', kwargs={'assessment_id': asm_no_ver.id})
        resp = client.post(url, {}, format='json', HTTP_IDEMPOTENCY_KEY='idem-start-nover')
        assert resp.status_code == status.HTTP_409_CONFLICT
        assert resp.data['error']['code'] == 'no_active_version'


# ==============================================================================
# 4. Attempt Ownership and IDOR Prevention Tests
# ==============================================================================

class TestAttemptOwnershipAndIDOR:
    """Verifies candidate authorization and protection against IDOR vulnerabilities."""

    def test_idor_protection_across_all_candidate_attempt_endpoints(
        self, db, candidate_user, second_candidate, standard_assessment
    ):
        asm, _ = standard_assessment

        # Start attempt as Candidate 1
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='candidate1-attempt-key',
        )

        # Log in as Candidate 2
        client = APIClient()
        client.force_login(second_candidate)

        # Candidate 2 attempts to access Candidate 1's attempt endpoints
        endpoints = [
            ('get', reverse('assessments:attempt-detail', kwargs={'attempt_id': attempt.id}), {}),
            ('post', reverse('assessments:attempt-submit', kwargs={'attempt_id': attempt.id}), {}),
            ('post', reverse('assessments:attempt-navigate', kwargs={'attempt_id': attempt.id}), {'order_index': 2}),
            ('get', reverse('assessments:attempt-current-question', kwargs={'attempt_id': attempt.id}), {}),
            ('get', reverse('assessments:attempt-question-detail', kwargs={'attempt_id': attempt.id, 'order_index': 1}), {}),
            ('post', reverse('assessments:attempt-question-answer', kwargs={'attempt_id': attempt.id, 'order_index': 1}), {'answer_payload': {'selected_option_id': 'opt_read_committed'}}),
            ('post', reverse('assessments:attempt-question-skip', kwargs={'attempt_id': attempt.id, 'order_index': 1}), {}),
        ]

        for method, url, payload in endpoints:
            if method == 'get':
                resp = client.get(url)
            else:
                resp = client.post(url, payload, format='json')
            assert resp.status_code == status.HTTP_403_FORBIDDEN, f"IDOR vulnerability on {url}: status {resp.status_code}"
            assert resp.data['error']['code'] == 'permission_denied'

    def test_nonexistent_attempt_returns_404(self, db, candidate_user):
        client = APIClient()
        client.force_login(candidate_user)
        non_existent = uuid.uuid4()

        url = reverse('assessments:attempt-detail', kwargs={'attempt_id': non_existent})
        resp = client.get(url)
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert resp.data['error']['code'] == 'attempt_not_found'


# ==============================================================================
# 5. Candidate-Safe Response Sanitization Tests
# ==============================================================================

class TestCandidateResponseSanitization:
    """Verifies that no confidential evaluation keys leak into candidate responses."""

    def test_candidate_question_dto_strips_confidential_keys(self, db, candidate_user, multi_type_assessment):
        asm, _ = multi_type_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='sanitize-test-key',
        )

        client = APIClient()
        client.force_login(candidate_user)

        # Check current-question endpoint
        resp = client.get(reverse('assessments:attempt-current-question', kwargs={'attempt_id': attempt.id}))
        assert resp.status_code == status.HTTP_200_OK

        forbidden = [
            'correct_answer',
            'correct_payload',
            'answer_key',
            'solution',
            'scoring_rubric',
            'rubric',
            'explanation',
            'is_correct',
            'competency',
            'weight',
        ]

        # Check top level
        for key in forbidden:
            assert key not in resp.data

        # Check content_payload
        payload = resp.data.get('content_payload', {})
        for key in forbidden:
            assert key not in payload

        # Check options array
        for opt in payload.get('options', []):
            for key in forbidden:
                assert key not in opt


# ==============================================================================
# 6. Answer Submission Across All Types Tests
# ==============================================================================

class TestAnswerSubmissionAllTypes:
    """Verifies answer validation and submission across all supported question types."""

    def test_all_question_types_submission(self, db, candidate_user, multi_type_assessment):
        asm, _ = multi_type_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='answers-all-types-key',
        )

        client = APIClient()
        client.force_login(candidate_user)

        base_url = f"/api/v1/assessments/attempts/{attempt.id}/questions"

        # 1. SINGLE_CHOICE (Q1)
        r1 = client.post(f"{base_url}/1/answer/", {'answer_payload': {'selected_option_id': 'c1'}}, format='json')
        assert r1.status_code == status.HTTP_200_OK
        assert r1.data['is_answered'] is True
        assert r1.data['current_answer'] == {'selected_option_id': 'c1'}

        # 2. MULTIPLE_CHOICE (Q2)
        r2 = client.post(f"{base_url}/2/answer/", {'answer_payload': {'selected_option_ids': ['m1', 'm2']}}, format='json')
        assert r2.status_code == status.HTTP_200_OK
        assert r2.data['is_answered'] is True
        assert r2.data['current_answer'] == {'selected_option_ids': ['m1', 'm2']}

        # 3. TRUE_FALSE (Q3)
        r3 = client.post(f"{base_url}/3/answer/", {'answer_payload': {'selected_value': True}}, format='json')
        assert r3.status_code == status.HTTP_200_OK
        assert r3.data['is_answered'] is True
        assert r3.data['current_answer'] == {'selected_value': True}

        # 4. NUMERICAL (Q4)
        r4 = client.post(f"{base_url}/4/answer/", {'answer_payload': {'value': 42}}, format='json')
        assert r4.status_code == status.HTTP_200_OK
        assert r4.data['is_answered'] is True
        assert r4.data['current_answer'] == {'value': 42}

        # 5. SHORT_TEXT (Q5)
        r5 = client.post(f"{base_url}/5/answer/", {'answer_payload': {'text': 'HTTP'}}, format='json')
        assert r5.status_code == status.HTTP_200_OK
        assert r5.data['is_answered'] is True
        assert r5.data['current_answer'] == {'text': 'HTTP'}

        # 6. CODE_OUTPUT (Q6)
        r6 = client.post(f"{base_url}/6/answer/", {'answer_payload': {'output': 'hello'}}, format='json')
        assert r6.status_code == status.HTTP_200_OK
        assert r6.data['is_answered'] is True
        assert r6.data['current_answer'] == {'output': 'hello'}

        # Verify answer count updated to 6
        detail_resp = client.get(reverse('assessments:attempt-detail', kwargs={'attempt_id': attempt.id}))
        assert detail_resp.data['answer_count'] == 6

    def test_invalid_answer_payloads_rejected(self, db, candidate_user, multi_type_assessment):
        asm, _ = multi_type_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='invalid-answers-key',
        )

        client = APIClient()
        client.force_login(candidate_user)
        base_url = f"/api/v1/assessments/attempts/{attempt.id}/questions"

        # SINGLE_CHOICE with non-existent option
        r_sc = client.post(f"{base_url}/1/answer/", {'answer_payload': {'selected_option_id': 'non_existent_opt'}}, format='json')
        assert r_sc.status_code == status.HTTP_400_BAD_REQUEST
        assert r_sc.data['error']['code'] == 'invalid_answer_payload'

        # MULTIPLE_CHOICE with empty list
        r_mc = client.post(f"{base_url}/2/answer/", {'answer_payload': {'selected_option_ids': []}}, format='json')
        assert r_mc.status_code == status.HTTP_400_BAD_REQUEST
        assert r_mc.data['error']['code'] == 'invalid_answer_payload'

        # NUMERICAL with non-numeric value
        r_num = client.post(f"{base_url}/4/answer/", {'answer_payload': {'value': 'not-a-number'}}, format='json')
        assert r_num.status_code == status.HTTP_400_BAD_REQUEST
        assert r_num.data['error']['code'] == 'invalid_answer_payload'

        # SHORT_TEXT with blank text
        r_st = client.post(f"{base_url}/5/answer/", {'answer_payload': {'text': '   '}}, format='json')
        assert r_st.status_code == status.HTTP_400_BAD_REQUEST
        assert r_st.data['error']['code'] == 'invalid_answer_payload'

    def test_answer_submission_strictly_requires_wrapped_payload(self, db, candidate_user, standard_assessment):
        """API strictly requires {"answer_payload": {...}} and rejects direct or malformed payloads with 400."""
        asm, _ = standard_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='strictly-wrapped-payload-key',
        )

        client = APIClient()
        client.force_login(candidate_user)
        ans_url = f"/api/v1/assessments/attempts/{attempt.id}/questions/1/answer/"

        # 1. Valid wrapped payload succeeds
        r_wrapped = client.post(
            ans_url,
            {'answer_payload': {'selected_option_id': 'opt_read_committed'}},
            format='json',
        )
        assert r_wrapped.status_code == status.HTTP_200_OK
        assert r_wrapped.data['current_answer'] == {'selected_option_id': 'opt_read_committed'}

        # 2. Direct unwrapped payload at root is strictly rejected with 400 Bad Request
        r_direct = client.post(
            ans_url,
            {'selected_option_id': 'opt_read_uncommitted'},
            format='json',
        )
        assert r_direct.status_code == status.HTTP_400_BAD_REQUEST

        # 3. Missing answer_payload completely returns 400 Bad Request
        r_empty = client.post(ans_url, {}, format='json')
        assert r_empty.status_code == status.HTTP_400_BAD_REQUEST

        # 4. Non-dict answer_payload returns 400 Bad Request
        r_nondict = client.post(ans_url, {'answer_payload': 'string_instead_of_dict'}, format='json')
        assert r_nondict.status_code == status.HTTP_400_BAD_REQUEST

        # 5. Empty dictionary answer_payload returns 400 Bad Request
        r_emptydict = client.post(ans_url, {'answer_payload': {}}, format='json')
        assert r_emptydict.status_code == status.HTTP_400_BAD_REQUEST

    def test_out_of_bounds_answer_submission(self, db, candidate_user, standard_assessment):
        """Submitting an answer for a question index that does not exist returns 400."""
        asm, _ = standard_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='oob-answer-key',
        )

        client = APIClient()
        client.force_login(candidate_user)
        ans_url = f"/api/v1/assessments/attempts/{attempt.id}/questions/99/answer/"

        resp = client.post(ans_url, {'answer_payload': {'selected_option_id': 'opt_read_committed'}}, format='json')
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data['error']['code'] == 'invalid_navigation'

    def test_navigate_invalid_payload(self, db, candidate_user, standard_assessment):
        """POST /navigate/ with missing or non-integer order_index returns 400 Bad Request."""
        asm, _ = standard_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='nav-invalid-payload-key',
        )

        client = APIClient()
        client.force_login(candidate_user)
        nav_url = reverse('assessments:attempt-navigate', kwargs={'attempt_id': attempt.id})

        # Missing order_index
        r1 = client.post(nav_url, {}, format='json')
        assert r1.status_code == status.HTTP_400_BAD_REQUEST

        # Invalid non-integer order_index
        r2 = client.post(nav_url, {'order_index': 'invalid_string'}, format='json')
        assert r2.status_code == status.HTTP_400_BAD_REQUEST

    def test_answer_submission_forward_only_out_of_order_rejected(
        self, db, candidate_user, forward_only_assessment
    ):
        """When backtracking is disabled, answering a question other than current_order_index is barred."""
        asm, _ = forward_only_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='ans-fwd-only-key',
        )

        client = APIClient()
        client.force_login(candidate_user)

        # Attempt is on question 1. Answering question 2 should be rejected.
        ans_url = f"/api/v1/assessments/attempts/{attempt.id}/questions/2/answer/"
        resp = client.post(ans_url, {'answer_payload': {'selected_option_id': 'opt1'}}, format='json')
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data['error']['code'] == 'backtracking_not_allowed'


# ==============================================================================
# 7. Question Navigation and Backtracking Tests
# ==============================================================================

class TestQuestionNavigationAndBacktracking:
    """Verifies navigation with and without backtracking, question retrieval, and auto-advancement."""

    def test_navigation_endpoint_explicit_with_backtracking(self, db, candidate_user, standard_assessment):
        """Tests POST /api/v1/assessments/attempts/{attempt_id}/navigate/ explicitly."""
        asm, _ = standard_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='nav-explicit-key',
        )

        client = APIClient()
        client.force_login(candidate_user)

        nav_url = reverse('assessments:attempt-navigate', kwargs={'attempt_id': attempt.id})

        # Navigate forward to question 3
        r1 = client.post(nav_url, {'order_index': 3}, format='json')
        assert r1.status_code == status.HTTP_200_OK
        assert r1.data['order_index'] == 3
        assert r1.data['current_order_index'] == 3

        # Navigate backward to question 1 (backtracking permitted)
        r2 = client.post(nav_url, {'order_index': 1}, format='json')
        assert r2.status_code == status.HTTP_200_OK
        assert r2.data['order_index'] == 1
        assert r2.data['current_order_index'] == 1

        # Out-of-bounds navigation
        r_oob = client.post(nav_url, {'order_index': 10}, format='json')
        assert r_oob.status_code == status.HTTP_400_BAD_REQUEST
        assert r_oob.data['error']['code'] == 'invalid_navigation'

    def test_forward_only_navigation_restricts_backward_and_skipping(
        self, db, candidate_user, forward_only_assessment
    ):
        """When allow_backtracking=False, backward navigation and jumping ahead are barred."""
        asm, _ = forward_only_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='fwd-only-key',
        )

        client = APIClient()
        client.force_login(candidate_user)

        nav_url = reverse('assessments:attempt-navigate', kwargs={'attempt_id': attempt.id})

        # Jump ahead past order_index + 1 rejected
        r_jump = client.post(nav_url, {'order_index': 3}, format='json')
        assert r_jump.status_code == status.HTTP_400_BAD_REQUEST
        assert r_jump.data['error']['code'] == 'invalid_navigation'

        # Advance to question 2 permitted
        r_adv = client.post(nav_url, {'order_index': 2}, format='json')
        assert r_adv.status_code == status.HTTP_200_OK
        assert r_adv.data['current_order_index'] == 2

        # Backward navigation to question 1 barred
        r_back = client.post(nav_url, {'order_index': 1}, format='json')
        assert r_back.status_code == status.HTTP_400_BAD_REQUEST
        assert r_back.data['error']['code'] == 'backtracking_not_allowed'

        # Read-only GET on previous question also barred when backtracking disabled
        prev_q_url = reverse(
            'assessments:attempt-question-detail',
            kwargs={'attempt_id': attempt.id, 'order_index': 1},
        )
        r_prev = client.get(prev_q_url)
        assert r_prev.status_code == status.HTTP_400_BAD_REQUEST
        assert r_prev.data['error']['code'] == 'backtracking_not_allowed'

    def test_skip_question_and_auto_advancement(self, db, candidate_user, forward_only_assessment):
        """Skipping advances active question index when forward-only."""
        asm, _ = forward_only_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='skip-adv-key',
        )

        client = APIClient()
        client.force_login(candidate_user)

        skip_url = f"/api/v1/assessments/attempts/{attempt.id}/questions/1/skip/"
        resp = client.post(skip_url, {}, format='json')
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data['is_answered'] is False
        assert resp.data['current_order_index'] == 2


# ==============================================================================
# 8. Deadline Expiration and Lifecycle Tests
# ==============================================================================

class TestDeadlineExpirationAndLifecycle:
    """Verifies server-authoritative deadlines, successful submit, and terminal attempt protection."""

    def test_deadline_expiration_returns_410_and_durably_expires(
        self, db, candidate_user, standard_assessment
    ):
        """Expired attempts return 410 Gone and are durably transitioned to EXPIRED in the database."""
        asm, _ = standard_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='deadline-test-key',
        )

        # Force attempt deadline into the past
        past_time = timezone.now() - timedelta(minutes=10)
        AssessmentAttempt.objects.filter(pk=attempt.id).update(deadline=past_time)

        client = APIClient()
        client.force_login(candidate_user)

        # 1. Answering past deadline fails with 410 Gone
        ans_url = f"/api/v1/assessments/attempts/{attempt.id}/questions/1/answer/"
        r_ans = client.post(
            ans_url,
            {'answer_payload': {'selected_option_id': 'opt_read_committed'}},
            format='json',
        )
        assert r_ans.status_code == status.HTTP_410_GONE
        assert r_ans.data['error']['code'] == 'attempt_expired'

        # Verify attempt was durably transitioned to EXPIRED in the database
        attempt.refresh_from_db()
        assert attempt.status == 'EXPIRED'
        assert attempt.completed_at is not None
        assert not ActiveAssessmentReservation.objects.filter(attempt_id=attempt.id).exists()

        # 2. Subsequent navigation on now-terminal attempt returns 409 Conflict
        nav_url = reverse('assessments:attempt-navigate', kwargs={'attempt_id': attempt.id})
        r_nav = client.post(nav_url, {'order_index': 2}, format='json')
        assert r_nav.status_code == status.HTTP_409_CONFLICT
        assert r_nav.data['error']['code'] == 'attempt_terminal'

    def test_submit_past_deadline_returns_410_and_durably_expires(
        self, db, candidate_user, standard_assessment
    ):
        """Submitting an attempt whose deadline has elapsed returns 410 Gone and transitions to EXPIRED."""
        asm, _ = standard_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='submit-expired-test-key',
        )

        # Force deadline into the past
        past_time = timezone.now() - timedelta(minutes=5)
        AssessmentAttempt.objects.filter(pk=attempt.id).update(deadline=past_time)

        client = APIClient()
        client.force_login(candidate_user)

        submit_url = reverse('assessments:attempt-submit', kwargs={'attempt_id': attempt.id})
        r_sub = client.post(submit_url, {}, format='json')
        assert r_sub.status_code == status.HTTP_410_GONE
        assert r_sub.data['error']['code'] == 'attempt_expired'

        # Verify attempt was durably transitioned to EXPIRED in DB
        attempt.refresh_from_db()
        assert attempt.status == 'EXPIRED'
        assert attempt.completed_at is not None
        assert not ActiveAssessmentReservation.objects.filter(attempt_id=attempt.id).exists()

    def test_successful_submission_and_terminal_protection(self, db, candidate_user, standard_assessment):
        asm, _ = standard_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='submit-test-key',
        )

        client = APIClient()
        client.force_login(candidate_user)

        submit_url = reverse('assessments:attempt-submit', kwargs={'attempt_id': attempt.id})

        # 1. Submit attempt
        r_sub = client.post(submit_url, {}, format='json')
        assert r_sub.status_code == status.HTTP_200_OK
        assert r_sub.data['status'] == 'SUBMITTED'
        assert r_sub.data['completed_at'] is not None

        # Verify active reservation was cleaned up
        assert not ActiveAssessmentReservation.objects.filter(attempt_id=attempt.id).exists()

        # 2. Submitting again returns 409 Conflict
        r_sub2 = client.post(submit_url, {}, format='json')
        assert r_sub2.status_code == status.HTTP_409_CONFLICT
        assert r_sub2.data['error']['code'] == 'attempt_terminal'

        # 3. Answering submitted attempt returns 409 Conflict
        ans_url = f"/api/v1/assessments/attempts/{attempt.id}/questions/1/answer/"
        r_ans = client.post(
            ans_url,
            {'answer_payload': {'selected_option_id': 'opt_read_committed'}},
            format='json',
        )
        assert r_ans.status_code == status.HTTP_409_CONFLICT
        assert r_ans.data['error']['code'] == 'attempt_terminal'


# ==============================================================================
# 9. Untimed Assessment Tests
# ==============================================================================

class TestUntimedAssessments:
    """Verifies attempt lifecycle, navigation, answers, and submission for untimed assessments."""

    def test_untimed_attempt_creation_has_no_artificial_deadline(self, db, candidate_user, untimed_assessment):
        asm, _ = untimed_assessment
        client = APIClient()
        client.force_login(candidate_user)

        url = reverse('assessments:attempt-start', kwargs={'assessment_id': asm.id})
        resp = client.post(url, {}, format='json', HTTP_IDEMPOTENCY_KEY='untimed-start-001')
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data['deadline'] is None
        assert resp.data['time_limit_seconds'] is None

        # Verify in DB
        attempt = AssessmentAttempt.objects.get(pk=resp.data['attempt_id'])
        assert attempt.deadline is None
        assert attempt.time_limit_seconds is None

    def test_untimed_attempt_retrieval_and_question_access(self, db, candidate_user, untimed_assessment):
        asm, _ = untimed_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='untimed-retrieve-key',
        )

        client = APIClient()
        client.force_login(candidate_user)

        # 1. Retrieve attempt summary
        detail_url = reverse('assessments:attempt-detail', kwargs={'attempt_id': attempt.id})
        r_det = client.get(detail_url)
        assert r_det.status_code == status.HTTP_200_OK
        assert r_det.data['status'] == 'IN_PROGRESS'
        assert r_det.data['deadline'] is None
        assert r_det.data['time_limit_seconds'] is None

        # 2. Retrieve current question
        curr_url = reverse('assessments:attempt-current-question', kwargs={'attempt_id': attempt.id})
        r_curr = client.get(curr_url)
        assert r_curr.status_code == status.HTTP_200_OK
        assert r_curr.data['deadline'] is None
        assert r_curr.data['time_remaining_seconds'] is None

    def test_untimed_attempt_navigation_and_skip(self, db, candidate_user, untimed_assessment):
        asm, _ = untimed_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='untimed-nav-key',
        )

        client = APIClient()
        client.force_login(candidate_user)

        # 1. Navigate to question 2
        nav_url = reverse('assessments:attempt-navigate', kwargs={'attempt_id': attempt.id})
        r_nav = client.post(nav_url, {'order_index': 2}, format='json')
        assert r_nav.status_code == status.HTTP_200_OK
        assert r_nav.data['current_order_index'] == 2
        assert r_nav.data['deadline'] is None

        # 2. Skip question 2
        skip_url = f"/api/v1/assessments/attempts/{attempt.id}/questions/2/skip/"
        r_skip = client.post(skip_url, {}, format='json')
        assert r_skip.status_code == status.HTTP_200_OK
        assert r_skip.data['is_answered'] is False

    def test_untimed_attempt_answering_and_final_submission(self, db, candidate_user, untimed_assessment):
        asm, _ = untimed_assessment
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='untimed-answer-submit-key',
        )

        client = APIClient()
        client.force_login(candidate_user)

        # 1. Answer question 1
        ans_url = f"/api/v1/assessments/attempts/{attempt.id}/questions/1/answer/"
        r_ans = client.post(
            ans_url,
            {'answer_payload': {'selected_option_id': 'opt1'}},
            format='json',
        )
        assert r_ans.status_code == status.HTTP_200_OK
        assert r_ans.data['is_answered'] is True
        assert r_ans.data['deadline'] is None

        # 2. Final submission
        sub_url = reverse('assessments:attempt-submit', kwargs={'attempt_id': attempt.id})
        r_sub = client.post(sub_url, {}, format='json')
        assert r_sub.status_code == status.HTTP_200_OK
        assert r_sub.data['status'] == 'SUBMITTED'
        assert r_sub.data['completed_at'] is not None
        assert r_sub.data['deadline'] is None
        assert not ActiveAssessmentReservation.objects.filter(attempt_id=attempt.id).exists()


# ==============================================================================
# 9. Exception-to-HTTP Mapping & Lock Timeout Tests
# ==============================================================================

class TestExceptionMappingAndLockTimeout:
    """Verifies exception adapter envelope and HTTP 503 lock timeout handling."""

    def test_lock_timeout_maps_to_503(self, db, candidate_user, standard_assessment):
        """LockTimeoutError (MySQL 1205) correctly fails fast with HTTP 503 Service Unavailable."""
        asm, _ = standard_assessment
        client = APIClient()
        client.force_login(candidate_user)

        url = reverse('assessments:attempt-start', kwargs={'assessment_id': asm.id})

        with patch.object(
            AssessmentAttemptService,
            'start_or_resume_attempt',
            side_effect=LockTimeoutError("Database lock wait timeout (MySQL 1205)"),
        ):
            resp = client.post(url, {}, format='json', HTTP_IDEMPOTENCY_KEY='lock-test-key')
            assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
            assert resp.data['error']['code'] == 'lock_timeout'
            assert 'timeout' in resp.data['error']['message'].lower()

    def test_standard_envelope_structure_on_errors(self, db, candidate_user, standard_assessment):
        """All domain and validation errors consistently adhere to the global error envelope."""
        asm, _ = standard_assessment
        client = APIClient()
        client.force_login(candidate_user)

        # Missing header error
        url = reverse('assessments:attempt-start', kwargs={'assessment_id': asm.id})
        resp = client.post(url, {}, format='json')
        assert 'error' in resp.data
        err = resp.data['error']
        assert 'code' in err
        assert 'message' in err
        assert 'details' in err
