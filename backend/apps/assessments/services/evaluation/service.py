"""
Attempt evaluation orchestration (Phase 2E.2).

Reads frozen attempt snapshots and frozen question evaluation data, delegates the
decision to the pure evaluator, and persists an immutable result revision through
``ResultRevisionService``. The whole operation runs inside the caller's
transaction (``submit_attempt``), so a class-C/D failure rolls back both the
terminal transition and the result.

Eligibility comes exclusively from the immutable terminal policy snapshot.
"""
from typing import Any, Optional

from django.db import transaction

from apps.arena.models import QuestionEvaluationData

from ...models import (
    RESULT_TERMINAL_STATUSES,
    AssessmentAttempt,
    AttemptAnswer,
    AttemptEvent,
    AttemptQuestion,
    AttemptResultRevision,
)
from ..result_revision_service import ResultRevisionService
from .dto import (
    ABSENCE_EMPTY_SUBMISSION,
    ABSENCE_NOT_REACHED,
    ABSENCE_SKIPPED,
    ANSWER_ABSENT,
    ANSWER_PRESENT,
    QuestionEvaluationInput,
)
from .evaluator import evaluate_question
from .policy import EVALUATOR_VERSION, POLICY_VERSION
from ..exceptions import (
    AssessmentValidationError,
    AttemptRedactedError,
    ResultRevisionIntegrityError,
)


class AttemptEvaluationService:
    """Evaluates a terminal attempt into an immutable result revision."""

    @classmethod
    def evaluate_attempt(
        cls,
        attempt: Any,
        *,
        actor: Any = None,
        reason: str = 'INITIAL_EVALUATION',
        reason_detail: str = '',
        expected_revision_id: Any = None,
    ) -> Optional[AttemptResultRevision]:
        attempt_id = getattr(attempt, 'pk', attempt)

        with transaction.atomic():
            locked_attempt = (
                AssessmentAttempt.objects.select_for_update()
                .select_related('assessment', 'assessment_version', 'terminal_snapshot')
                .get(pk=attempt_id)
            )

            if locked_attempt.status not in RESULT_TERMINAL_STATUSES:
                raise AssessmentValidationError(
                    f"Cannot evaluate attempt in status '{locked_attempt.status}'."
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
                    details={'attempt_id': str(locked_attempt.pk)},
                )

            # Independent eligibility flag: evaluation of EXPIRED/CANCELLED is not
            # enabled (D-02a unresolved), so those attempts produce no revision.
            if not snapshot.evaluate_eligible:
                return None

            attempt_questions = list(
                AttemptQuestion.objects.filter(attempt=locked_attempt)
                .select_related('question_version')
                .order_by('order_index')
            )
            if not attempt_questions:
                # An attempt without questions cannot satisfy the total-weight
                # invariant; no result revision is fabricated.
                return None

            answers = {
                answer.attempt_question_id: answer
                for answer in AttemptAnswer.objects.filter(
                    attempt_question__attempt=locked_attempt
                )
            }

            if any(answer.redacted_at is not None for answer in answers.values()):
                raise AttemptRedactedError(
                    'This attempt contains redacted answer content and cannot be evaluated.',
                    details={'attempt_id': str(locked_attempt.pk)},
                )

            skipped_ids = set()
            for event in AttemptEvent.objects.filter(
                attempt=locked_attempt, event_type='QUESTION_SKIPPED'
            ):
                payload = event.payload or {}
                value = payload.get('attempt_question_id')
                if value:
                    skipped_ids.add(str(value))

            eval_data_map = {
                data.question_version_id: data
                for data in QuestionEvaluationData.objects.filter(
                    question_version_id__in=[
                        aq.question_version_id for aq in attempt_questions
                    ]
                )
            }

            inputs = []
            for aq in attempt_questions:
                answer = answers.get(aq.pk)
                presence, absence_reason = cls._resolve_presence(aq, answer, skipped_ids)
                eval_data = eval_data_map.get(aq.question_version_id)

                inputs.append(
                    QuestionEvaluationInput(
                        attempt_question_id=aq.pk,
                        weight=aq.weight,
                        question_type=aq.question_type_snapshot or aq.question_version.question_type,
                        grading_strategy=(
                            eval_data.grading_strategy if eval_data else ''
                        ),
                        correct_payload=(eval_data.correct_payload if eval_data else None),
                        scoring_rubric=(eval_data.scoring_rubric if eval_data else None),
                        answer_payload=(answer.answer_payload if answer and presence == ANSWER_PRESENT else None),
                        answer_presence=presence,
                        absence_reason=absence_reason,
                        answer_redacted=bool(answer and answer.redacted_at),
                    )
                )

            outcomes = [evaluate_question(inp) for inp in inputs]

            # Deterministic safety: a malformed input set must never be persisted.
            for outcome in outcomes:
                if outcome.outcome in ('UNGRADED', 'PENDING_MANUAL') and not outcome.ungraded_reason:
                    raise AssessmentValidationError(
                        'Undecided outcomes must carry an ungraded reason.',
                        details={'attempt_question_id': str(outcome.attempt_question_id)},
                    )

            return ResultRevisionService.record_revision(
                locked_attempt,
                outcomes,
                actor=actor,
                reason=reason,
                reason_detail=reason_detail,
                expected_revision_id=expected_revision_id,
                scoring_policy_version=POLICY_VERSION,
                evaluator_version=EVALUATOR_VERSION,
            )

    @classmethod
    def _resolve_presence(cls, aq: AttemptQuestion, answer: Any, skipped_ids: set[str]) -> tuple[str, str]:
        if answer is not None and answer.is_answered and answer.answer_payload:
            return ANSWER_PRESENT, ''
        if answer is None:
            if str(aq.pk) in skipped_ids:
                return ANSWER_ABSENT, ABSENCE_SKIPPED
            return ANSWER_ABSENT, ABSENCE_NOT_REACHED
        return ANSWER_ABSENT, ABSENCE_EMPTY_SUBMISSION
