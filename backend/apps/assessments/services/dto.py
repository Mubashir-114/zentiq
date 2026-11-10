"""
Data Transfer Objects (DTOs) for ZENTIQ Assessments (Milestone 4A - Phase 2D.2).
Guarantees strict candidate confidentiality: evaluation data, answer keys, scoring rubrics,
explanations, and competency mappings are NEVER included in candidate-facing DTOs.
"""
import copy
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Optional
import uuid

# Forbidden keys that must never leak into candidate-facing presentation payloads
FORBIDDEN_CANDIDATE_PAYLOAD_KEYS = {
    'correct_answer',
    'correct_payload',
    'answer_key',
    'solution',
    'solutions',
    'scoring_rubric',
    'rubric',
    'explanation',
    'explanations',
    'competency',
    'competencies',
    'competency_mapping',
    'points',
    'is_correct',
    'correct',
    'weight',
    'grading_strategy',
    'grading_criteria',
    'notes',
}


def sanitize_candidate_content_payload(payload: Any) -> dict[str, Any]:
    """
    Strips confidential keys and metadata from question content payloads before
    returning to candidate clients.
    """
    if not isinstance(payload, dict):
        return {}

    sanitized = copy.deepcopy(payload)

    # Strip top-level confidential keys
    for key in list(sanitized.keys()):
        if str(key).lower() in FORBIDDEN_CANDIDATE_PAYLOAD_KEYS:
            del sanitized[key]

    # Sanitize choices / options list if present
    options = sanitized.get('options')
    if isinstance(options, list):
        clean_options = []
        for opt in options:
            if isinstance(opt, dict):
                clean_opt = {
                    k: v
                    for k, v in opt.items()
                    if str(k).lower() not in FORBIDDEN_CANDIDATE_PAYLOAD_KEYS
                }
                clean_options.append(clean_opt)
            else:
                clean_options.append(opt)
        sanitized['options'] = clean_options

    return sanitized


@dataclass(frozen=True)
class CandidateQuestionDTO:
    """
    Safe candidate-facing question representation for live assessment attempts.
    Excludes all internal evaluation keys, explanations, and competency mappings.
    """
    attempt_id: uuid.UUID
    attempt_question_id: uuid.UUID
    order_index: int
    question_count: int
    prompt: str
    question_type: str
    content_payload: dict[str, Any]
    time_limit_seconds: Optional[int]
    current_answer: Optional[dict[str, Any]]
    is_answered: bool
    allow_backtracking: bool
    current_order_index: int
    deadline: Optional[datetime]
    time_remaining_seconds: Optional[int]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data['attempt_id'] = str(self.attempt_id)
        data['attempt_question_id'] = str(self.attempt_question_id)
        data['deadline'] = self.deadline.isoformat() if self.deadline else None
        return data


@dataclass(frozen=True)
class AttemptSummaryDTO:
    """
    Summary DTO representing current or finalized attempt execution status.
    """
    attempt_id: uuid.UUID
    assessment_id: uuid.UUID
    assessment_code: str
    assessment_title: str
    version_number: int
    status: str
    attempt_number: int
    started_at: datetime
    completed_at: Optional[datetime]
    deadline: Optional[datetime]
    time_limit_seconds: Optional[int]
    question_count: int
    answer_count: int
    current_order_index: int
    allow_backtracking: bool

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data['attempt_id'] = str(self.attempt_id)
        data['assessment_id'] = str(self.assessment_id)
        data['started_at'] = self.started_at.isoformat() if self.started_at else None
        data['completed_at'] = self.completed_at.isoformat() if self.completed_at else None
        data['deadline'] = self.deadline.isoformat() if self.deadline else None
        return data

