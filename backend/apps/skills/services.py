"""
Domain services for ZENTIQ Skill Taxonomy.
Provides authoritative operations for prerequisite graph manipulation,
cycle detection, and dependency validation.
"""
from collections import deque
from decimal import Decimal
from typing import List, Optional

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from .models import Competency, SkillPrerequisite


class PrerequisiteService:
    """
    Authoritative service for managing prerequisite relationships between competencies.
    Enforces Directed Acyclic Graph (DAG) invariants, preventing circular dependencies.
    """

    @classmethod
    def has_cycle(cls, competency: Competency, prerequisite_competency: Competency) -> bool:
        """
        Determines whether adding an edge (competency requires prerequisite_competency)
        would introduce a cycle into the prerequisite graph.

        Traverses the graph starting from prerequisite_competency along existing prerequisite edges.
        If competency is reachable, adding the proposed edge would complete a directed cycle.

        Concurrency limitation:
        Graph validation executes read queries against the current database state. In highly
        concurrent multi-worker environments, two simultaneous requests creating mutual dependencies
        (e.g. A->B and B->A) could both pass read-time validation before either transaction commits.
        Because prerequisite authoring is a low-frequency administrative action, application-level
        BFS traversal within an atomic transaction provides the optimal balance of performance
        and integrity without table-level database locks.
        """
        if competency.pk == prerequisite_competency.pk:
            return True

        visited = set()
        queue = deque([prerequisite_competency.pk])

        while queue:
            current_id = queue.popleft()
            if current_id == competency.pk:
                return True

            if current_id not in visited:
                visited.add(current_id)
                # Fetch all prerequisite competency IDs that current_id requires
                prereq_ids = SkillPrerequisite.objects.filter(
                    competency_id=current_id
                ).values_list('prerequisite_competency_id', flat=True)
                for next_id in prereq_ids:
                    if next_id not in visited:
                        queue.append(next_id)

        return False

    @classmethod
    def validate_prerequisite_addition(
        cls,
        competency: Competency,
        prerequisite_competency: Competency,
    ) -> None:
        """
        Validates that adding prerequisite_competency as a prerequisite for competency
        satisfies all graph and domain rules. Raises ValidationError on violation.
        """
        if not competency or not prerequisite_competency:
            return

        if competency.pk == prerequisite_competency.pk:
            raise ValidationError(
                _("A competency cannot require itself as a prerequisite.")
            )

        if cls.has_cycle(competency, prerequisite_competency):
            raise ValidationError(
                _(
                    f"Circular prerequisite detected: adding [{prerequisite_competency.code}] "
                    f"as a prerequisite for [{competency.code}] creates a closed dependency cycle."
                )
            )

    @classmethod
    def create_prerequisite(
        cls,
        competency: Competency,
        prerequisite_competency: Competency,
        min_mastery_percentage: Decimal = Decimal('70.00'),
    ) -> SkillPrerequisite:
        """
        Creates a new verified prerequisite edge within an atomic transaction.
        Authoritative entry point for programmatic prerequisite creation.
        """
        with transaction.atomic():
            cls.validate_prerequisite_addition(competency, prerequisite_competency)
            prerequisite = SkillPrerequisite.objects.create(
                competency=competency,
                prerequisite_competency=prerequisite_competency,
                min_mastery_percentage=min_mastery_percentage,
            )
            return prerequisite

    @classmethod
    def get_prerequisite_chain(cls, competency: Competency) -> List[Competency]:
        """
        Returns all recursive prerequisite competencies required to unlock the given competency,
        ordered topologically.
        """
        chain = []
        visited = set()
        queue = deque([competency.pk])

        while queue:
            current_id = queue.popleft()
            if current_id not in visited:
                visited.add(current_id)
                prereqs = Competency.objects.filter(
                    dependent_competencies__competency_id=current_id
                ).select_related('subdomain__domain')
                for p in prereqs:
                    if p.pk not in visited:
                        chain.append(p)
                        queue.append(p.pk)

        return chain

