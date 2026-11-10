"""
Assessment Composition and Publication Service for ZENTIQ (Milestone 4A - Phase 2D.2).
Manages Assessment canonical anchors, draft versions, pinned QuestionVersions,
weight rules, contiguous ordering, and atomic publication promotion.
"""
from decimal import Decimal, InvalidOperation
from typing import Any, Optional, Sequence
import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.db.models import F, Max
from django.utils import timezone

from apps.arena.models import Question, QuestionVersion
from apps.assessments.models import (
    Assessment,
    AssessmentVersion,
    AssessmentVersionQuestion,
)
from .concurrency import with_deadlock_retry
from .exceptions import (
    AssessmentDeprecatedError,
    AssessmentNotFoundError,
    AssessmentValidationError,
    AssessmentVersionImmutabilityError,
    AssessmentVersionNotFoundError,
    DuplicateCanonicalQuestionError,
    IncompleteAssessmentVersionError,
    InvalidQuestionOrderError,
    InvalidQuestionWeightError,
    InvalidVersionTransitionError,
    QuestionDeprecatedError,
    QuestionNotPublishedError,
)
from .permissions import check_can_manage_assessment


def normalize_question_weight(value: Any) -> Decimal:
    """
    Validates and converts a question weight to Decimal.
    Rejects booleans, non-numeric strings, NaNs, infinities, and values <= 0.
    """
    if isinstance(value, bool):
        raise InvalidQuestionWeightError("Boolean values are not valid question weights.")
    if value is None:
        raise InvalidQuestionWeightError("Question weight cannot be None.")

    try:
        norm_val = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InvalidQuestionWeightError(
            f"Invalid question weight '{value}': must be a valid positive decimal."
        ) from exc

    if norm_val.is_nan() or norm_val.is_infinite():
        raise InvalidQuestionWeightError("NaN and Infinity are not valid question weights.")

    if norm_val <= Decimal('0.00'):
        raise InvalidQuestionWeightError(
            f"Question weight must be strictly positive (> 0.00), got {norm_val}."
        )

    return norm_val


def lock_assessment_and_version(version_id: Any) -> tuple[Assessment, AssessmentVersion]:
    """
    Acquires exclusive row-level locks in strict hierarchical order:
    1. Lock parent Assessment (select_for_update).
    2. Reload and lock AssessmentVersion (select_for_update).
    """
    v_id = getattr(version_id, 'pk', version_id)
    row = AssessmentVersion.objects.filter(pk=v_id).values('assessment_id').first()
    if not row:
        raise AssessmentVersionNotFoundError(f"AssessmentVersion '{v_id}' does not exist.")

    assessment_id = row['assessment_id']
    try:
        assessment = Assessment.objects.select_for_update().get(pk=assessment_id)
    except Assessment.DoesNotExist as exc:
        raise AssessmentNotFoundError(f"Assessment '{assessment_id}' does not exist.") from exc

    try:
        version = AssessmentVersion.objects.select_for_update().get(pk=v_id)
    except AssessmentVersion.DoesNotExist as exc:
        raise AssessmentVersionNotFoundError(f"AssessmentVersion '{v_id}' does not exist.") from exc

    return assessment, version


class AssessmentCompositionService:
    """
    Authoritative domain service coordinating assessment drafts, versioning,
    pinned question composition, ordering, and publication lifecycle.
    """

    @classmethod
    @with_deadlock_retry()
    def create_assessment(
        cls,
        *,
        code: str,
        title: str,
        description: str = '',
        user: Any = None,
    ) -> Assessment:
        """
        Creates a permanent canonical Assessment anchor.
        """
        check_can_manage_assessment(user)

        if not code or not code.strip():
            raise AssessmentValidationError("Assessment code cannot be empty.")
        if not title or not title.strip():
            raise AssessmentValidationError("Assessment title cannot be empty.")

        clean_code = code.strip().upper()

        with transaction.atomic():
            if Assessment.objects.filter(code=clean_code).exists():
                raise AssessmentValidationError(f"Assessment with code '{clean_code}' already exists.")

            assessment = Assessment(
                code=clean_code,
                title=title.strip(),
                description=description.strip() if description else '',
                created_by=user,
                is_deprecated=False,
            )
            assessment.full_clean(exclude=['active_version'])
            assessment.save()
            return assessment

    @classmethod
    @with_deadlock_retry()
    def update_assessment(
        cls,
        assessment_id: Any,
        *,
        title: Optional[str] = None,
        description: Optional[str] = None,
        user: Any = None,
    ) -> Assessment:
        """
        Updates presentation metadata of an existing Assessment anchor.
        """
        a_id = getattr(assessment_id, 'pk', assessment_id)
        with transaction.atomic():
            try:
                assessment = Assessment.objects.select_for_update().get(pk=a_id)
            except Assessment.DoesNotExist as exc:
                raise AssessmentNotFoundError(f"Assessment '{a_id}' does not exist.") from exc

            check_can_manage_assessment(user, assessment)

            update_fields = ['updated_at']
            if title is not None:
                if not title.strip():
                    raise AssessmentValidationError("Assessment title cannot be empty.")
                assessment.title = title.strip()
                update_fields.append('title')

            if description is not None:
                assessment.description = description.strip()
                update_fields.append('description')

            assessment.full_clean(exclude=['active_version'] if not assessment.active_version_id else None)
            assessment.save(update_fields=update_fields)
            return assessment

    @classmethod
    @with_deadlock_retry()
    def deprecate_assessment(
        cls,
        assessment_id: Any,
        *,
        user: Any = None,
    ) -> Assessment:
        """
        Retires an Assessment series from active catalog presentation and attempts.
        Transactionally unsets active_version and marks is_deprecated=True.
        """
        a_id = getattr(assessment_id, 'pk', assessment_id)
        with transaction.atomic():
            try:
                assessment = Assessment.objects.select_for_update().get(pk=a_id)
            except Assessment.DoesNotExist as exc:
                raise AssessmentNotFoundError(f"Assessment '{a_id}' does not exist.") from exc

            check_can_manage_assessment(user, assessment)

            if assessment.is_deprecated:
                return assessment

            assessment.is_deprecated = True
            assessment.active_version = None
            assessment.save(update_fields=['is_deprecated', 'active_version', 'updated_at'])
            return assessment

    @classmethod
    @with_deadlock_retry()
    def create_draft_version(
        cls,
        assessment_id: Any,
        *,
        title: str,
        description: str = '',
        time_limit_seconds: Optional[int] = None,
        allow_backtracking: bool = True,
        change_summary: str = '',
        user: Any = None,
    ) -> AssessmentVersion:
        """
        Creates a new DRAFT AssessmentVersion for an Assessment series.
        Acquires exclusive lock on parent Assessment to serialize version creation.
        """
        a_id = getattr(assessment_id, 'pk', assessment_id)
        with transaction.atomic():
            try:
                assessment = Assessment.objects.select_for_update().get(pk=a_id)
            except Assessment.DoesNotExist as exc:
                raise AssessmentNotFoundError(f"Assessment '{a_id}' does not exist.") from exc

            check_can_manage_assessment(user, assessment)

            if assessment.is_deprecated:
                raise AssessmentDeprecatedError(
                    f"Cannot create new versions for deprecated assessment '{assessment.code}'."
                )

            if not title or not title.strip():
                raise AssessmentValidationError("Assessment version title cannot be empty.")

            if time_limit_seconds is not None and time_limit_seconds <= 0:
                raise AssessmentValidationError("Time limit must be a positive integer in seconds or None.")

            # Compute next version number atomically
            max_ver = (
                AssessmentVersion.objects.filter(assessment=assessment)
                .aggregate(Max('version_number'))['version_number__max']
                or 0
            )
            next_ver = max_ver + 1

            version = AssessmentVersion(
                assessment=assessment,
                version_number=next_ver,
                status='DRAFT',
                title=title.strip(),
                description=description.strip() if description else '',
                time_limit_seconds=time_limit_seconds,
                allow_backtracking=allow_backtracking,
                change_summary=change_summary.strip() if change_summary else '',
                created_by=user,
            )
            version.full_clean()
            version.save()
            return version

    @classmethod
    @with_deadlock_retry()
    def update_draft_version(
        cls,
        version_id: Any,
        *,
        title: Optional[str] = None,
        description: Optional[str] = None,
        time_limit_seconds: Optional[int] = -1,  # Sentinel for default unchanged
        allow_backtracking: Optional[bool] = None,
        change_summary: Optional[str] = None,
        user: Any = None,
    ) -> AssessmentVersion:
        """
        Updates configuration fields of a DRAFT AssessmentVersion.
        Rejects mutations if version is PUBLISHED or ARCHIVED.
        """
        with transaction.atomic():
            assessment, version = lock_assessment_and_version(version_id)
            check_can_manage_assessment(user, assessment)

            if version.status in ('PUBLISHED', 'ARCHIVED'):
                raise AssessmentVersionImmutabilityError(
                    f"Cannot modify version in '{version.status}' status. Create a new draft revision."
                )

            update_fields = ['updated_at']

            if title is not None:
                if not title.strip():
                    raise AssessmentValidationError("Assessment version title cannot be empty.")
                version.title = title.strip()
                update_fields.append('title')

            if description is not None:
                version.description = description.strip()
                update_fields.append('description')

            if time_limit_seconds != -1:
                if time_limit_seconds is not None and time_limit_seconds <= 0:
                    raise AssessmentValidationError("Time limit must be a positive integer in seconds or None.")
                version.time_limit_seconds = time_limit_seconds
                update_fields.append('time_limit_seconds')

            if allow_backtracking is not None:
                version.allow_backtracking = bool(allow_backtracking)
                update_fields.append('allow_backtracking')

            if change_summary is not None:
                version.change_summary = change_summary.strip()
                update_fields.append('change_summary')

            version.full_clean()
            version.save(update_fields=update_fields)
            return version

    @classmethod
    @with_deadlock_retry()
    def add_question_to_version(
        cls,
        version_id: Any,
        question_version_id: Any,
        *,
        order_index: Optional[int] = None,
        weight: Any = Decimal('1.00'),
        user: Any = None,
    ) -> AssessmentVersionQuestion:
        """
        Appends or inserts a pinned QuestionVersion into a DRAFT AssessmentVersion.
        Enforces:
        - Parent Assessment exclusive lock.
        - Version DRAFT status.
        - QuestionVersion must be PUBLISHED.
        - Canonical Question must NOT be deprecated.
        - Deduplication: no two versions of the same canonical Question in the assessment.
        - Positive Decimal weight.
        - Contiguous, collision-free order indices.
        """
        qv_id = getattr(question_version_id, 'pk', question_version_id)
        norm_weight = normalize_question_weight(weight)

        with transaction.atomic():
            assessment, version = lock_assessment_and_version(version_id)
            check_can_manage_assessment(user, assessment)

            if version.status in ('PUBLISHED', 'ARCHIVED'):
                raise AssessmentVersionImmutabilityError(
                    f"Cannot add questions to an assessment version with status '{version.status}'."
                )

            # 1. Resolve canonical question_id for target QuestionVersion
            row = QuestionVersion.objects.filter(pk=qv_id).values('question_id').first()
            if not row:
                raise AssessmentValidationError(f"QuestionVersion '{qv_id}' does not exist.")
            canonical_q_id = row['question_id']

            # 2. Acquire shared lock on canonical Question
            try:
                question = Question.objects.select_for_update(share=True).get(pk=canonical_q_id)
            except Question.DoesNotExist as exc:
                raise AssessmentValidationError(f"Parent Question '{canonical_q_id}' does not exist.") from exc

            # 3. Acquire shared lock on target QuestionVersion
            try:
                qv = (
                    QuestionVersion.objects.select_for_update(share=True)
                    .select_related('question')
                    .get(pk=qv_id)
                )
            except QuestionVersion.DoesNotExist as exc:
                raise AssessmentValidationError(f"QuestionVersion '{qv_id}' does not exist.") from exc

            # 4. Revalidate publication and deprecation while holding locks
            if qv.status != 'PUBLISHED':
                raise QuestionNotPublishedError(
                    f"Cannot add question version '{qv.id}' with status '{qv.status}'. Only PUBLISHED question versions can be added."
                )

            if question.is_deprecated or qv.question.is_deprecated:
                raise QuestionDeprecatedError(
                    f"Cannot add question version '{qv.id}' because parent question '{question.code}' is deprecated."
                )

            # 5. Check for duplicate canonical question
            existing_conflict = (
                AssessmentVersionQuestion.objects.filter(
                    assessment_version=version,
                    question_version__question_id=canonical_q_id,
                ).exists()
            )
            if existing_conflict:
                raise DuplicateCanonicalQuestionError(
                    f"A version of canonical Question '{question.code}' is already included in this assessment version."
                )

            # Determine order_index
            existing_questions = list(
                AssessmentVersionQuestion.objects.filter(assessment_version=version)
                .order_by('order_index')
            )
            max_order = len(existing_questions)

            if order_index is None or order_index > max_order + 1:
                target_order = max_order + 1
            else:
                if order_index < 1:
                    raise InvalidQuestionOrderError("Order index must be an integer >= 1.")
                target_order = order_index

            # If inserting into an occupied slot, shift subsequent questions up
            if target_order <= max_order:
                # Use safe temporary offset +10000 to avoid unique constraint collisions
                AssessmentVersionQuestion.objects.filter(
                    assessment_version=version,
                    order_index__gte=target_order,
                ).update(order_index=F('order_index') + 10000)

                for q in existing_questions:
                    if q.order_index >= target_order:
                        AssessmentVersionQuestion.objects.filter(pk=q.pk).update(
                            order_index=q.order_index + 1
                        )

            avq = AssessmentVersionQuestion(
                assessment_version=version,
                question_version=qv,
                order_index=target_order,
                weight=norm_weight,
            )
            avq.full_clean()
            avq.save()
            return avq

    @classmethod
    @with_deadlock_retry()
    def remove_question_from_version(
        cls,
        version_id: Any,
        question_version_id: Any,
        *,
        user: Any = None,
    ) -> None:
        """
        Removes a pinned QuestionVersion from a DRAFT AssessmentVersion and
        re-compacts remaining questions to contiguous order indices 1..N.
        """
        qv_id = getattr(question_version_id, 'pk', question_version_id)

        with transaction.atomic():
            assessment, version = lock_assessment_and_version(version_id)
            check_can_manage_assessment(user, assessment)

            if version.status in ('PUBLISHED', 'ARCHIVED'):
                raise AssessmentVersionImmutabilityError(
                    f"Cannot remove questions from an assessment version with status '{version.status}'."
                )

            avq = AssessmentVersionQuestion.objects.filter(
                assessment_version=version,
                question_version_id=qv_id,
            ).first()

            if not avq:
                raise AssessmentValidationError(
                    f"QuestionVersion '{qv_id}' is not in this assessment version."
                )

            avq.delete()

            # Re-compact remaining question orders contiguously: 1..N
            remaining = list(
                AssessmentVersionQuestion.objects.filter(assessment_version=version)
                .order_by('order_index')
            )

            # Offset by 10000 to prevent unique collisions
            AssessmentVersionQuestion.objects.filter(assessment_version=version).update(
                order_index=F('order_index') + 10000
            )

            for new_idx, item in enumerate(remaining, start=1):
                AssessmentVersionQuestion.objects.filter(pk=item.pk).update(order_index=new_idx)

    @classmethod
    @with_deadlock_retry()
    def reorder_questions(
        cls,
        version_id: Any,
        question_version_ids: Sequence[Any],
        *,
        user: Any = None,
    ) -> list[AssessmentVersionQuestion]:
        """
        Reorders pinned QuestionVersions in a DRAFT AssessmentVersion to match
        the sequence provided in question_version_ids.
        """
        with transaction.atomic():
            assessment, version = lock_assessment_and_version(version_id)
            check_can_manage_assessment(user, assessment)

            if version.status in ('PUBLISHED', 'ARCHIVED'):
                raise AssessmentVersionImmutabilityError(
                    f"Cannot reorder questions in an assessment version with status '{version.status}'."
                )

            raw_ids = [str(getattr(item, 'pk', item)) for item in question_version_ids]
            existing_questions = {
                str(q.question_version_id): q
                for q in AssessmentVersionQuestion.objects.filter(assessment_version=version)
            }

            if set(raw_ids) != set(existing_questions.keys()) or len(raw_ids) != len(existing_questions):
                raise InvalidQuestionOrderError(
                    "Reorder sequence must contain exactly all question versions currently in the assessment version."
                )

            # Offset by 10000 to prevent intermediate unique constraint collisions
            AssessmentVersionQuestion.objects.filter(assessment_version=version).update(
                order_index=F('order_index') + 10000
            )

            updated = []
            for new_order, qv_str_id in enumerate(raw_ids, start=1):
                item = existing_questions[qv_str_id]
                AssessmentVersionQuestion.objects.filter(pk=item.pk).update(order_index=new_order)
                item.order_index = new_order
                updated.append(item)

            return updated

    @classmethod
    def validate_version_completeness(cls, version: AssessmentVersion) -> None:
        """
        Validates completeness and integrity of an AssessmentVersion prior to publication:
        - Version title must be non-empty.
        - Must contain at least one question.
        - Question order indices must be contiguous [1..N].
        - Pinned QuestionVersions must still exist, be in PUBLISHED status, and not deprecated.
        """
        if not (version.title and version.title.strip()):
            raise IncompleteAssessmentVersionError("Assessment version title cannot be empty.")

        questions = list(
            AssessmentVersionQuestion.objects.filter(assessment_version=version)
            .select_related('question_version', 'question_version__question')
            .order_by('order_index')
        )

        if not questions:
            raise IncompleteAssessmentVersionError(
                "Assessment version must contain at least one question before publication."
            )

        # Verify contiguous 1..N ordering
        for expected_idx, q in enumerate(questions, start=1):
            if q.order_index != expected_idx:
                raise IncompleteAssessmentVersionError(
                    f"Question order indices are not contiguous. Expected {expected_idx}, got {q.order_index}."
                )

            if q.question_version.status != 'PUBLISHED':
                raise QuestionNotPublishedError(
                    f"Pinned QuestionVersion '{q.question_version_id}' is in status '{q.question_version.status}', not PUBLISHED."
                )

            if q.question_version.question.is_deprecated:
                raise QuestionDeprecatedError(
                    f"Pinned QuestionVersion '{q.question_version_id}' belongs to deprecated Question '{q.question_version.question.code}'."
                )

    @classmethod
    @with_deadlock_retry()
    def publish_version(
        cls,
        version_id: Any,
        *,
        user: Any = None,
    ) -> AssessmentVersion:
        """
        Atomically publishes a DRAFT AssessmentVersion and reconciles Assessment.active_version.
        """
        with transaction.atomic():
            assessment, version = lock_assessment_and_version(version_id)
            check_can_manage_assessment(user, assessment)

            if assessment.is_deprecated:
                raise AssessmentDeprecatedError(
                    f"Cannot publish versions for deprecated assessment '{assessment.code}'."
                )

            if version.status != 'DRAFT':
                raise InvalidVersionTransitionError(
                    f"Only DRAFT versions can be published. Current status is '{version.status}'."
                )

            cls.validate_version_completeness(version)

            version.status = 'PUBLISHED'
            version.published_at = timezone.now()
            version.full_clean()
            version.save(update_fields=['status', 'published_at', 'updated_at'])

            # Promote as active_version on parent assessment
            assessment.active_version = version
            assessment.save(update_fields=['active_version', 'updated_at'])
            return version

    @classmethod
    @with_deadlock_retry()
    def archive_version(
        cls,
        version_id: Any,
        *,
        user: Any = None,
    ) -> AssessmentVersion:
        """
        Archives a PUBLISHED AssessmentVersion and reconciles Assessment.active_version.
        """
        with transaction.atomic():
            assessment, version = lock_assessment_and_version(version_id)
            check_can_manage_assessment(user, assessment)

            if version.status != 'PUBLISHED':
                raise InvalidVersionTransitionError(
                    f"Only PUBLISHED versions can be archived. Current status is '{version.status}'."
                )

            version.status = 'ARCHIVED'
            version.save(update_fields=['status', 'updated_at'])

            # Active version reconciliation handled in AssessmentVersion.save(),
            # reload assessment to ensure fresh state
            assessment.refresh_from_db()
            return version

