"""
Unit and integration tests for AssessmentNavigationService (Milestone 4A - Phase 2D.2 Stage C).
Covers:
- Forward and backward question navigation when backtracking is allowed.
- Forward-only sequential navigation enforcement when backtracking is disabled.
- Rejection of out-of-order jumping and skipping ahead when backtracking is disabled.
- CandidateQuestionDTO generation and candidate confidentiality verification.
- Time remaining calculation and server-side deadline expiration.
- Terminal attempt navigation prevention.
- Append-only QUESTION_NAVIGATED audit trail.
- Authorization guards.
"""
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import sys

# Ensure backend root is on sys.path
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.arena.models import Question, QuestionVersion
from apps.assessments.models import AttemptEvent
from apps.assessments.services import (
    AssessmentAttemptService,
    AssessmentCompositionService,
    AssessmentNavigationService,
    AssessmentPermissionDeniedError,
    AttemptExpiredError,
    AttemptTerminalError,
    BacktrackingNotAllowedError,
    InvalidNavigationError,
)
from apps.skills.models import Competency, Domain, Subdomain

User = get_user_model()


@pytest.fixture
def author_user(db):
    return User.objects.create_user(
        email='author_nav@example.com',
        password='TestPassword123!',
        is_staff=True,
    )


@pytest.fixture
def candidate_user(db):
    return User.objects.create_user(
        email='cand_nav@example.com',
        password='TestPassword123!',
    )


@pytest.fixture
def other_user(db):
    return User.objects.create_user(
        email='other_nav@example.com',
        password='TestPassword123!',
    )


@pytest.fixture
def competency(db):
    domain = Domain.objects.create(
        slug='data-structures',
        name='Data Structures',
        category='TECHNICAL',
        description='DS domain',
        display_order=1,
    )
    subdomain = Subdomain.objects.create(
        domain=domain,
        slug='trees',
        name='Trees',
        display_order=1,
    )
    return Competency.objects.create(
        subdomain=subdomain,
        code='COMP-TREE-01',
        name='Binary Trees',
        description='Tree traversal',
        bloom_level='APPLY',
    )


def create_3_question_assessment(author, comp, allow_backtracking=True, time_limit_seconds=3600):
    qvs = []
    for i in range(1, 4):
        q = Question.objects.create(code=f'QST-NAV-{i}', created_by=author)
        qv = QuestionVersion.objects.create(
            question=q,
            version_number=1,
            status='DRAFT',
            title=f'Question {i}',
            prompt=f'Prompt text for question {i}',
            question_type='SINGLE_CHOICE',
            primary_competency=comp,
            content_payload={'options': [{'id': '1', 'text': f'Option {i}-A'}]},
            created_by=author,
        )
        qv.status = 'IN_REVIEW'; qv.save(); qv.status = 'PUBLISHED'; qv.save()
        q.active_version = qv; q.save()
        qvs.append(qv)

    asm = AssessmentCompositionService.create_assessment(
        code=f'ASM-NAV-{"BT" if allow_backtracking else "FO"}',
        title='Navigation Assessment',
        user=author,
    )
    ver = AssessmentCompositionService.create_draft_version(
        asm.id,
        title='Nav v1.0',
        time_limit_seconds=time_limit_seconds,
        allow_backtracking=allow_backtracking,
        user=author,
    )
    for qv in qvs:
        AssessmentCompositionService.add_question_to_version(ver.id, qv.id, user=author)
    AssessmentCompositionService.publish_version(ver.id, user=author)
    asm.refresh_from_db()
    return asm, ver, qvs


# ==============================================================================
# Navigation with Backtracking Allowed
# ==============================================================================

class TestNavigationBacktrackingAllowed:
    def test_navigate_forward_and_backward(self, db, author_user, candidate_user, competency):
        asm, _, _ = create_3_question_assessment(author_user, competency, allow_backtracking=True)
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-nav-bt',
        )
        assert attempt.current_order_index == 1

        # Navigate forward to 2
        dto2 = AssessmentNavigationService.navigate_to_question(attempt.id, target_order_index=2, user=candidate_user)
        assert dto2.order_index == 2
        attempt.refresh_from_db()
        assert attempt.current_order_index == 2

        # Navigate forward to 3
        dto3 = AssessmentNavigationService.navigate_to_question(attempt.id, target_order_index=3, user=candidate_user)
        assert dto3.order_index == 3
        attempt.refresh_from_db()
        assert attempt.current_order_index == 3

        # Navigate backward to 1
        dto1 = AssessmentNavigationService.navigate_to_question(attempt.id, target_order_index=1, user=candidate_user)
        assert dto1.order_index == 1
        attempt.refresh_from_db()
        assert attempt.current_order_index == 1

        # Check QUESTION_NAVIGATED audit events
        events = list(AttemptEvent.objects.filter(attempt=attempt, event_type='QUESTION_NAVIGATED'))
        assert len(events) == 3
        assert events[0].payload == {'from_order': 1, 'to_order': 2}
        assert events[1].payload == {'from_order': 2, 'to_order': 3}
        assert events[2].payload == {'from_order': 3, 'to_order': 1}

    def test_navigate_out_of_bounds_rejected(self, db, author_user, candidate_user, competency):
        asm, _, _ = create_3_question_assessment(author_user, competency, allow_backtracking=True)
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-nav-bounds',
        )
        with pytest.raises(InvalidNavigationError):
            AssessmentNavigationService.navigate_to_question(attempt.id, target_order_index=0, user=candidate_user)

        with pytest.raises(InvalidNavigationError):
            AssessmentNavigationService.navigate_to_question(attempt.id, target_order_index=4, user=candidate_user)


# ==============================================================================
# Forward-Only Navigation (Backtracking Disabled)
# ==============================================================================

class TestForwardOnlyNavigation:
    def test_backward_navigation_rejected(self, db, author_user, candidate_user, competency):
        asm, _, _ = create_3_question_assessment(author_user, competency, allow_backtracking=False)
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-nav-fo',
        )
        assert attempt.current_order_index == 1
        assert attempt.allow_backtracking is False

        # Navigate to next (2)
        AssessmentNavigationService.navigate_to_question(attempt.id, target_order_index=2, user=candidate_user)
        attempt.refresh_from_db()
        assert attempt.current_order_index == 2

        # Backward navigation to 1 must be rejected
        with pytest.raises(BacktrackingNotAllowedError) as exc:
            AssessmentNavigationService.navigate_to_question(attempt.id, target_order_index=1, user=candidate_user)
        assert 'Backtracking' in str(exc.value)

    def test_skip_ahead_past_next_question_rejected(self, db, author_user, candidate_user, competency):
        asm, _, _ = create_3_question_assessment(author_user, competency, allow_backtracking=False)
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-nav-skip-ahead',
        )
        assert attempt.current_order_index == 1

        # Attempting to jump directly from 1 to 3 must be rejected
        with pytest.raises(InvalidNavigationError) as exc:
            AssessmentNavigationService.navigate_to_question(attempt.id, target_order_index=3, user=candidate_user)
        assert 'Cannot skip ahead' in str(exc.value)

    def test_direct_question_access_restricted_when_forward_only(self, db, author_user, candidate_user, competency):
        asm, _, _ = create_3_question_assessment(author_user, competency, allow_backtracking=False)
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-nav-direct',
        )
        # Accessing current question succeeds
        dto1 = AssessmentNavigationService.get_question_by_order(attempt.id, order_index=1, user=candidate_user)
        assert dto1.order_index == 1

        # Accessing future question 2 directly without navigating raises BacktrackingNotAllowedError
        with pytest.raises(BacktrackingNotAllowedError):
            AssessmentNavigationService.get_question_by_order(attempt.id, order_index=2, user=candidate_user)


# ==============================================================================
# Question Representation & Candidate Confidentiality
# ==============================================================================

class TestCandidateQuestionConfidentiality:
    def test_candidate_safe_question_dto_sanitization(self, db, author_user, candidate_user, competency):
        asm, _, qvs = create_3_question_assessment(author_user, competency, allow_backtracking=True)
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-cand-dto',
        )
        dto = AssessmentNavigationService.get_current_question(attempt.id, user=candidate_user)
        assert dto.order_index == 1
        assert dto.question_count == 3
        assert dto.prompt == qvs[0].prompt
        assert dto.question_type == 'SINGLE_CHOICE'
        assert dto.is_answered is False
        assert dto.current_answer is None
        assert dto.time_remaining_seconds is not None
        assert dto.time_remaining_seconds > 0

        # Verify no evaluation attributes on DTO
        assert not hasattr(dto, 'correct_payload')
        assert not hasattr(dto, 'scoring_rubric')
        assert not hasattr(dto, 'explanation')
        assert not hasattr(dto, 'competency')

    def test_deadline_expiration_on_navigation(self, db, author_user, candidate_user, competency):
        asm, _, _ = create_3_question_assessment(author_user, competency, allow_backtracking=True)
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-nav-deadline',
        )
        # Fast forward deadline
        attempt.deadline = timezone.now() - timedelta(seconds=1)
        attempt.save(update_fields=['deadline'])

        with pytest.raises(AttemptExpiredError):
            AssessmentNavigationService.navigate_to_question(attempt.id, target_order_index=2, user=candidate_user)

        attempt.refresh_from_db()
        assert attempt.status == 'EXPIRED'

    def test_terminal_attempt_navigation_prohibited(self, db, author_user, candidate_user, competency):
        asm, _, _ = create_3_question_assessment(author_user, competency, allow_backtracking=True)
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-nav-term',
        )
        AssessmentAttemptService.submit_attempt(attempt.id, user=candidate_user)

        with pytest.raises(AttemptTerminalError):
            AssessmentNavigationService.navigate_to_question(attempt.id, target_order_index=2, user=candidate_user)

    def test_unauthorized_user_navigation_rejected(self, db, author_user, candidate_user, other_user, competency):
        asm, _, _ = create_3_question_assessment(author_user, competency, allow_backtracking=True)
        attempt, _ = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=asm.id,
            user=candidate_user,
            idempotency_key='idem-nav-unauth',
        )
        with pytest.raises(AssessmentPermissionDeniedError):
            AssessmentNavigationService.navigate_to_question(attempt.id, target_order_index=2, user=other_user)

