"""
Question Versioning Service for ZENTIQ Arena.
Authoritative domain service governing QuestionVersion lifecycle transitions,
source-based draft generation, review gates, atomic publication promotion,
and active version pointer reconciliation.
"""
import copy
from decimal import Decimal
from typing import Any, Optional

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from apps.arena.models import (
    Question,
    QuestionCompetencyMapping,
    QuestionEvaluationData,
    QuestionVersion,
    scan_for_confidential_keys,
)
from apps.skills.models import Competency
from .composition_service import (
    QuestionCompositionService,
    lock_question_and_version,
    resolve_competency,
)
from .exceptions import (
    ActiveVersionIntegrityError,
    EvaluationDataMissingError,
    InactiveCompetencyError,
    IncompleteQuestionVersionError,
    InvalidLifecycleTransitionError,
    MissingRequiredDraftFieldsError,
    QuestionDeprecatedError,
    QuestionImmutabilityError,
    QuestionNotFoundError,
    QuestionPermissionDeniedError,
    QuestionValidationError,
    QuestionVersionNotFoundError,
    RejectionReasonRequiredError,
    SelfPublicationNotAllowedError,
    SourceVersionMismatchError,
)
from .permissions import (
    check_authenticated_and_active,
    check_can_archive_or_deprecate_version,
    check_can_create_draft_version,
    check_can_publish_version,
    check_can_return_to_draft,
    check_can_submit_for_review,
    check_can_update_draft_version,
    check_can_withdraw_from_review,
)


def validate_version_completeness(version: QuestionVersion) -> None:
    """
    Validates completeness of a QuestionVersion prior to review submission or publication.
    Enforces model-supported requirements and schema validations without inventing
    additional artificial constraints (e.g. no arbitrary minimum string lengths).
    """
    # 1. Core model field requirements
    if not (version.title and version.title.strip()):
        raise IncompleteQuestionVersionError("Question version title cannot be empty.")

    if not (version.prompt and version.prompt.strip()):
        raise IncompleteQuestionVersionError("Question version prompt cannot be empty.")

    valid_types = {c[0] for c in QuestionVersion.TYPE_CHOICES}
    if version.question_type not in valid_types:
        raise IncompleteQuestionVersionError(
            f"Invalid question type '{version.question_type}'. Valid choices are: {sorted(list(valid_types))}."
        )

    if not version.primary_competency_id:
        raise IncompleteQuestionVersionError("Question version must reference a primary competency.")

    if not version.primary_competency.is_active:
        raise IncompleteQuestionVersionError(
            f"Primary competency '{version.primary_competency.code}' is inactive."
        )

    try:
        version.full_clean()
    except ValidationError as val_exc:
        raise IncompleteQuestionVersionError(
            "Question version data failed validation.",
            details=val_exc.message_dict if hasattr(val_exc, 'message_dict') else {'error': str(val_exc)},
        ) from val_exc

    # 2. Primary competency mapping consistency
    primary_mapping = QuestionCompetencyMapping.objects.filter(
        question_version=version,
        is_primary=True,
    ).first()
    if not primary_mapping:
        raise IncompleteQuestionVersionError("Question version lacks a primary competency mapping.")

    if primary_mapping.competency_id != version.primary_competency_id:
        raise IncompleteQuestionVersionError(
            "Primary competency mapping does not match version primary competency."
        )

    # 3. Confidential evaluation data existence and schema validation
    eval_data = getattr(version, 'evaluation_data', None)
    if not eval_data:
        eval_data = QuestionEvaluationData.objects.filter(question_version=version).first()

    if not eval_data:
        raise EvaluationDataMissingError(
            f"No evaluation data has been configured for QuestionVersion '{version.pk}'."
        )

    valid_strategies = {c[0] for c in QuestionEvaluationData.STRATEGY_CHOICES}
    if eval_data.grading_strategy not in valid_strategies:
        raise IncompleteQuestionVersionError(
            f"Invalid grading strategy '{eval_data.grading_strategy}'."
        )

    if eval_data.correct_payload is None:
        raise IncompleteQuestionVersionError("Evaluation data correct_payload cannot be None.")

    try:
        eval_data.full_clean(exclude=['correct_payload'])
    except ValidationError as val_exc:
        raise IncompleteQuestionVersionError(
            "Evaluation data failed validation.",
            details=val_exc.message_dict if hasattr(val_exc, 'message_dict') else {'error': str(val_exc)},
        ) from val_exc


class QuestionVersioningService:
    """
    Authoritative domain service governing QuestionVersion lifecycle transitions,
    source-based draft generation, review gates, atomic publication promotion,
    and active version pointer reconciliation.
    """

    @classmethod
    def create_draft_version(
        cls,
        question_id: Any,
        *,
        user: Any,
        source_version_id: Optional[Any] = None,
        title: Optional[str] = None,
        prompt: Optional[str] = None,
        question_type: Optional[str] = None,
        primary_competency: Optional[Any] = None,
        difficulty_tier: Optional[str] = None,
        bloom_level: Optional[str] = None,
        time_limit_seconds: Optional[int] = None,
        content_payload: Optional[Any] = None,
        explanation: Optional[str] = None,
        change_summary: Optional[str] = None,
    ) -> QuestionVersion:
        """
        Creates a new immutable QuestionVersion in DRAFT status for the given Question.

        Invariants enforced:
        - Parent Question is locked first (select_for_update).
        - Rejects permanently deprecated Question series (QuestionDeprecatedError).
        - Source Resolution:
          - Explicit source_version_id: validated to belong to target Question series.
          - Omitted source_version_id: inspects question.active_version.
            If active_version is non-null, validates integrity (must exist, belong to question, status PUBLISHED).
            If corrupt, raises ActiveVersionIntegrityError (never silently falls back).
            If valid, active_version is used as default clone source.
          - If active_version is genuinely None: creates draft from scratch requiring title, prompt,
            question_type, and primary_competency. Raises MissingRequiredDraftFieldsError if any missing.
        - JSON Payload Compatibility: content_payload accepts JSON dicts, lists, and primitives.
          None means omitted and inherits from source (or defaults to {} on scratch draft).
        - Safe Composition Cloning: Mappings, tags, and evaluation data are cloned into independent records
          via QuestionCompositionService within the same atomic transaction.
        - Confidential keys in content_payload are rejected.
        - Monotonic version numbering: max(version_number) + 1 under Question lock.
        """
        check_can_create_draft_version(user)

        with transaction.atomic():
            q_id = getattr(question_id, 'pk', question_id)
            try:
                question = Question.objects.select_for_update().get(pk=q_id)
            except (Question.DoesNotExist, ValueError, TypeError) as exc:
                raise QuestionNotFoundError(f"Question '{question_id}' does not exist.") from exc

            if question.is_deprecated:
                raise QuestionDeprecatedError(
                    f"Question '{question.code}' is deprecated and cannot accept new drafts.",
                    details={'question_id': str(question.pk), 'code': question.code},
                )

            source_version = None
            if source_version_id is not None:
                s_id = getattr(source_version_id, 'pk', source_version_id)
                try:
                    source_version = QuestionVersion.objects.get(pk=s_id)
                except (QuestionVersion.DoesNotExist, ValueError, TypeError) as exc:
                    raise QuestionVersionNotFoundError(
                        f"Source QuestionVersion '{source_version_id}' does not exist."
                    ) from exc

                if source_version.question_id != question.pk:
                    raise SourceVersionMismatchError(
                        f"Source version '{s_id}' does not belong to Question '{question.pk}'.",
                        details={'question_id': str(question.pk), 'source_version_id': str(s_id)},
                    )
            else:
                # Default source resolution via question.active_version
                if question.active_version_id is not None:
                    av = QuestionVersion.objects.filter(pk=question.active_version_id).first()
                    if not av or av.question_id != question.pk or av.status != 'PUBLISHED':
                        raise ActiveVersionIntegrityError(
                            f"Active version pointer for Question '{question.code}' violates integrity constraints.",
                            details={
                                'question_id': str(question.pk),
                                'active_version_id': str(question.active_version_id),
                                'found_status': av.status if av else None,
                            },
                        )
                    source_version = av
                else:
                    source_version = None

            # Resolve effective attributes
            if source_version is not None:
                eff_title = title if title is not None else source_version.title
                eff_prompt = prompt if prompt is not None else source_version.prompt
                eff_question_type = question_type if question_type is not None else source_version.question_type
                eff_comp = (
                    resolve_competency(primary_competency)
                    if primary_competency is not None
                    else source_version.primary_competency
                )
                eff_difficulty = difficulty_tier if difficulty_tier is not None else source_version.difficulty_tier
                eff_bloom = bloom_level if bloom_level is not None else source_version.bloom_level
                eff_time_limit = time_limit_seconds if time_limit_seconds is not None else source_version.time_limit_seconds
                eff_payload = copy.deepcopy(source_version.content_payload) if content_payload is None else content_payload
                eff_explanation = explanation if explanation is not None else source_version.explanation
                eff_change_summary = change_summary if change_summary is not None else ""
            else:
                # Scratch creation without a source
                missing = []
                if not title:
                    missing.append('title')
                if not prompt:
                    missing.append('prompt')
                if not question_type:
                    missing.append('question_type')
                if not primary_competency:
                    missing.append('primary_competency')

                if missing:
                    raise MissingRequiredDraftFieldsError(
                        f"Draft creation without a source requires: {', '.join(missing)}.",
                        details={'missing_fields': missing},
                    )

                eff_title = title
                eff_prompt = prompt
                eff_question_type = question_type
                eff_comp = resolve_competency(primary_competency)
                eff_difficulty = difficulty_tier if difficulty_tier is not None else 'INTERMEDIATE'
                eff_bloom = bloom_level if bloom_level is not None else 'APPLY'
                eff_time_limit = time_limit_seconds if time_limit_seconds is not None else 60
                eff_payload = dict() if content_payload is None else content_payload
                eff_explanation = explanation if explanation is not None else ""
                eff_change_summary = change_summary if change_summary is not None else ""

            if not eff_comp.is_active:
                raise InactiveCompetencyError(
                    f"Cannot create draft referencing inactive competency '{eff_comp.code}'.",
                    details={'competency_id': str(eff_comp.pk), 'code': eff_comp.code},
                )

            leaked = scan_for_confidential_keys(eff_payload)
            if leaked:
                raise QuestionValidationError(
                    f"Confidential evaluation keys are forbidden in public content_payload: {', '.join(leaked)}.",
                    details={'leaked_keys': leaked},
                )

            max_version = (
                QuestionVersion.objects.filter(question=question)
                .aggregate(models.Max('version_number'))['version_number__max']
                or 0
            )
            next_version_number = max_version + 1

            new_draft = QuestionVersion(
                question=question,
                version_number=next_version_number,
                status='DRAFT',
                title=eff_title,
                prompt=eff_prompt,
                question_type=eff_question_type,
                difficulty_tier=eff_difficulty,
                primary_competency=eff_comp,
                bloom_level=eff_bloom,
                time_limit_seconds=eff_time_limit,
                content_payload=eff_payload,
                explanation=eff_explanation,
                change_summary=eff_change_summary,
                created_by=user,
            )
            try:
                new_draft.full_clean()
            except ValidationError as val_exc:
                raise QuestionValidationError(
                    "QuestionVersion validation failed.",
                    details=val_exc.message_dict if hasattr(val_exc, 'message_dict') else {'error': str(val_exc)},
                ) from val_exc
            new_draft.save()

            # Safe composition cloning via QuestionCompositionService
            if source_version is not None:
                source_primary = QuestionCompetencyMapping.objects.filter(
                    question_version=source_version,
                    is_primary=True,
                ).first()
                primary_weight = source_primary.weight if source_primary else Decimal('1.00')

                QuestionCompositionService.set_primary_competency(
                    version_id=new_draft.pk,
                    competency=eff_comp,
                    weight=primary_weight,
                    user=user,
                )

                source_secondaries = QuestionCompetencyMapping.objects.filter(
                    question_version=source_version,
                    is_primary=False,
                )
                secondary_specs = [
                    {'competency': m.competency_id, 'weight': m.weight}
                    for m in source_secondaries
                    if m.competency_id != eff_comp.pk
                ]
                if secondary_specs:
                    QuestionCompositionService.set_secondary_competencies(
                        version_id=new_draft.pk,
                        mappings_spec=secondary_specs,
                        user=user,
                    )

                source_tags = list(source_version.tags.values_list('slug', flat=True))
                if source_tags:
                    QuestionCompositionService.sync_version_tags(
                        version_id=new_draft.pk,
                        tag_slugs=source_tags,
                        user=user,
                    )

                source_eval = QuestionEvaluationData.objects.filter(question_version=source_version).first()
                if source_eval:
                    QuestionCompositionService.set_evaluation_data(
                        version_id=new_draft.pk,
                        grading_strategy=source_eval.grading_strategy,
                        correct_payload=copy.deepcopy(source_eval.correct_payload),
                        scoring_rubric=copy.deepcopy(source_eval.scoring_rubric),
                        user=user,
                    )
            else:
                QuestionCompositionService.set_primary_competency(
                    version_id=new_draft.pk,
                    competency=eff_comp,
                    weight=Decimal('1.00'),
                    user=user,
                )

            return new_draft

    @classmethod
    def update_draft_version(
        cls,
        version_id: Any,
        *,
        user: Any,
        title: Optional[str] = None,
        prompt: Optional[str] = None,
        question_type: Optional[str] = None,
        primary_competency: Optional[Any] = None,
        difficulty_tier: Optional[str] = None,
        bloom_level: Optional[str] = None,
        time_limit_seconds: Optional[int] = None,
        content_payload: Optional[Any] = None,
        explanation: Optional[str] = None,
        change_summary: Optional[str] = None,
    ) -> QuestionVersion:
        """
        Updates core content and metadata fields on an existing DRAFT QuestionVersion.

        Invariants enforced:
        - Target version must be in DRAFT status (QuestionImmutabilityError).
        - Authorization: Version author, arena.change_questionversion, or active superuser.
        - content_payload supports dict, list, and primitives. None preserves existing payload untouched.
        - Primary competency updates reconcile primary mapping automatically.
        """
        with transaction.atomic():
            question, version = lock_question_and_version(version_id)
            if version.status != 'DRAFT':
                raise QuestionImmutabilityError(
                    f"QuestionVersion is in '{version.status}' status. "
                    "Content modifications are permitted only on DRAFT versions."
                )

            check_can_update_draft_version(user, version)

            if title is not None:
                version.title = title
            if prompt is not None:
                version.prompt = prompt
            if question_type is not None:
                version.question_type = question_type
            if difficulty_tier is not None:
                version.difficulty_tier = difficulty_tier
            if bloom_level is not None:
                version.bloom_level = bloom_level
            if time_limit_seconds is not None:
                version.time_limit_seconds = time_limit_seconds
            if explanation is not None:
                version.explanation = explanation
            if change_summary is not None:
                version.change_summary = change_summary

            if content_payload is not None:
                leaked = scan_for_confidential_keys(content_payload)
                if leaked:
                    raise QuestionValidationError(
                        f"Confidential evaluation keys are forbidden in public content_payload: {', '.join(leaked)}.",
                        details={'leaked_keys': leaked},
                    )
                version.content_payload = content_payload

            if primary_competency is not None:
                comp = resolve_competency(primary_competency)
                if not comp.is_active:
                    raise InactiveCompetencyError(
                        f"Cannot update draft referencing inactive competency '{comp.code}'.",
                        details={'competency_id': str(comp.pk), 'code': comp.code},
                    )
                version.primary_competency = comp
                QuestionCompositionService.set_primary_competency(
                    version_id=version.pk,
                    competency=comp,
                    user=user,
                )

            try:
                version.full_clean()
            except ValidationError as val_exc:
                raise QuestionValidationError(
                    "QuestionVersion validation failed.",
                    details=val_exc.message_dict if hasattr(val_exc, 'message_dict') else {'error': str(val_exc)},
                ) from val_exc

            version.save()
            return version

    @classmethod
    def submit_for_review(
        cls,
        version_id: Any,
        *,
        user: Any,
    ) -> QuestionVersion:
        """
        Transitions a QuestionVersion from DRAFT to IN_REVIEW.

        Invariants enforced:
        - Current status must be DRAFT (InvalidLifecycleTransitionError).
        - Authorization: Version author, arena.change_questionversion, or active superuser.
        - Validates review completeness before transition.
        """
        with transaction.atomic():
            question, version = lock_question_and_version(version_id)
            if version.status != 'DRAFT':
                raise InvalidLifecycleTransitionError(
                    f"Cannot submit QuestionVersion in '{version.status}' status for review. "
                    "Only DRAFT versions can be submitted."
                )

            check_can_submit_for_review(user, version)
            validate_version_completeness(version)

            version.status = 'IN_REVIEW'
            version.clean()
            version.save()
            return version

    @classmethod
    def return_to_draft(
        cls,
        version_id: Any,
        *,
        user: Any,
        rejection_reason: str,
    ) -> QuestionVersion:
        """
        Transitions a QuestionVersion from IN_REVIEW back to DRAFT based on reviewer rejection.

        Invariants enforced:
        - Current status must be IN_REVIEW (InvalidLifecycleTransitionError).
        - Authorization: Reviewer (arena.publish_questionversion), admin (arena.change_questionversion),
          or non-author superuser. Authors cannot self-reject via this reviewer path.
        - rejection_reason is mandatory and non-empty (RejectionReasonRequiredError).
        - Records rejection reason in change_summary ("Review rejected: <reason>").
        """
        with transaction.atomic():
            question, version = lock_question_and_version(version_id)
            if version.status != 'IN_REVIEW':
                raise InvalidLifecycleTransitionError(
                    f"Cannot return QuestionVersion in '{version.status}' status to draft. "
                    "Only IN_REVIEW versions can be returned to draft."
                )

            check_can_return_to_draft(user, version)

            if not rejection_reason or not rejection_reason.strip():
                raise RejectionReasonRequiredError(
                    "A non-empty rejection reason is required to return a version to draft."
                )

            version.status = 'DRAFT'
            version.change_summary = f"Review rejected: {rejection_reason.strip()}"[:255]
            version.clean()
            version.save()
            return version

    @classmethod
    def withdraw_from_review(
        cls,
        version_id: Any,
        *,
        user: Any,
        reason: Optional[str] = None,
    ) -> QuestionVersion:
        """
        Transitions a QuestionVersion from IN_REVIEW back to DRAFT via author withdrawal.

        Invariants enforced:
        - Current status must be IN_REVIEW (InvalidLifecycleTransitionError).
        - Strictly restricted to the version author (version.created_by_id == user.pk).
          Non-author superusers are rejected to protect audit trail integrity.
        - reason is optional.
        - Records withdrawal in change_summary ("Withdrawn by author: <reason>" or "Withdrawn by author").
        """
        with transaction.atomic():
            question, version = lock_question_and_version(version_id)
            if version.status != 'IN_REVIEW':
                raise InvalidLifecycleTransitionError(
                    f"Cannot withdraw QuestionVersion in '{version.status}' status. "
                    "Only IN_REVIEW versions can be withdrawn by author."
                )

            check_can_withdraw_from_review(user, version)

            version.status = 'DRAFT'
            if reason and reason.strip():
                version.change_summary = f"Withdrawn by author: {reason.strip()}"[:255]
            else:
                version.change_summary = "Withdrawn by author"

            version.clean()
            version.save()
            return version

    @classmethod
    def publish_version(
        cls,
        version_id: Any,
        *,
        user: Any,
    ) -> QuestionVersion:
        """
        Transitions a QuestionVersion from IN_REVIEW to PUBLISHED and atomically promotes
        it to become the parent Question's active_version.

        Invariants enforced:
        - Parent Question is locked first, then QuestionVersion.
        - Rejects permanently deprecated Question series (QuestionDeprecatedError).
        - Current status must be IN_REVIEW (InvalidLifecycleTransitionError).
        - Separation of duties: Authors (even superusers) CANNOT publish their own versions (SelfPublicationNotAllowedError).
        - Authorization: Requires arena.publish_questionversion or non-author active superuser.
        - Re-validates review completeness immediately prior to publication.
        - Sets version.status = 'PUBLISHED', published_at = timezone.now().
        - Atomically sets question.active_version = version.
        """
        with transaction.atomic():
            question, version = lock_question_and_version(version_id)

            if question.is_deprecated:
                raise QuestionDeprecatedError(
                    f"Question '{question.code}' is deprecated and cannot publish versions.",
                    details={'question_id': str(question.pk), 'code': question.code},
                )

            if version.status != 'IN_REVIEW':
                raise InvalidLifecycleTransitionError(
                    f"Cannot publish QuestionVersion with status '{version.status}'. "
                    "Only IN_REVIEW versions can be published."
                )

            check_can_publish_version(user, version)
            validate_version_completeness(version)

            version.status = 'PUBLISHED'
            version.published_at = timezone.now()
            version.clean()
            version.save()

            question.active_version = version
            question.clean()
            question.save(update_fields=['active_version', 'updated_at'])

            return version

    @classmethod
    def archive_version(
        cls,
        version_id: Any,
        *,
        user: Any,
    ) -> QuestionVersion:
        """
        Transitions a QuestionVersion from PUBLISHED to ARCHIVED.

        Invariants enforced:
        - Current status must be PUBLISHED (InvalidLifecycleTransitionError).
        - Authorization: arena.change_questionversion or active superuser.
        - Model hook in QuestionVersion.save() reconciles active pointer:
          - If target is active on active Question, selects highest remaining PUBLISHED version, or None.
          - If parent Question is deprecated (is_deprecated=True), active_version remains None.
          - If target was not active, pointer is undisturbed.
        """
        with transaction.atomic():
            question, version = lock_question_and_version(version_id)
            if version.status != 'PUBLISHED':
                raise InvalidLifecycleTransitionError(
                    f"Cannot archive QuestionVersion with status '{version.status}'. "
                    "Only PUBLISHED versions can be archived."
                )

            check_can_archive_or_deprecate_version(user)

            version.status = 'ARCHIVED'
            version.clean()
            version.save()
            return version

    @classmethod
    def deprecate_version(
        cls,
        version_id: Any,
        *,
        user: Any,
    ) -> QuestionVersion:
        """
        Transitions a QuestionVersion from PUBLISHED or ARCHIVED to DEPRECATED.

        Invariants enforced:
        - Current status must be PUBLISHED or ARCHIVED (InvalidLifecycleTransitionError).
        - Authorization: arena.change_questionversion or active superuser.
        - Model hook in QuestionVersion.save() reconciles active pointer.
        - Terminal state: cannot transition further.
        """
        with transaction.atomic():
            question, version = lock_question_and_version(version_id)
            if version.status not in ('PUBLISHED', 'ARCHIVED'):
                raise InvalidLifecycleTransitionError(
                    f"Cannot deprecate QuestionVersion with status '{version.status}'. "
                    "Permitted only from PUBLISHED or ARCHIVED status."
                )

            check_can_archive_or_deprecate_version(user)

            version.status = 'DEPRECATED'
            version.clean()
            version.save()
            return version
