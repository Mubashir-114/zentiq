"""
Question Composition Service for ZENTIQ Arena.
Authoritative domain service for managing question version sub-entities on DRAFT versions:
- Confidential QuestionEvaluationData
- Primary and weighted secondary QuestionCompetencyMapping
- Taxonomy-orthogonal Tag associations (QuestionVersionTag)
"""
from decimal import Decimal, InvalidOperation
from typing import Any, Optional
import uuid

from django.contrib.auth import get_user_model
from django.db import transaction

from apps.arena.models import (
    Question,
    QuestionCompetencyMapping,
    QuestionEvaluationData,
    QuestionVersion,
    QuestionVersionTag,
    Tag,
)
from apps.skills.models import Competency
from .exceptions import (
    ArenaServiceError,
    CompetencyMappingInvalidError,
    CompetencyNotFoundError,
    EvaluationDataMissingError,
    QuestionImmutabilityError,
    QuestionNotFoundError,
    QuestionVersionNotFoundError,
    TagNotFoundError,
)
from .permissions import check_can_modify_draft, check_can_view_evaluation_data

User = get_user_model()


def normalize_weight(value: Any, field_name: str = "weight") -> Decimal:
    """
    Safely normalizes and validates a competency weight as a Decimal.

    Enforces:
    - Rejects boolean inputs (isinstance(value, bool)).
    - Rejects None and non-numeric representations.
    - Rejects NaN and Infinity.
    - Enforces bounds: Decimal('0.05') <= weight <= Decimal('1.00').
    - Performs arithmetic exclusively in Decimal space.
    """
    if isinstance(value, bool):
        raise CompetencyMappingInvalidError(
            f"Invalid {field_name}: boolean values are not valid weights."
        )
    if value is None:
        raise CompetencyMappingInvalidError(f"Invalid {field_name}: weight cannot be None.")

    try:
        norm_val = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CompetencyMappingInvalidError(
            f"Invalid {field_name} value '{value}': must be a valid decimal number."
        ) from exc

    if norm_val.is_nan() or norm_val.is_infinite():
        raise CompetencyMappingInvalidError(
            f"Invalid {field_name}: NaN and Infinity values are not permitted."
        )

    if norm_val < Decimal('0.05') or norm_val > Decimal('1.00'):
        raise CompetencyMappingInvalidError(
            f"{field_name} must be between 0.05 and 1.00, got {norm_val}."
        )

    return norm_val


def resolve_competency(competency: Any) -> Competency:
    """
    Reloads the Competency from the database using its primary key to ensure fresh state.
    Raises CompetencyNotFoundError if the record does not exist or has been deleted.
    """
    if competency is None:
        raise CompetencyNotFoundError("Competency cannot be None.")

    competency_id = getattr(competency, 'pk', competency)
    try:
        return Competency.objects.get(pk=competency_id)
    except (Competency.DoesNotExist, ValueError, TypeError) as exc:
        raise CompetencyNotFoundError(
            f"Competency '{competency_id}' does not exist or has been deleted."
        ) from exc


def lock_question_and_version(version_id: Any) -> tuple[Question, QuestionVersion]:
    """
    Acquires row-level locks in a strict hierarchical order to prevent deadlocks:
    1. Resolve question_id from QuestionVersion.
    2. Lock parent Question (select_for_update).
    3. Reload and lock QuestionVersion (select_for_update).

    Raises:
    - QuestionVersionNotFoundError if the version does not exist.
    - QuestionNotFoundError if the parent question does not exist.
    """
    v_id = getattr(version_id, 'pk', version_id)

    row = QuestionVersion.objects.filter(pk=v_id).values('question_id').first()
    if not row:
        raise QuestionVersionNotFoundError(f"QuestionVersion '{v_id}' does not exist.")

    question_id = row['question_id']

    try:
        question = Question.objects.select_for_update().get(pk=question_id)
    except Question.DoesNotExist as exc:
        raise QuestionNotFoundError(f"Question '{question_id}' does not exist.") from exc

    try:
        fresh_version = (
            QuestionVersion.objects.select_for_update()
            .select_related('question')
            .get(pk=v_id)
        )
    except QuestionVersion.DoesNotExist as exc:
        raise QuestionVersionNotFoundError(f"QuestionVersion '{v_id}' does not exist.") from exc

    return question, fresh_version


class QuestionCompositionService:
    """
    Authoritative service coordinating sub-entity composition on draft questions.
    All mutating methods execute within atomic transactions, acquire deterministic locks,
    reload fresh state, and enforce model instance-level lifecycle safeguards.
    """

    # -------------------------------------------------------------------------
    # Competency Management
    # -------------------------------------------------------------------------

    @classmethod
    def set_primary_competency(
        cls,
        version_id: Any,
        competency: Any,
        weight: Optional[Any] = None,
        user: Optional[User] = None,
    ) -> tuple[QuestionVersion, QuestionCompetencyMapping]:
        """
        Sets the primary competency for a DRAFT question version and reconciles
        its primary competency mapping.

        Invariants enforced:
        - Version must be in DRAFT status.
        - User must be authorized (can_modify_draft).
        - Competency must exist and be freshly resolved.
        - Exactly one primary mapping is maintained matching version.primary_competency.
        - If the new primary competency already existed as a secondary mapping,
          the secondary mapping is automatically removed.
        - Preserves existing model-level primary weight behavior: if weight is not specified,
          preserves the existing primary mapping weight or falls back to model default (1.00).
        - Primary competency weight is strictly excluded from aggregate secondary calculations.
        """
        with transaction.atomic():
            question, version = lock_question_and_version(version_id)
            if version.status != 'DRAFT':
                raise QuestionImmutabilityError(
                    f"QuestionVersion is in '{version.status}' status. "
                    "Composition modifications are permitted only on DRAFT versions."
                )
            check_can_modify_draft(user, version)

            comp = resolve_competency(competency)

            # Reload all existing mappings under lock
            existing_mappings = list(
                QuestionCompetencyMapping.objects.select_for_update()
                .filter(question_version=version)
            )

            existing_primary = next((m for m in existing_mappings if m.is_primary), None)
            existing_secondary = next(
                (m for m in existing_mappings if not m.is_primary and m.competency_id == comp.pk),
                None,
            )

            # Prevent primary competency from remaining as a secondary mapping
            if existing_secondary:
                existing_secondary.delete()

            # Update QuestionVersion primary_competency
            version.primary_competency = comp
            version.clean()
            version.save()

            # Determine primary mapping weight
            if weight is not None:
                norm_weight = normalize_weight(weight, field_name="primary competency weight")
            elif existing_primary:
                norm_weight = existing_primary.weight
            else:
                norm_weight = Decimal('1.00')

            # Reconcile primary mapping instance
            if existing_primary:
                existing_primary.competency = comp
                existing_primary.weight = norm_weight
                existing_primary.clean()
                existing_primary.save()
                primary_mapping = existing_primary
            else:
                primary_mapping = QuestionCompetencyMapping(
                    question_version=version,
                    competency=comp,
                    is_primary=True,
                    weight=norm_weight,
                )
                primary_mapping.clean()
                primary_mapping.save()

            return version, primary_mapping

    @classmethod
    def add_secondary_competency(
        cls,
        version_id: Any,
        competency: Any,
        weight: Any,
        user: Optional[User] = None,
    ) -> QuestionCompetencyMapping:
        """
        Attaches a secondary competency mapping to a DRAFT question version.

        Invariants enforced:
        - Version must be in DRAFT status.
        - User must be authorized (can_modify_draft).
        - Competency must exist and cannot match primary_competency.
        - Competency cannot already be mapped to this version.
        - Weight must be between 0.05 and 1.00.
        - Sum of all secondary weights on this version must not exceed 1.00.
        - Primary competency weight is excluded from this aggregate check.
        """
        with transaction.atomic():
            question, version = lock_question_and_version(version_id)
            if version.status != 'DRAFT':
                raise QuestionImmutabilityError(
                    f"QuestionVersion is in '{version.status}' status. "
                    "Composition modifications are permitted only on DRAFT versions."
                )
            check_can_modify_draft(user, version)

            comp = resolve_competency(competency)
            norm_weight = normalize_weight(weight, field_name="secondary competency weight")

            # Reload and lock existing mappings
            existing_mappings = list(
                QuestionCompetencyMapping.objects.select_for_update()
                .filter(question_version=version)
            )

            if comp.pk == version.primary_competency_id:
                raise CompetencyMappingInvalidError(
                    f"Competency '{comp.code}' is the primary competency for this version "
                    "and cannot be mapped as a secondary competency."
                )

            if any(m.competency_id == comp.pk for m in existing_mappings):
                raise CompetencyMappingInvalidError(
                    f"Competency '{comp.code}' is already mapped to this question version."
                )

            current_secondary_sum = sum(
                (m.weight for m in existing_mappings if not m.is_primary),
                Decimal('0.00'),
            )
            proposed_total = current_secondary_sum + norm_weight
            if proposed_total > Decimal('1.00'):
                raise CompetencyMappingInvalidError(
                    f"Aggregate secondary competency weight {proposed_total} exceeds "
                    f"the maximum allowed of 1.00 (current secondary total: {current_secondary_sum}, "
                    f"proposed addition: {norm_weight})."
                )

            mapping = QuestionCompetencyMapping(
                question_version=version,
                competency=comp,
                is_primary=False,
                weight=norm_weight,
            )
            mapping.clean()
            mapping.save()
            return mapping

    @classmethod
    def update_secondary_competency_weight(
        cls,
        version_id: Any,
        competency: Any,
        weight: Any,
        user: Optional[User] = None,
    ) -> QuestionCompetencyMapping:
        """
        Updates the weight of an existing secondary competency mapping on a DRAFT version.

        Invariants enforced:
        - Version must be in DRAFT status.
        - User must be authorized (can_modify_draft).
        - Competency must exist and have an active secondary mapping on this version.
        - New weight must be between 0.05 and 1.00.
        - Sum of all secondary weights (substituting the new weight) must not exceed 1.00.
        """
        with transaction.atomic():
            question, version = lock_question_and_version(version_id)
            if version.status != 'DRAFT':
                raise QuestionImmutabilityError(
                    f"QuestionVersion is in '{version.status}' status. "
                    "Composition modifications are permitted only on DRAFT versions."
                )
            check_can_modify_draft(user, version)

            comp = resolve_competency(competency)
            norm_weight = normalize_weight(weight, field_name="secondary competency weight")

            existing_mappings = list(
                QuestionCompetencyMapping.objects.select_for_update()
                .filter(question_version=version)
            )

            target = next(
                (m for m in existing_mappings if not m.is_primary and m.competency_id == comp.pk),
                None,
            )
            if not target:
                raise CompetencyMappingInvalidError(
                    f"Secondary competency mapping for '{comp.code}' does not exist on this version."
                )

            other_secondary_sum = sum(
                (m.weight for m in existing_mappings if not m.is_primary and m.pk != target.pk),
                Decimal('0.00'),
            )
            proposed_total = other_secondary_sum + norm_weight
            if proposed_total > Decimal('1.00'):
                raise CompetencyMappingInvalidError(
                    f"Aggregate secondary competency weight {proposed_total} exceeds "
                    f"the maximum allowed of 1.00 (other secondary total: {other_secondary_sum}, "
                    f"proposed weight: {norm_weight})."
                )

            target.weight = norm_weight
            target.clean()
            target.save()
            return target

    @classmethod
    def remove_secondary_competency(
        cls,
        version_id: Any,
        competency: Any,
        user: Optional[User] = None,
    ) -> None:
        """
        Removes an existing secondary competency mapping from a DRAFT version.

        Invariants enforced:
        - Version must be in DRAFT status.
        - User must be authorized (can_modify_draft).
        - Competency must exist and have an active secondary mapping on this version.
        - Primary competency mapping cannot be removed via this method.
        - Deletion is performed at instance level (instance.delete()).
        """
        with transaction.atomic():
            question, version = lock_question_and_version(version_id)
            if version.status != 'DRAFT':
                raise QuestionImmutabilityError(
                    f"QuestionVersion is in '{version.status}' status. "
                    "Composition modifications are permitted only on DRAFT versions."
                )
            check_can_modify_draft(user, version)

            comp = resolve_competency(competency)

            existing_mappings = list(
                QuestionCompetencyMapping.objects.select_for_update()
                .filter(question_version=version)
            )

            if any(m.is_primary and m.competency_id == comp.pk for m in existing_mappings):
                raise CompetencyMappingInvalidError(
                    f"Competency '{comp.code}' is the primary competency mapping. "
                    "It cannot be removed using remove_secondary_competency()."
                )

            target = next(
                (m for m in existing_mappings if not m.is_primary and m.competency_id == comp.pk),
                None,
            )
            if not target:
                raise CompetencyMappingInvalidError(
                    f"Secondary competency mapping for '{comp.code}' does not exist on this version."
                )

            target.delete()

    @classmethod
    def set_secondary_competencies(
        cls,
        version_id: Any,
        mappings_spec: list[dict[str, Any]],
        user: Optional[User] = None,
    ) -> list[QuestionCompetencyMapping]:
        """
        Performs atomic batch replacement / synchronization of all secondary competencies
        for a DRAFT question version.

        Invariants enforced:
        - Version must be in DRAFT status.
        - User must be authorized (can_modify_draft).
        - Input list cannot contain duplicate competencies.
        - No competency in the spec may match primary_competency.
        - Each weight must be between 0.05 and 1.00.
        - Sum of all weights in the proposed spec must not exceed 1.00.
        - Entire proposed mapping state is validated BEFORE applying any mutations.
        - Mutations use instance-level delete() and save() within a single atomic transaction.
        """
        with transaction.atomic():
            question, version = lock_question_and_version(version_id)
            if version.status != 'DRAFT':
                raise QuestionImmutabilityError(
                    f"QuestionVersion is in '{version.status}' status. "
                    "Composition modifications are permitted only on DRAFT versions."
                )
            check_can_modify_draft(user, version)

            # Pre-validate specifications before database writes
            seen_comp_pks = set()
            resolved_specs: list[tuple[Competency, Decimal]] = []
            total_secondary_weight = Decimal('0.00')

            for idx, item in enumerate(mappings_spec):
                if not isinstance(item, dict):
                    raise CompetencyMappingInvalidError(
                        f"Invalid specification at index {idx}: must be a dictionary."
                    )
                if 'competency' not in item or 'weight' not in item:
                    raise CompetencyMappingInvalidError(
                        f"Specification at index {idx} must contain 'competency' and 'weight'."
                    )

                comp = resolve_competency(item['competency'])

                if comp.pk in seen_comp_pks:
                    raise CompetencyMappingInvalidError(
                        f"Duplicate competency '{comp.code}' in secondary competency specifications."
                    )
                seen_comp_pks.add(comp.pk)

                if comp.pk == version.primary_competency_id:
                    raise CompetencyMappingInvalidError(
                        f"Competency '{comp.code}' is the primary competency for this version "
                        "and cannot be added as a secondary competency."
                    )

                norm_weight = normalize_weight(
                    item['weight'],
                    field_name=f"weight at index {idx} for competency '{comp.code}'",
                )
                total_secondary_weight += norm_weight
                resolved_specs.append((comp, norm_weight))

            if total_secondary_weight > Decimal('1.00'):
                raise CompetencyMappingInvalidError(
                    f"Aggregate secondary competency weight {total_secondary_weight} exceeds "
                    "the maximum allowed of 1.00."
                )

            # Reload existing mappings under lock
            existing_mappings = list(
                QuestionCompetencyMapping.objects.select_for_update()
                .filter(question_version=version)
            )

            existing_secondaries = {
                m.competency_id: m for m in existing_mappings if not m.is_primary
            }

            # 1. Instance-level deletion of unreferenced secondary mappings
            for comp_id, mapping in list(existing_secondaries.items()):
                if comp_id not in seen_comp_pks:
                    mapping.delete()

            # 2. Instance-level update or creation
            result: list[QuestionCompetencyMapping] = []
            for comp, norm_weight in resolved_specs:
                if comp.pk in existing_secondaries:
                    mapping = existing_secondaries[comp.pk]
                    if mapping.weight != norm_weight:
                        mapping.weight = norm_weight
                        mapping.clean()
                        mapping.save()
                    result.append(mapping)
                else:
                    mapping = QuestionCompetencyMapping(
                        question_version=version,
                        competency=comp,
                        is_primary=False,
                        weight=norm_weight,
                    )
                    mapping.clean()
                    mapping.save()
                    result.append(mapping)

            return result

    @classmethod
    def get_competency_mappings(cls, version_id: Any) -> list[QuestionCompetencyMapping]:
        """
        Retrieves all competency mappings for a question version, ordered with primary first.
        """
        v_id = getattr(version_id, 'pk', version_id)
        return list(
            QuestionCompetencyMapping.objects.filter(question_version_id=v_id)
            .select_related('competency')
            .order_by('-is_primary', 'competency__code')
        )

    # -------------------------------------------------------------------------
    # Evaluation Data Management
    # -------------------------------------------------------------------------

    @classmethod
    def set_evaluation_data(
        cls,
        version_id: Any,
        grading_strategy: str,
        correct_payload: Any,
        scoring_rubric: Optional[dict[str, Any]] = None,
        user: Optional[User] = None,
    ) -> QuestionEvaluationData:
        """
        Configures or updates confidential QuestionEvaluationData for a DRAFT question version.

        Invariants enforced:
        - Version must be in DRAFT status.
        - User must be authorized (can_modify_draft).
        - grading_strategy must be explicitly validated against QuestionEvaluationData.STRATEGY_CHOICES.
        - correct_payload is typed as Any, preserving JSON-compatibility without restricting to dict.
        - scoring_rubric defaults to an empty dict if omitted.
        - Saves via instance-level save() inside an atomic transaction.
        """
        with transaction.atomic():
            question, version = lock_question_and_version(version_id)
            if version.status != 'DRAFT':
                raise QuestionImmutabilityError(
                    f"QuestionVersion is in '{version.status}' status. "
                    "Composition modifications are permitted only on DRAFT versions."
                )
            check_can_modify_draft(user, version)

            # Explicit choices validation
            valid_strategies = {choice[0] for choice in QuestionEvaluationData.STRATEGY_CHOICES}
            if grading_strategy not in valid_strategies:
                raise ArenaServiceError(
                    f"Invalid grading strategy '{grading_strategy}'. "
                    f"Valid strategies are: {sorted(list(valid_strategies))}.",
                    details={
                        'valid_strategies': sorted(list(valid_strategies)),
                        'provided': grading_strategy,
                    },
                )

            rubric = scoring_rubric if scoring_rubric is not None else {}

            eval_data = (
                QuestionEvaluationData.objects.select_for_update()
                .filter(question_version=version)
                .first()
            )

            if eval_data:
                eval_data.grading_strategy = grading_strategy
                eval_data.correct_payload = correct_payload
                eval_data.scoring_rubric = rubric
                eval_data.clean()
                eval_data.save()
            else:
                eval_data = QuestionEvaluationData(
                    question_version=version,
                    grading_strategy=grading_strategy,
                    correct_payload=correct_payload,
                    scoring_rubric=rubric,
                )
                eval_data.clean()
                eval_data.save()

            return eval_data

    @classmethod
    def get_evaluation_data(
        cls,
        version_id: Any,
        user: Optional[User] = None,
    ) -> QuestionEvaluationData:
        """
        Retrieves confidential evaluation data for an authorized user.

        Invariants enforced:
        - Confidential data isolation: User must satisfy check_can_view_evaluation_data.
        - Regular assessment players and unauthorized users cannot retrieve evaluation data.
        - Raises EvaluationDataMissingError if not configured.
        """
        v_id = getattr(version_id, 'pk', version_id)
        version = QuestionVersion.objects.filter(pk=v_id).select_related('question').first()
        if not version:
            raise QuestionVersionNotFoundError(f"QuestionVersion '{v_id}' does not exist.")

        check_can_view_evaluation_data(user, version)

        eval_data = QuestionEvaluationData.objects.filter(question_version=version).first()
        if not eval_data:
            raise EvaluationDataMissingError(
                f"No evaluation data has been configured for QuestionVersion '{v_id}'."
            )

        return eval_data

    # -------------------------------------------------------------------------
    # Tag Synchronization
    # -------------------------------------------------------------------------

    @classmethod
    def sync_version_tags(
        cls,
        version_id: Any,
        tag_slugs: list[str],
        user: Optional[User] = None,
    ) -> list[Tag]:
        """
        Synchronizes Tag associations on a DRAFT question version.

        Invariants enforced:
        - Version must be in DRAFT status.
        - User must be authorized (can_modify_draft).
        - tag_slugs are deterministically deduplicated.
        - If any requested tag slug does not exist, raises TagNotFoundError without committing partial changes.
        - Removed tags are deleted via instance-level delete().
        - Added tags are created via instance-level save().
        - All operations execute within a single atomic transaction.
        """
        with transaction.atomic():
            question, version = lock_question_and_version(version_id)
            if version.status != 'DRAFT':
                raise QuestionImmutabilityError(
                    f"QuestionVersion is in '{version.status}' status. "
                    "Composition modifications are permitted only on DRAFT versions."
                )
            check_can_modify_draft(user, version)

            # Deduplicate tag_slugs deterministically
            seen_slugs = set()
            deduped_slugs: list[str] = []
            for s in tag_slugs:
                if s not in seen_slugs:
                    seen_slugs.add(s)
                    deduped_slugs.append(s)

            # Validate that all slugs exist in the database
            found_tags = list(Tag.objects.filter(slug__in=deduped_slugs))
            found_slug_map = {t.slug: t for t in found_tags}

            missing_slugs = [s for s in deduped_slugs if s not in found_slug_map]
            if missing_slugs:
                raise TagNotFoundError(
                    f"The following tag slugs do not exist: {missing_slugs}.",
                    details={'missing_slugs': missing_slugs},
                )

            # Reload existing associations under lock
            current_tags = list(
                QuestionVersionTag.objects.select_for_update()
                .filter(question_version=version)
                .select_related('tag')
            )
            current_by_slug = {vt.tag.slug: vt for vt in current_tags}

            # 1. Instance-level deletion of unneeded tags
            target_slug_set = set(deduped_slugs)
            for slug, vt in list(current_by_slug.items()):
                if slug not in target_slug_set:
                    vt.delete()

            # 2. Instance-level creation of new tags
            result_tags: list[Tag] = []
            for slug in deduped_slugs:
                tag = found_slug_map[slug]
                if slug not in current_by_slug:
                    new_vt = QuestionVersionTag(question_version=version, tag=tag)
                    new_vt.clean()
                    new_vt.save()
                result_tags.append(tag)

            return result_tags

