"""
Assessment Answer Service for ZENTIQ (Milestone 4A - Phase 2D.2).
Governs Stage C answer submission, explicit question skipping, answer-type validation,
and attempt counter updates.
"""
from decimal import Decimal, InvalidOperation
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
    AnswerValidationError,
    AttemptExpiredError,
    AttemptNotFoundError,
    AttemptTerminalError,
    BacktrackingNotAllowedError,
    InvalidNavigationError,
)
from .permissions import check_can_access_attempt


def validate_answer_payload_for_type(
    answer_payload: Any,
    question_type: str,
    content_payload: dict[str, Any],
) -> None:
    """
    Validates candidate answer payload against the snapshotted question type and presentation choices.
    Supported types:
    - SINGLE_CHOICE: {'selected_option_id': str/int}
    - MULTIPLE_CHOICE: {'selected_option_ids': list[str/int]} (non-empty)
    - TRUE_FALSE: {'selected_value': bool or str/int}
    - NUMERICAL: {'value': int/float/Decimal or numeric string}
    - SHORT_TEXT: {'text': non-empty str}
    - CODE_OUTPUT: {'output': str} or {'text': str}
    """
    if not isinstance(answer_payload, dict):
        raise AnswerValidationError("Answer payload must be a JSON object (dictionary).")

    options = content_payload.get('options')
    valid_option_ids: set[str] = set()
    if isinstance(options, list):
        for opt in options:
            if isinstance(opt, dict):
                opt_id = opt.get('id') or opt.get('option_id')
                if opt_id is not None:
                    valid_option_ids.add(str(opt_id))

    if question_type == 'SINGLE_CHOICE':
        if 'selected_option_id' not in answer_payload:
            raise AnswerValidationError("Missing required key 'selected_option_id' for SINGLE_CHOICE question.")
        selected = answer_payload['selected_option_id']
        if selected is None or str(selected).strip() == '':
            raise AnswerValidationError("selected_option_id cannot be null or empty.")
        if valid_option_ids and str(selected) not in valid_option_ids:
            raise AnswerValidationError(
                f"Selected option '{selected}' is not among valid choices: {sorted(list(valid_option_ids))}."
            )

    elif question_type == 'MULTIPLE_CHOICE':
        if 'selected_option_ids' not in answer_payload:
            raise AnswerValidationError("Missing required key 'selected_option_ids' for MULTIPLE_CHOICE question.")
        selected_ids = answer_payload['selected_option_ids']
        if not isinstance(selected_ids, (list, tuple)) or len(selected_ids) == 0:
            raise AnswerValidationError("selected_option_ids must be a non-empty list of option IDs.")
        if valid_option_ids:
            for s_id in selected_ids:
                if str(s_id) not in valid_option_ids:
                    raise AnswerValidationError(
                        f"Selected option '{s_id}' is not among valid choices: {sorted(list(valid_option_ids))}."
                    )

    elif question_type == 'TRUE_FALSE':
        if 'selected_value' not in answer_payload:
            raise AnswerValidationError("Missing required key 'selected_value' for TRUE_FALSE question.")
        val = answer_payload['selected_value']
        if val is None:
            raise AnswerValidationError("selected_value cannot be None.")
        if not isinstance(val, bool):
            str_val = str(val).strip().upper()
            if str_val not in {'TRUE', 'FALSE', 'T', 'F', '1', '0'}:
                if valid_option_ids and str(val) not in valid_option_ids:
                    raise AnswerValidationError(f"Invalid TRUE_FALSE value '{val}'.")

    elif question_type == 'NUMERICAL':
        if 'value' not in answer_payload:
            raise AnswerValidationError("Missing required key 'value' for NUMERICAL question.")
        val = answer_payload['value']
        if val is None or isinstance(val, bool):
            raise AnswerValidationError("value must be a valid number, not boolean or null.")
        try:
            Decimal(str(val))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise AnswerValidationError(f"Invalid numerical value '{val}'.") from exc

    elif question_type == 'SHORT_TEXT':
        if 'text' not in answer_payload:
            raise AnswerValidationError("Missing required key 'text' for SHORT_TEXT question.")
        text_val = answer_payload['text']
        if not isinstance(text_val, str) or not text_val.strip():
            raise AnswerValidationError("text must be a non-empty string.")

    elif question_type == 'CODE_OUTPUT':
        if 'output' not in answer_payload and 'text' not in answer_payload:
            raise AnswerValidationError("Missing required key 'output' or 'text' for CODE_OUTPUT question.")
        out_val = answer_payload.get('output', answer_payload.get('text'))
        if not isinstance(out_val, str):
            raise AnswerValidationError("output must be a string.")


class AssessmentAnswerService:
    """
    Authoritative domain service handling candidate answer submission and skipping.
    """

    @classmethod
    @with_deadlock_retry()
    def submit_answer(
        cls,
        attempt_id: Any,
        question_order_index: int,
        answer_payload: dict[str, Any],
        *,
        user: Any,
    ) -> CandidateQuestionDTO:
        """
        Saves candidate answer for the specified question in an IN_PROGRESS attempt.
        Enforces:
        - Attempt serialization lock.
        - Candidate ownership and IN_PROGRESS state.
        - Strict server-side deadline.
        - Backtracking restrictions (forward-only navigation when backtracking disabled).
        - Question-type validation.
        - Distinct answer counter updates.
        - ANSWER_SUBMITTED audit event.
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
                    f"Attempt is in terminal status '{attempt.status}' and cannot receive answers."
                )

            # Deadline verification
            if attempt.deadline and timezone.now() > attempt.deadline:
                from .attempt_service import AssessmentAttemptService
                AssessmentAttemptService._expire_attempt_locked(attempt)
                is_expired = True
            else:
                # Backtracking verification
                if not attempt.allow_backtracking and question_order_index != attempt.current_order_index:
                    raise BacktrackingNotAllowedError(
                        f"Cannot submit answer for question #{question_order_index}. "
                        f"Current question is #{attempt.current_order_index} and backtracking is disabled."
                    )

                try:
                    aq = (
                        AttemptQuestion.objects.select_for_update()
                        .get(attempt=attempt, order_index=question_order_index)
                    )
                except AttemptQuestion.DoesNotExist as exc:
                    raise InvalidNavigationError(
                        f"Question #{question_order_index} does not exist in this attempt."
                    ) from exc

                # Validate answer payload against snapshot schema
                validate_answer_payload_for_type(
                    answer_payload=answer_payload,
                    question_type=aq.question_type_snapshot,
                    content_payload=aq.content_payload_snapshot or {},
                )

                # Update or create AttemptAnswer
                answer, created = AttemptAnswer.objects.get_or_create(
                    attempt_question=aq,
                    defaults={
                        'answer_payload': answer_payload,
                        'is_answered': True,
                        'answered_at': timezone.now(),
                    },
                )
                if not created:
                    answer.answer_payload = answer_payload
                    answer.is_answered = True
                    answer.answered_at = timezone.now()
                    answer.save()

                # Update distinct answer_count on attempt
                answered_count = AttemptAnswer.objects.filter(
                    attempt_question__attempt=attempt,
                    is_answered=True,
                ).count()
                attempt.answer_count = answered_count

                # If forward-only navigation, advance current_order_index automatically if answering current
                attempt_update_fields = ['answer_count', 'updated_at']
                if not attempt.allow_backtracking and attempt.current_order_index == question_order_index:
                    if attempt.current_order_index < attempt.question_count:
                        attempt.current_order_index += 1
                        attempt_update_fields.append('current_order_index')

                attempt.save(update_fields=attempt_update_fields)

                # Append append-only audit event
                AttemptEvent.objects.create(
                    attempt=attempt,
                    event_type='ANSWER_SUBMITTED',
                    payload={
                        'order_index': aq.order_index,
                        'attempt_question_id': str(aq.id),
                    },
                )

                # Build safe DTO
                time_remaining = (
                    int(max(0, (attempt.deadline - timezone.now()).total_seconds()))
                    if attempt.deadline
                    else None
                )

                dto_result = CandidateQuestionDTO(
                    attempt_id=attempt.id,
                    attempt_question_id=aq.id,
                    order_index=aq.order_index,
                    question_count=attempt.question_count,
                    prompt=aq.prompt_snapshot,
                    question_type=aq.question_type_snapshot,
                    content_payload=sanitize_candidate_content_payload(aq.content_payload_snapshot),
                    time_limit_seconds=aq.time_limit_seconds_snapshot,
                    current_answer=answer.answer_payload,
                    is_answered=True,
                    allow_backtracking=attempt.allow_backtracking,
                    current_order_index=attempt.current_order_index,
                    deadline=attempt.deadline,
                    time_remaining_seconds=time_remaining,
                )

        if is_expired:
            raise AttemptExpiredError("The time limit for this assessment attempt has expired.")

        return dto_result

    @classmethod
    @with_deadlock_retry()
    def skip_question(
        cls,
        attempt_id: Any,
        question_order_index: int,
        *,
        user: Any,
    ) -> CandidateQuestionDTO:
        """
        Explicitly skips answering the specified question.
        Advances current_order_index when forward-only navigation is enforced.
        Logs QUESTION_SKIPPED audit event.
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
                    f"Attempt is in terminal status '{attempt.status}' and questions cannot be skipped."
                )

            if attempt.deadline and timezone.now() > attempt.deadline:
                from .attempt_service import AssessmentAttemptService
                AssessmentAttemptService._expire_attempt_locked(attempt)
                is_expired = True
            else:
                if not attempt.allow_backtracking and question_order_index != attempt.current_order_index:
                    raise BacktrackingNotAllowedError(
                        f"Cannot skip question #{question_order_index}. "
                        f"Current question is #{attempt.current_order_index} and backtracking is disabled."
                    )

                try:
                    aq = AttemptQuestion.objects.get(attempt=attempt, order_index=question_order_index)
                except AttemptQuestion.DoesNotExist as exc:
                    raise InvalidNavigationError(
                        f"Question #{question_order_index} does not exist in this attempt."
                    ) from exc

                # Advance current_order_index if forward-only
                if not attempt.allow_backtracking and attempt.current_order_index == question_order_index:
                    if attempt.current_order_index < attempt.question_count:
                        attempt.current_order_index += 1
                        attempt.save(update_fields=['current_order_index', 'updated_at'])

                AttemptEvent.objects.create(
                    attempt=attempt,
                    event_type='QUESTION_SKIPPED',
                    payload={
                        'order_index': aq.order_index,
                        'attempt_question_id': str(aq.id),
                    },
                )

                existing_answer = AttemptAnswer.objects.filter(attempt_question=aq).first()
                time_remaining = (
                    int(max(0, (attempt.deadline - timezone.now()).total_seconds()))
                    if attempt.deadline
                    else None
                )

                dto_result = CandidateQuestionDTO(
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

        if is_expired:
            raise AttemptExpiredError("The time limit for this assessment attempt has expired.")

        return dto_result
