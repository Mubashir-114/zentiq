"""
Assessment Navigation Service for ZENTIQ (Milestone 4A - Phase 2D.2).
Governs candidate movement across questions, enforces forward-only rules when backtracking is disabled,
and returns strictly sanitized CandidateQuestionDTOs.
"""
from typing import Any, Optional
import uuid

from django.db import transaction
from django.utils import timezone

from apps.assessments.models import (
    AssessmentAttempt,
    AttemptAnswer,
    AttemptEvent,
    AttemptQuestion,
)
from .concurrency import with_deadlock_retry
from .dto import CandidateQuestionDTO, sanitize_candidate_content_payload
from .exceptions import (
    AttemptExpiredError,
    AttemptNotFoundError,
    AttemptTerminalError,
    BacktrackingNotAllowedError,
    InvalidNavigationError,
)
from .permissions import check_can_access_attempt


def build_candidate_question_dto(
    attempt: AssessmentAttempt,
    aq: AttemptQuestion,
) -> CandidateQuestionDTO:
    """
    Builds a candidate-safe CandidateQuestionDTO for a given AttemptQuestion.
    Ensures zero leakage of evaluation keys, answer keys, scoring rubrics, or explanations.
    """
    existing_answer = AttemptAnswer.objects.filter(attempt_question=aq).first()
    time_remaining = (
        int(max(0, (attempt.deadline - timezone.now()).total_seconds()))
        if attempt.deadline
        else None
    )

    return CandidateQuestionDTO(
        attempt_id=attempt.id,
        attempt_question_id=aq.id,
        order_index=aq.order_index,
        question_count=attempt.question_count,
        prompt=aq.prompt_snapshot,
        question_type=aq.question_type_snapshot,
        content_payload=sanitize_candidate_content_payload(aq.content_payload_snapshot),
        time_limit_seconds=aq.time_limit_seconds_snapshot,
        current_answer=existing_answer.answer_payload if existing_answer else None,
        is_answered=existing_answer.is_answered if existing_answer else False,
        allow_backtracking=attempt.allow_backtracking,
        current_order_index=attempt.current_order_index,
        deadline=attempt.deadline,
        time_remaining_seconds=time_remaining,
    )


class AssessmentNavigationService:
    """
    Authoritative domain service coordinating question retrieval and candidate navigation.
    """

    @classmethod
    @with_deadlock_retry()
    def navigate_to_question(
        cls,
        attempt_id: Any,
        target_order_index: int,
        *,
        user: Any,
    ) -> CandidateQuestionDTO:
        """
        Navigates candidate to target_order_index within an IN_PROGRESS attempt.
        Enforces:
        - Attempt serialization lock.
        - Candidate ownership and active attempt status.
        - Server-side deadline check.
        - Target index bounds (1 <= target <= question_count).
        - Forward-only navigation when backtracking is disabled:
          Rejects target < current_order_index.
          Rejects skipping ahead past current_order_index + 1.
        - Updates attempt.current_order_index.
        - Records QUESTION_NAVIGATED audit event.
        - Returns candidate-safe representation.
        """
        att_id = getattr(attempt_id, 'pk', attempt_id)

        is_expired = False
        with transaction.atomic():
            try:
                attempt = (
                    AssessmentAttempt.objects.select_for_update()
                    .select_related('assessment', 'assessment_version')
                    .get(pk=att_id)
                )
            except AssessmentAttempt.DoesNotExist as exc:
                raise AttemptNotFoundError(f"Attempt '{att_id}' does not exist.") from exc

            check_can_access_attempt(user, attempt)

            if attempt.status != 'IN_PROGRESS':
                raise AttemptTerminalError(
                    f"Attempt is in terminal status '{attempt.status}' and navigation is disabled."
                )

            # Deadline verification
            if attempt.deadline and timezone.now() > attempt.deadline:
                from .attempt_service import AssessmentAttemptService
                AssessmentAttemptService._expire_attempt_locked(attempt)
                is_expired = True
            else:
                # Bounds check
                if target_order_index < 1 or target_order_index > attempt.question_count:
                    raise InvalidNavigationError(
                        f"Target order index {target_order_index} is out of bounds (1..{attempt.question_count})."
                    )

                prev_order = attempt.current_order_index

                # Backtracking rules
                if not attempt.allow_backtracking:
                    if target_order_index < prev_order:
                        raise BacktrackingNotAllowedError(
                            f"Backtracking to question #{target_order_index} is not permitted. "
                            f"Current question is #{prev_order}."
                        )
                    if target_order_index > prev_order + 1:
                        raise InvalidNavigationError(
                            f"Cannot skip ahead to question #{target_order_index} from #{prev_order} "
                            "when forward-only navigation is enforced."
                        )

                if target_order_index != prev_order:
                    attempt.current_order_index = target_order_index
                    attempt.save(update_fields=['current_order_index', 'updated_at'])

                    AttemptEvent.objects.create(
                        attempt=attempt,
                        event_type='QUESTION_NAVIGATED',
                        payload={
                            'from_order': prev_order,
                            'to_order': target_order_index,
                        },
                    )

                aq = AttemptQuestion.objects.get(attempt=attempt, order_index=target_order_index)
                dto_result = build_candidate_question_dto(attempt, aq)

        if is_expired:
            raise AttemptExpiredError("The time limit for this assessment attempt has expired.")

        return dto_result

    @classmethod
    def get_current_question(
        cls,
        attempt_id: Any,
        *,
        user: Any,
    ) -> CandidateQuestionDTO:
        """
        Retrieves the candidate-safe question DTO for the attempt's current_order_index.
        """
        att_id = getattr(attempt_id, 'pk', attempt_id)
        try:
            attempt = (
                AssessmentAttempt.objects.select_related('assessment', 'assessment_version')
                .get(pk=att_id)
            )
        except AssessmentAttempt.DoesNotExist as exc:
            raise AttemptNotFoundError(f"Attempt '{att_id}' does not exist.") from exc

        check_can_access_attempt(user, attempt)

        # Check deadline lazily
        if attempt.status == 'IN_PROGRESS' and attempt.deadline:
            if timezone.now() > attempt.deadline:
                from .attempt_service import AssessmentAttemptService
                AssessmentAttemptService.expire_attempt(attempt.id)
                raise AttemptExpiredError("The time limit for this assessment attempt has expired.")

        aq = AttemptQuestion.objects.get(attempt=attempt, order_index=attempt.current_order_index)
        return build_candidate_question_dto(attempt, aq)

    @classmethod
    def get_question_by_order(
        cls,
        attempt_id: Any,
        order_index: int,
        *,
        user: Any,
    ) -> CandidateQuestionDTO:
        """
        Retrieves the candidate-safe question DTO for a specific order index.
        Enforces backtracking restrictions: if backtracking is disabled, candidates
        can only access current_order_index.
        """
        att_id = getattr(attempt_id, 'pk', attempt_id)
        try:
            attempt = (
                AssessmentAttempt.objects.select_related('assessment', 'assessment_version')
                .get(pk=att_id)
            )
        except AssessmentAttempt.DoesNotExist as exc:
            raise AttemptNotFoundError(f"Attempt '{att_id}' does not exist.") from exc

        check_can_access_attempt(user, attempt)

        # Check deadline lazily
        if attempt.status == 'IN_PROGRESS' and attempt.deadline:
            if timezone.now() > attempt.deadline:
                from .attempt_service import AssessmentAttemptService
                AssessmentAttemptService.expire_attempt(attempt.id)
                raise AttemptExpiredError("The time limit for this assessment attempt has expired.")

        if not attempt.allow_backtracking and order_index != attempt.current_order_index:
            raise BacktrackingNotAllowedError(
                f"Access to question #{order_index} is not allowed when backtracking is disabled. "
                f"Current question is #{attempt.current_order_index}."
            )

        try:
            aq = AttemptQuestion.objects.get(attempt=attempt, order_index=order_index)
        except AttemptQuestion.DoesNotExist as exc:
            raise InvalidNavigationError(
                f"Question #{order_index} does not exist in this attempt."
            ) from exc

        return build_candidate_question_dto(attempt, aq)
