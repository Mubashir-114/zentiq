"""
Assessment Attempt Service for ZENTIQ (Milestone 4A - Phase 2D.2).
Governs Stage B (Attempt creation, mandatory idempotency, active reservations, question snapshots)
and Stage D (Attempt lifecycle: submit, expire, cancel, server-side deadline enforcement).
"""
import copy
from datetime import timedelta
import random
from typing import Any, Optional
import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from apps.arena.models import Question, QuestionVersion
from apps.assessments.models import (
    ActiveAssessmentReservation,
    Assessment,
    AssessmentAttempt,
    AssessmentVersion,
    AssessmentVersionQuestion,
    AttemptEvent,
    AttemptQuestion,
)
from .concurrency import with_deadlock_retry
from .dto import AttemptSummaryDTO, sanitize_candidate_content_payload
from .exceptions import (
    ActiveAttemptExistsError,
    AssessmentDeprecatedError,
    AssessmentNoActiveVersionError,
    AssessmentNotFoundError,
    AssessmentValidationError,
    AttemptExpiredError,
    AttemptNotFoundError,
    AttemptTerminalError,
)
from .permissions import (
    check_can_access_attempt,
    check_can_cancel_attempt,
    check_can_start_attempt,
)


def build_attempt_summary(attempt: AssessmentAttempt) -> AttemptSummaryDTO:
    """
    Constructs an AttemptSummaryDTO from an AssessmentAttempt instance.
    """
    return AttemptSummaryDTO(
        attempt_id=attempt.id,
        assessment_id=attempt.assessment_id,
        assessment_code=attempt.assessment.code,
        assessment_title=attempt.assessment.title,
        version_number=attempt.assessment_version.version_number,
        status=attempt.status,
        attempt_number=attempt.attempt_number,
        started_at=attempt.started_at,
        completed_at=attempt.completed_at,
        deadline=attempt.deadline,
        time_limit_seconds=attempt.time_limit_seconds,
        question_count=attempt.question_count,
        answer_count=attempt.answer_count,
        current_order_index=attempt.current_order_index,
        allow_backtracking=attempt.allow_backtracking,
    )


class AssessmentAttemptService:
    """
    Authoritative domain service coordinating assessment attempt creation,
    reservations, question snapshots, and lifecycle state transitions.
    """

    @classmethod
    @with_deadlock_retry()
    def start_or_resume_attempt(
        cls,
        *,
        assessment_id: Any,
        user: Any,
        idempotency_key: str,
    ) -> tuple[AssessmentAttempt, bool]:
        """
        Starts a new assessment attempt or resumes an existing one matching the idempotency key.

        Returns:
            tuple[AssessmentAttempt, bool]: (attempt, created)
            - created=True if a new attempt was generated.
            - created=False if an existing attempt was replayed idempotently.

        Guarantees:
        - Strict mandatory idempotency key handling scoped to (user, assessment).
        - Exactly one active attempt per (user, assessment) enforced via ActiveAssessmentReservation.
        - Preserves approved savepoint strategy for reservation collision handling.
        - Snapshots question order, weights, and option shuffling per attempt.
        - Preserves exact pinned QuestionVersion foreign keys without silent substitutions.
        - Appends ATTEMPT_STARTED audit event.
        """
        a_id = getattr(assessment_id, 'pk', assessment_id)

        if not idempotency_key or not idempotency_key.strip():
            raise AssessmentValidationError("Mandatory idempotency_key must not be blank.")

        clean_idem_key = idempotency_key.strip()
        if len(clean_idem_key) > 64:
            raise AssessmentValidationError("Idempotency key must not exceed 64 characters.")

        with transaction.atomic():
            # 1. Lock parent Assessment with candidate-side SHARED lock
            try:
                assessment = Assessment.objects.select_for_update(share=True).get(pk=a_id)
            except Assessment.DoesNotExist as exc:
                raise AssessmentNotFoundError(f"Assessment '{a_id}' does not exist.") from exc

            check_can_start_attempt(user, assessment)

            if assessment.is_deprecated:
                raise AssessmentDeprecatedError(
                    f"Assessment '{assessment.code}' is deprecated and cannot accept new attempts."
                )

            # 2. Check for idempotent replay: match (user, assessment, idempotency_key)
            existing_attempt = (
                AssessmentAttempt.objects.filter(
                    user=user,
                    assessment=assessment,
                    idempotency_key=clean_idem_key,
                )
                .select_related('assessment', 'assessment_version')
                .first()
            )
            if existing_attempt:
                # If active attempt has expired by deadline, expire it transactionally
                if existing_attempt.status == 'IN_PROGRESS' and existing_attempt.deadline:
                    if timezone.now() > existing_attempt.deadline:
                        cls.expire_attempt(existing_attempt.id)
                        existing_attempt.refresh_from_db()
                return existing_attempt, False

            # 3. Lock active version with candidate-side SHARED lock
            if not assessment.active_version_id:
                raise AssessmentNoActiveVersionError(
                    f"Assessment '{assessment.code}' does not have an active published version."
                )

            active_ver = (
                AssessmentVersion.objects.select_for_update(share=True)
                .filter(pk=assessment.active_version_id)
                .first()
            )
            if not active_ver or active_ver.status != 'PUBLISHED':
                raise AssessmentNoActiveVersionError(
                    f"Assessment '{assessment.code}' active version is not in PUBLISHED status."
                )

            # 4. Check for existing active reservation on this assessment
            active_res = (
                ActiveAssessmentReservation.objects.filter(
                    user=user,
                    assessment=assessment,
                )
                .select_related('attempt')
                .first()
            )
            if active_res:
                active_att = active_res.attempt
                # Check if the active attempt has expired
                if active_att.deadline and timezone.now() > active_att.deadline:
                    cls.expire_attempt(active_att.id)
                else:
                    raise ActiveAttemptExistsError(
                        f"An active attempt (#{active_att.attempt_number}) is already in progress for assessment '{assessment.code}'.",
                        details={
                            'attempt_id': str(active_att.id),
                            'attempt_number': active_att.attempt_number,
                            'status': active_att.status,
                        },
                    )

            # 5. Fetch pinned questions from active version
            version_questions = list(
                AssessmentVersionQuestion.objects.filter(assessment_version=active_ver)
                .select_related('question_version', 'question_version__question')
                .order_by('order_index')
            )
            if not version_questions:
                raise AssessmentValidationError(
                    f"Published assessment version '{active_ver.id}' contains no questions."
                )

            # 6. Acquire SHARED locks on canonical Question records in sorted PK order
            canonical_q_ids = sorted(list({avq.question_version.question_id for avq in version_questions}))
            locked_questions = list(
                Question.objects.select_for_update(share=True)
                .filter(pk__in=canonical_q_ids)
                .order_by('pk')
            )
            locked_q_map = {q.pk: q for q in locked_questions}

            # 7. Acquire SHARED locks on QuestionVersion records in sorted PK order
            qv_ids = sorted(list({avq.question_version_id for avq in version_questions}))
            locked_qvs = list(
                QuestionVersion.objects.select_for_update(share=True)
                .filter(pk__in=qv_ids)
                .order_by('pk')
            )
            locked_qv_map = {qv.pk: qv for qv in locked_qvs}

            # Validate that none of the pinned questions are deprecated or unpublished
            for avq in version_questions:
                qv = locked_qv_map.get(avq.question_version_id)
                q = locked_q_map.get(qv.question_id) if qv else None
                if not qv or qv.status != 'PUBLISHED':
                    raise AssessmentValidationError(
                        f"Pinned QuestionVersion '{avq.question_version_id}' is no longer published."
                    )
                if not q or q.is_deprecated:
                    raise AssessmentValidationError(
                        f"Pinned Question '{q.code if q else 'unknown'}' is deprecated."
                    )

            # 8. Compute sequential attempt number for (user, assessment)
            max_num = (
                AssessmentAttempt.objects.filter(user=user, assessment=assessment)
                .aggregate(Max('attempt_number'))['attempt_number__max']
                or 0
            )
            next_attempt_number = max_num + 1

            now = timezone.now()
            time_limit = active_ver.time_limit_seconds
            deadline = now + timedelta(seconds=time_limit) if time_limit else None

            # 9. Create AssessmentAttempt
            attempt = AssessmentAttempt(
                user=user,
                assessment=assessment,
                assessment_version=active_ver,
                attempt_number=next_attempt_number,
                status='IN_PROGRESS',
                started_at=now,
                deadline=deadline,
                time_limit_seconds=time_limit,
                allow_backtracking=active_ver.allow_backtracking,
                current_order_index=1,
                question_count=len(version_questions),
                answer_count=0,
                idempotency_key=clean_idem_key,
            )
            attempt.full_clean()

            # 10. Create Attempt and ActiveAssessmentReservation using nested savepoint
            try:
                with transaction.atomic():  # Creates isolated DB savepoint
                    attempt.save()
                    ActiveAssessmentReservation.objects.create(
                        user=user,
                        assessment=assessment,
                        attempt=attempt,
                        idempotency_key=clean_idem_key,
                    )
            except IntegrityError as exc:
                # Savepoint rolled back; inspect collision using fresh current locking read
                # Do NOT use select_related('attempt') as it would lock attempt or expand lock scope
                collision = (
                    ActiveAssessmentReservation.objects.select_for_update()
                    .filter(
                        user=user,
                        assessment=assessment,
                    )
                    .first()
                )
                if collision:
                    raise ActiveAttemptExistsError(
                        f"Concurrent attempt start conflict: an active attempt already exists ({collision.attempt_id}).",
                        details={'attempt_id': str(collision.attempt_id)},
                    ) from exc
                raise

            # 11. Snapshot AttemptQuestions and shuffle options
            for avq in version_questions:
                qv = locked_qv_map.get(avq.question_version_id) or avq.question_version

                # Clean and sanitize presentation payload
                raw_payload = qv.content_payload or {}
                sanitized_payload = sanitize_candidate_content_payload(raw_payload)

                # Shuffle options if present
                options = sanitized_payload.get('options')
                if isinstance(options, list) and len(options) > 1:
                    shuffled_options = list(options)
                    random.shuffle(shuffled_options)
                    sanitized_payload['options'] = shuffled_options

                aq = AttemptQuestion(
                    attempt=attempt,
                    question_version=qv,
                    order_index=avq.order_index,
                    weight=avq.weight,
                    prompt_snapshot=qv.prompt,
                    content_payload_snapshot=sanitized_payload,
                    question_type_snapshot=qv.question_type,
                    time_limit_seconds_snapshot=qv.time_limit_seconds,
                )
                aq.full_clean()
                aq.save()

            # 10. Record append-only audit event
            AttemptEvent.objects.create(
                attempt=attempt,
                event_type='ATTEMPT_STARTED',
                payload={
                    'assessment_id': str(assessment.id),
                    'assessment_code': assessment.code,
                    'version_number': active_ver.version_number,
                    'attempt_number': attempt.attempt_number,
                    'question_count': attempt.question_count,
                    'time_limit_seconds': attempt.time_limit_seconds,
                    'deadline': attempt.deadline.isoformat() if attempt.deadline else None,
                    'allow_backtracking': attempt.allow_backtracking,
                },
            )

            return attempt, True

    @classmethod
    @with_deadlock_retry()
    def submit_attempt(
        cls,
        attempt_id: Any,
        *,
        user: Any,
    ) -> AttemptSummaryDTO:
        """
        Concludes and submits an assessment attempt in IN_PROGRESS status.
        Enforces strict server-side deadline: if deadline has passed, expires attempt.
        Cleans up active reservation transactionally and appends ATTEMPT_SUBMITTED audit event.
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
                    f"Attempt is already in terminal status '{attempt.status}' and cannot be submitted."
                )

            # Strict server-side deadline enforcement
            if attempt.deadline and timezone.now() > attempt.deadline:
                cls._expire_attempt_locked(attempt)
                is_expired = True
            else:
                attempt.status = 'SUBMITTED'
                attempt.completed_at = timezone.now()
                attempt.full_clean()
                attempt.save(update_fields=['status', 'completed_at', 'updated_at'])

                # Clean up active reservation
                ActiveAssessmentReservation.objects.filter(attempt=attempt).delete()

                AttemptEvent.objects.create(
                    attempt=attempt,
                    event_type='ATTEMPT_SUBMITTED',
                    payload={
                        'attempt_number': attempt.attempt_number,
                        'question_count': attempt.question_count,
                        'answer_count': attempt.answer_count,
                    },
                )

        if is_expired:
            raise AttemptExpiredError("The time limit for this assessment attempt has expired.")

        return build_attempt_summary(attempt)

    @classmethod
    @with_deadlock_retry()
    def expire_attempt(
        cls,
        attempt_id: Any,
    ) -> AttemptSummaryDTO:
        """
        Transitions an IN_PROGRESS attempt to EXPIRED status.
        Cleans up active reservation and logs ATTEMPT_EXPIRED audit event.
        """
        att_id = getattr(attempt_id, 'pk', attempt_id)
        with transaction.atomic():
            try:
                attempt = (
                    AssessmentAttempt.objects.select_for_update()
                    .select_related('assessment', 'assessment_version')
                    .get(pk=att_id)
                )
            except AssessmentAttempt.DoesNotExist as exc:
                raise AttemptNotFoundError(f"Attempt '{att_id}' does not exist.") from exc

            if attempt.status != 'IN_PROGRESS':
                return build_attempt_summary(attempt)

            return cls._expire_attempt_locked(attempt)

    @classmethod
    def _expire_attempt_locked(cls, attempt: AssessmentAttempt) -> AttemptSummaryDTO:
        """
        Internal helper to transition an already-locked attempt to EXPIRED status.
        """
        attempt.status = 'EXPIRED'
        attempt.completed_at = timezone.now()
        attempt.full_clean()
        attempt.save(update_fields=['status', 'completed_at', 'updated_at'])

        ActiveAssessmentReservation.objects.filter(attempt=attempt).delete()

        AttemptEvent.objects.create(
            attempt=attempt,
            event_type='ATTEMPT_EXPIRED',
            payload={
                'deadline': attempt.deadline.isoformat() if attempt.deadline else None,
                'question_count': attempt.question_count,
                'answer_count': attempt.answer_count,
            },
        )
        return build_attempt_summary(attempt)

    @classmethod
    @with_deadlock_retry()
    def cancel_attempt(
        cls,
        attempt_id: Any,
        *,
        user: Any,
        reason: str = '',
    ) -> AttemptSummaryDTO:
        """
        Cancels an IN_PROGRESS assessment attempt.
        Cleans up active reservation and logs ATTEMPT_CANCELLED audit event.
        """
        att_id = getattr(attempt_id, 'pk', attempt_id)

        with transaction.atomic():
            try:
                attempt = (
                    AssessmentAttempt.objects.select_for_update()
                    .select_related('assessment', 'assessment_version')
                    .get(pk=att_id)
                )
            except AssessmentAttempt.DoesNotExist as exc:
                raise AttemptNotFoundError(f"Attempt '{att_id}' does not exist.") from exc

            check_can_cancel_attempt(user, attempt)

            if attempt.status != 'IN_PROGRESS':
                raise AttemptTerminalError(
                    f"Attempt is in status '{attempt.status}' and cannot be cancelled."
                )

            attempt.status = 'CANCELLED'
            attempt.completed_at = timezone.now()
            attempt.full_clean()
            attempt.save(update_fields=['status', 'completed_at', 'updated_at'])

            ActiveAssessmentReservation.objects.filter(attempt=attempt).delete()

            AttemptEvent.objects.create(
                attempt=attempt,
                event_type='ATTEMPT_CANCELLED',
                payload={
                    'reason': reason.strip() if reason else 'User cancelled',
                    'question_count': attempt.question_count,
                    'answer_count': attempt.answer_count,
                },
            )

            return build_attempt_summary(attempt)

    @classmethod
    def get_attempt_summary(
        cls,
        attempt_id: Any,
        *,
        user: Any = None,
    ) -> AttemptSummaryDTO:
        """
        Retrieves summary DTO for an assessment attempt.
        """
        att_id = getattr(attempt_id, 'pk', attempt_id)
        try:
            attempt = (
                AssessmentAttempt.objects.select_related('assessment', 'assessment_version')
                .get(pk=att_id)
            )
        except AssessmentAttempt.DoesNotExist as exc:
            raise AttemptNotFoundError(f"Attempt '{att_id}' does not exist.") from exc

        if user is not None:
            check_can_access_attempt(user, attempt)

        # Check deadline lazily
        if attempt.status == 'IN_PROGRESS' and attempt.deadline:
            if timezone.now() > attempt.deadline:
                return cls.expire_attempt(attempt.id)

        return build_attempt_summary(attempt)
