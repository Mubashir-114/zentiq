"""
Immutable result revision and authoritative head management (Phase 2E.2).

Exactly one transaction performs:
  lock attempt → lock head → verify predecessor is the current revision →
  verify same attempt → allocate next revision number → create the immutable
  snapshot + complete outcome set → move the head atomically → audit + outbox.

Revisions are never updated or deleted. Supersession is expressed by a new
revision whose ``supersedes`` pointer names the previous one; ``UNIQUE(attempt,
supersedes)`` makes the chain linear so two writers cannot fork history.
"""
from typing import Any, Iterable

from django.db import IntegrityError, transaction
from django.utils import timezone

from ..models import (
    RESULT_TERMINAL_STATUSES,
    AssessmentAttempt,
    AttemptEvent,
    AttemptQuestionEvaluation,
    AttemptResultHead,
    AttemptResultRevision,
)
from .evaluation.dto import QuestionOutcome
from .evaluation.policy import (
    EVALUATOR_VERSION,
    POLICY_VERSION,
    derive_totals,
)
from .exceptions import (
    ResultRevisionConflictError,
    ResultRevisionIntegrityError,
)

REASON_INITIAL = 'INITIAL_EVALUATION'


class ResultRevisionService:
    """Creates immutable result revisions and moves the authoritative head."""

    @classmethod
    def record_revision(
        cls,
        attempt: Any,
        outcomes: Iterable[QuestionOutcome],
        *,
        actor: Any = None,
        reason: str = REASON_INITIAL,
        reason_detail: str = '',
        expected_revision_id: Any = None,
        scoring_policy_version: str = POLICY_VERSION,
        evaluator_version: str = EVALUATOR_VERSION,
    ) -> AttemptResultRevision:
        rows = list(outcomes)

        with transaction.atomic():
            locked_attempt = (
                AssessmentAttempt.objects.select_for_update()
                .select_related('terminal_snapshot')
                .get(pk=attempt.pk)
            )

            if locked_attempt.status not in RESULT_TERMINAL_STATUSES:
                raise ResultRevisionConflictError(
                    'Results may only be recorded for terminal attempts.',
                    details={'attempt_id': str(locked_attempt.pk),
                             'status': locked_attempt.status},
                )

            snapshot = getattr(locked_attempt, 'terminal_snapshot', None)
            if snapshot is None:
                raise ResultRevisionIntegrityError(
                    'Attempt has no terminal policy snapshot; eligibility is unknown.',
                    details={'attempt_id': str(locked_attempt.pk)},
                )
            if snapshot.terminal_status != locked_attempt.status:
                raise ResultRevisionIntegrityError(
                    'Terminal snapshot does not match the attempt status.',
                    details={
                        'attempt_id': str(locked_attempt.pk),
                        'snapshot_status': snapshot.terminal_status,
                        'attempt_status': locked_attempt.status,
                    },
                )

            cls._verify_outcome_ownership(locked_attempt, rows)

            head = (
                AttemptResultHead.objects.select_for_update()
                .filter(attempt=locked_attempt)
                .select_related('current_revision')
                .first()
            )

            if head is None:
                if expected_revision_id is not None:
                    raise ResultRevisionConflictError(
                        'No authoritative result exists, but a predecessor revision was supplied.',
                        details={'attempt_id': str(locked_attempt.pk)},
                    )
                previous = None
                next_number = 1
            else:
                previous = head.current_revision
                if previous.attempt_id != locked_attempt.pk:
                    raise ResultRevisionIntegrityError(
                        'Authoritative head points at a revision from another attempt.',
                        details={
                            'attempt_id': str(locked_attempt.pk),
                            'revision_attempt_id': str(previous.attempt_id),
                        },
                    )
                if expected_revision_id is None or str(expected_revision_id) != str(previous.pk):
                    raise ResultRevisionConflictError(
                        'The requested predecessor is not the current authoritative revision.',
                        details={
                            'attempt_id': str(locked_attempt.pk),
                            'current_revision_id': str(previous.pk),
                            'expected_revision_id': (
                                str(expected_revision_id) if expected_revision_id else None
                            ),
                        },
                    )
                next_number = previous.revision_number + 1

            totals = derive_totals(rows)

            revision = AttemptResultRevision(
                attempt=locked_attempt,
                revision_number=next_number,
                supersedes=previous,
                terminal_snapshot=snapshot,
                status=totals.status,
                evaluation_status=totals.evaluation_status,
                final_score=totals.final_score,
                provisional_score=totals.provisional_score,
                total_weight=totals.total_weight,
                graded_weight=totals.graded_weight,
                excluded_weight=totals.excluded_weight,
                earned_weight=totals.earned_weight,
                question_count=totals.question_count,
                answered_count=totals.answered_count,
                correct_count=totals.correct_count,
                incorrect_count=totals.incorrect_count,
                partially_correct_count=totals.partially_correct_count,
                unanswered_count=totals.unanswered_count,
                ungraded_count=totals.ungraded_count,
                pending_manual_count=totals.pending_manual_count,
                scoring_policy_version=scoring_policy_version,
                evaluator_version=evaluator_version,
                actor_type='STAFF' if actor is not None else 'SYSTEM',
                actor=actor,
                reason=reason,
                reason_detail=reason_detail[:255],
                created_at=timezone.now(),
            )

            try:
                with transaction.atomic():  # savepoint: isolate chain uniqueness collision
                    revision.full_clean()
                    revision.save(force_insert=True)
            except IntegrityError as exc:
                raise ResultRevisionConflictError(
                    'A competing result revision was created concurrently.',
                    details={'attempt_id': str(locked_attempt.pk)},
                ) from exc

            for row in rows:
                AttemptQuestionEvaluation.objects.create(
                    result_revision=revision,
                    attempt_question_id=row.attempt_question_id,
                    outcome=row.outcome,
                    disposition=row.disposition,
                    awarded_fraction=row.awarded_fraction,
                    awarded_points=row.awarded_points,
                    max_points=row.max_points,
                    grading_strategy=row.grading_strategy,
                    evaluation_config_hash=row.evaluation_config_hash,
                    evaluator_version=evaluator_version,
                    ungraded_reason=row.ungraded_reason,
                    excluded_reason=row.excluded_reason,
                    answer_presence=row.answer_presence,
                    absence_reason=row.absence_reason,
                    answer_payload_hash=row.answer_payload_hash,
                    answer_canonicalization_version=row.answer_canonicalization_version,
                    details=row.details,
                    created_at=timezone.now(),
                )

            if previous is None:
                try:
                    with transaction.atomic():  # savepoint: concurrent first evaluation
                        AttemptResultHead.objects.create(
                            attempt=locked_attempt,
                            current_revision=revision,
                        )
                except IntegrityError as exc:
                    raise ResultRevisionConflictError(
                        'A competing authoritative result was created concurrently.',
                        details={'attempt_id': str(locked_attempt.pk)},
                    ) from exc
            else:
                head.current_revision = revision
                head.save(update_fields=['current_revision', 'updated_at'])

            from ..models import ResultOutboxEvent

            ResultOutboxEvent.objects.create(
                event_type='RESULT_REVISION_COMMITTED',
                attempt_id=locked_attempt.pk,
                result_revision=revision,
                dedupe_key=f'result:{locked_attempt.pk}:rev{next_number}:committed',
                payload={
                    'attempt_id': str(locked_attempt.pk),
                    'revision_id': str(revision.pk),
                    'revision_number': next_number,
                    'status': totals.status,
                },
            )

            AttemptEvent.objects.create(
                attempt=locked_attempt,
                event_type='ATTEMPT_EVALUATED',
                payload={
                    'revision_id': str(revision.pk),
                    'revision_number': next_number,
                    'status': totals.status,
                    'evaluation_status': totals.evaluation_status,
                    'graded_weight': str(totals.graded_weight),
                    'total_weight': str(totals.total_weight),
                },
            )

            return revision

    @classmethod
    def _verify_outcome_ownership(cls, attempt: Any, rows: list[QuestionOutcome]) -> None:
        expected_ids = set(
            attempt.questions.values_list('pk', flat=True)
        )
        supplied_ids = {row.attempt_question_id for row in rows}

        if len(supplied_ids) != len(rows):
            raise ResultRevisionIntegrityError(
                'Duplicate per-question outcomes are not permitted within a revision.',
                details={'attempt_id': str(attempt.pk)},
            )
        if supplied_ids != expected_ids:
            raise ResultRevisionIntegrityError(
                'Outcome set does not cover the attempt questions exactly once.',
                details={
                    'attempt_id': str(attempt.pk),
                    'missing': [str(pk) for pk in sorted(expected_ids - supplied_ids, key=str)],
                    'unexpected': [str(pk) for pk in sorted(supplied_ids - expected_ids, key=str)],
                },
            )
