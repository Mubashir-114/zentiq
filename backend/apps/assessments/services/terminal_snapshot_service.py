"""
Terminal transition policy snapshot service (Phase 2E.2).

The snapshot is the sole authority for evaluation / mastery / XP eligibility.
It is created only inside the terminal transition transaction and is insert-only.
"""
from ..models import RESULT_TERMINAL_STATUSES, AttemptTerminalSnapshot
from .evaluation.policy import POLICY_VERSION, resolve_terminal_flags
from .exceptions import (
    AssessmentValidationError,
    TerminalSnapshotConflictError,
)


class TerminalSnapshotService:
    """Records the immutable eligibility decision for a terminal attempt."""

    @classmethod
    def record(cls, attempt, *, decision_source: str) -> AttemptTerminalSnapshot:
        terminal_status = attempt.status
        if terminal_status not in RESULT_TERMINAL_STATUSES:
            raise AssessmentValidationError(
                f"Cannot snapshot eligibility for attempt in status '{terminal_status}'."
            )

        existing = AttemptTerminalSnapshot.objects.filter(attempt=attempt).first()
        if existing is not None:
            if existing.terminal_status != terminal_status:
                raise TerminalSnapshotConflictError(
                    'Attempt already has a terminal snapshot with a different status.',
                    details={
                        'attempt_id': str(attempt.pk),
                        'existing_status': existing.terminal_status,
                        'requested_status': terminal_status,
                    },
                )
            return existing

        flags = resolve_terminal_flags(terminal_status)
        return AttemptTerminalSnapshot.objects.create(
            attempt=attempt,
            terminal_status=terminal_status,
            decision_source=decision_source,
            policy_version=POLICY_VERSION,
            **flags,
        )
