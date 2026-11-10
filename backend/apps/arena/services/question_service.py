"""
Question Service for ZENTIQ Arena.
Authoritative domain service managing Question canonical identity, creation,
retrieval, selectable assessment queries, and series deprecation.
Preserves strict scope boundaries: does not perform draft composition or version lifecycle transitions.
"""
from decimal import Decimal
import re
import secrets
import string
from typing import Any, Optional
import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import F, QuerySet

from apps.arena.models import (
    Question,
    QuestionCompetencyMapping,
    QuestionVersion,
    scan_for_confidential_keys,
)
from .composition_service import QuestionCompositionService, resolve_competency
from .exceptions import (
    ActiveVersionIntegrityError,
    CompetencyNotFoundError,
    InactiveCompetencyError,
    QuestionAlreadyDeprecatedError,
    QuestionCodeGenerationError,
    QuestionDeprecatedError,
    QuestionNoActiveVersionError,
    QuestionNotFoundError,
    QuestionPermissionDeniedError,
    QuestionValidationError,
    TagNotFoundError,
)
from .permissions import (
    check_authenticated_and_active,
    check_can_create_question,
    check_can_deprecate_question,
    check_can_view_question,
)

MAX_CODE_RETRIES = 5


def generate_canonical_code(competency_code: str) -> str:
    """
    Generates a standardized canonical question code in format:
    QST-{CLEAN_COMPETENCY_PREFIX}-{RANDOM_SUFFIX}

    Rules:
    - Strips trailing numeric version suffixes (e.g. '-01', '-02').
    - Uppercase alphanumeric and hyphens/underscores only.
    - Prefix truncated to a maximum of 25 characters.
    - Suffix: 6 cryptographically secure random alphanumeric characters.
    - Guaranteed length is <= 36 characters (strictly within model max_length=40).
    """
    cleaned = re.sub(r'-\d+$', '', competency_code.strip().upper())
    cleaned = re.sub(r'[^A-Z0-9_-]', '', cleaned)[:25]
    suffix = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
    return f"QST-{cleaned}-{suffix}"


class QuestionService:
    """
    Authoritative domain service for Question canonical identity and series operations.
    """

    @classmethod
    def create_question(
        cls,
        *,
        primary_competency: Any,
        title: str,
        prompt: str,
        question_type: str,
        user: Any,
        difficulty_tier: str = 'INTERMEDIATE',
        bloom_level: str = 'APPLY',
        time_limit_seconds: int = 60,
        content_payload: Optional[Any] = None,
        explanation: str = '',
        tags: Optional[list[str]] = None,
    ) -> tuple[Question, QuestionVersion]:
        """
        Atomically creates a canonical Question anchor, an initial v1 DRAFT QuestionVersion,
        the primary QuestionCompetencyMapping, and optional initial tags.

        Parameters:
            primary_competency: Competency model instance, PK, or UUID. Must be active (is_active=True).
            title: Authoring title for the question premise (max 200 chars).
            prompt: Rich-text/Markdown/LaTeX question stem presented to candidates.
            question_type: Valid question type choice (e.g. 'SINGLE_CHOICE', 'CODE_OUTPUT').
            user: Authenticated and active user. Must possess 'arena.add_question' or superuser status.
            difficulty_tier: Difficulty tier choice (default 'INTERMEDIATE').
            bloom_level: Cognitive depth choice (default 'APPLY').
            time_limit_seconds: Anti-cheat pacing limit (5 to 600 seconds, default 60).
            content_payload: Structured JSON presentation data. None indicates omission and resolves
                             to model default {}. Explicit JSON null is not supported by the model schema.
            explanation: Post-assessment explanation rationale.
            tags: Optional list of pre-existing tag slugs to associate with the v1 version.

        Returns:
            tuple[Question, QuestionVersion]: The persisted Question anchor and v1 DRAFT version.
        """
        check_can_create_question(user)

        comp = resolve_competency(primary_competency)
        if not comp.is_active:
            raise InactiveCompetencyError(
                f"Cannot create question for inactive competency '{comp.code}'.",
                details={'competency_id': str(comp.pk), 'code': comp.code, 'is_active': False},
            )

        # Non-nullable JSONField semantics: None means omitted and resolves to model default {}
        effective_payload = dict() if content_payload is None else content_payload

        # Reject confidential evaluation keys from public presentation payload
        leaked = scan_for_confidential_keys(effective_payload)
        if leaked:
            raise QuestionValidationError(
                f"Confidential evaluation keys are forbidden in public content_payload: {', '.join(leaked)}.",
                details={'leaked_keys': leaked},
            )

        with transaction.atomic():
            question = None
            for attempt in range(MAX_CODE_RETRIES):
                candidate_code = generate_canonical_code(comp.code)
                code_collision_detected = False

                try:
                    with transaction.atomic():  # Creates isolated DB savepoint
                        candidate_question = Question(
                            code=candidate_code,
                            created_by=user,
                            is_deprecated=False,
                        )

                        # 1. Model-level validation check: distinguish unique collision from validation error
                        try:
                            candidate_question.full_clean(exclude=['active_version'])
                        except ValidationError as val_exc:
                            err_dict = getattr(val_exc, 'error_dict', {})
                            code_errors = err_dict.get('code', [])
                            is_unique_collision = any(getattr(err, 'code', None) == 'unique' for err in code_errors)
                            has_other_errors = len(err_dict) > 1 or any(
                                getattr(err, 'code', None) != 'unique' for err in code_errors
                            )

                            if is_unique_collision and not has_other_errors:
                                code_collision_detected = True
                            else:
                                raise QuestionValidationError(
                                    "Question anchor validation failed.",
                                    details=val_exc.message_dict if hasattr(val_exc, 'message_dict') else {'error': str(val_exc)},
                                ) from val_exc

                        if not code_collision_detected:
                            # 2. Database insertion: let IntegrityError escape this atomic block!
                            candidate_question.save(force_insert=True)
                            question = candidate_question
                            break

                except IntegrityError as exc:
                    # Atomic.__exit__ has executed savepoint_rollback(sid). Outer transaction is healthy.
                    if Question.objects.filter(code=candidate_code).exists():
                        # Confirmed: candidate code uniqueness collision
                        if attempt == MAX_CODE_RETRIES - 1:
                            raise QuestionCodeGenerationError(
                                f"Failed to generate a unique question code after {MAX_CODE_RETRIES} attempts.",
                                details={'competency_code': comp.code, 'attempts': MAX_CODE_RETRIES},
                            ) from exc
                        continue
                    else:
                        # Candidate code does not exist: non-code integrity error (e.g. FK failure)
                        raise QuestionValidationError(
                            f"Question anchor persistence failed due to an unexpected database integrity violation: {exc}",
                            details={'error': str(exc)},
                        ) from exc

                if code_collision_detected:
                    if attempt == MAX_CODE_RETRIES - 1:
                        raise QuestionCodeGenerationError(
                            f"Failed to generate a unique question code after {MAX_CODE_RETRIES} attempts.",
                            details={'competency_code': comp.code, 'attempts': MAX_CODE_RETRIES},
                        )
                    continue
            else:
                raise QuestionCodeGenerationError(
                    f"Failed to generate a unique question code after {MAX_CODE_RETRIES} attempts.",
                    details={'competency_code': comp.code, 'attempts': MAX_CODE_RETRIES},
                )

            # 3. Create initial QuestionVersion v1 DRAFT
            version = QuestionVersion(
                question=question,
                version_number=1,
                status='DRAFT',
                title=title,
                prompt=prompt,
                question_type=question_type,
                difficulty_tier=difficulty_tier,
                primary_competency=comp,
                bloom_level=bloom_level,
                time_limit_seconds=time_limit_seconds,
                content_payload=effective_payload,
                explanation=explanation,
                created_by=user,
            )
            try:
                version.full_clean()
            except ValidationError as val_exc:
                raise QuestionValidationError(
                    "QuestionVersion validation failed.",
                    details=val_exc.message_dict if hasattr(val_exc, 'message_dict') else {'error': str(val_exc)},
                ) from val_exc
            version.save()

            # 4. Create primary QuestionCompetencyMapping
            mapping = QuestionCompetencyMapping(
                question_version=version,
                competency=comp,
                weight=Decimal('1.00'),
                is_primary=True,
            )
            try:
                mapping.full_clean()
            except ValidationError as val_exc:
                raise QuestionValidationError(
                    "QuestionCompetencyMapping validation failed.",
                    details=val_exc.message_dict if hasattr(val_exc, 'message_dict') else {'error': str(val_exc)},
                ) from val_exc
            mapping.save()

            # 5. Attach initial tags if provided
            if tags is not None and len(tags) > 0:
                QuestionCompositionService.sync_version_tags(
                    version_id=version.pk,
                    tag_slugs=tags,
                    user=user,
                )

            return question, version

    @classmethod
    def get_question(
        cls,
        question_id_or_code: Any,
        *,
        user: Any,
    ) -> Question:
        """
        Retrieves a canonical Question series for authoring, review, or administrative inspection.
        """
        check_authenticated_and_active(user)

        target = getattr(question_id_or_code, 'pk', question_id_or_code)
        question = None

        if isinstance(target, uuid.UUID):
            question = (
                Question.objects.select_related('active_version', 'active_version__primary_competency')
                .filter(pk=target)
                .first()
            )
        else:
            str_target = str(target).strip()
            try:
                parsed_uuid = uuid.UUID(str_target)
                question = (
                    Question.objects.select_related('active_version', 'active_version__primary_competency')
                    .filter(pk=parsed_uuid)
                    .first()
                )
            except (ValueError, AttributeError):
                question = None

            if not question:
                question = (
                    Question.objects.select_related('active_version', 'active_version__primary_competency')
                    .filter(code=str_target)
                    .first()
                )

        if not question:
            raise QuestionNotFoundError(f"Question '{question_id_or_code}' does not exist.")

        check_can_view_question(user, question)
        return question

    @classmethod
    def get_assessment_question(
        cls,
        question_id: Any,
    ) -> QuestionVersion:
        """
        Trusted internal system retrieval for assessment selection, exam engines, and candidate delivery.
        Machine-to-machine boundary without user RBAC. Validates active published version invariants.
        """
        q_id = getattr(question_id, 'pk', question_id)
        try:
            val_uuid = uuid.UUID(str(q_id))
            question = (
                Question.objects.select_related('active_version', 'active_version__primary_competency')
                .filter(pk=val_uuid)
                .first()
            )
        except (ValueError, AttributeError):
            question = None

        if not question:
            raise QuestionNotFoundError(f"Question '{question_id}' does not exist.")

        if question.is_deprecated:
            raise QuestionDeprecatedError(
                f"Question '{question.code}' is deprecated and cannot be selected for assessments.",
                details={'question_id': str(question.pk), 'code': question.code},
            )

        active_version = question.active_version
        if active_version is None:
            raise QuestionNoActiveVersionError(
                f"Question '{question.code}' does not have an active published version.",
                details={'question_id': str(question.pk), 'code': question.code},
            )

        if active_version.question_id != question.pk:
            raise ActiveVersionIntegrityError(
                f"Active version '{active_version.pk}' does not belong to Question '{question.pk}'.",
                details={'question_id': str(question.pk), 'active_version_id': str(active_version.pk)},
            )

        if active_version.status != 'PUBLISHED':
            raise ActiveVersionIntegrityError(
                f"Active version for Question '{question.code}' has status '{active_version.status}', expected 'PUBLISHED'.",
                details={
                    'question_id': str(question.pk),
                    'active_version_id': str(active_version.pk),
                    'status': active_version.status,
                },
            )

        return active_version

    @classmethod
    def list_selectable_questions(
        cls,
        *,
        competency_id: Optional[Any] = None,
        difficulty_tier: Optional[str] = None,
        question_type: Optional[str] = None,
    ) -> QuerySet[Question]:
        """
        Returns an optimized QuerySet of Question entities eligible for live assessment selection.
        Machine-to-machine trusted internal assessment-selection query. Excludes confidential evaluation data.
        """
        qs = (
            Question.objects.filter(
                is_deprecated=False,
                active_version__isnull=False,
                active_version__question=F('pk'),
                active_version__status='PUBLISHED',
            )
            .select_related('active_version', 'active_version__primary_competency')
        )

        if competency_id is not None:
            c_id = getattr(competency_id, 'pk', competency_id)
            qs = qs.filter(active_version__primary_competency_id=c_id)

        if difficulty_tier is not None:
            qs = qs.filter(active_version__difficulty_tier=difficulty_tier)

        if question_type is not None:
            qs = qs.filter(active_version__question_type=question_type)

        return qs

    @classmethod
    def deprecate_question(
        cls,
        question_id: Any,
        *,
        user: Any,
        strict: bool = False,
    ) -> Question:
        """
        Retires a Question series from future assessment selection.
        Enforces administrative authorization, row locking, and idempotent or strict behavior.
        """
        check_authenticated_and_active(user)

        with transaction.atomic():
            q_id = getattr(question_id, 'pk', question_id)
            try:
                question = Question.objects.select_for_update().get(pk=q_id)
            except (Question.DoesNotExist, ValueError, TypeError) as exc:
                raise QuestionNotFoundError(f"Question '{question_id}' does not exist.") from exc

            check_can_deprecate_question(user, question)

            if question.is_deprecated:
                if strict:
                    raise QuestionAlreadyDeprecatedError(
                        f"Question '{question.code}' is already deprecated.",
                        details={'question_id': str(question.pk), 'code': question.code},
                    )
                return question

            question.is_deprecated = True
            question.active_version = None
            question.clean()
            question.save()
            return question

