"""
Serializers for ZENTIQ Assessment Execution REST API (Phase 2D.3).
Provides strictly sanitized candidate representations, lifecycle summaries,
and input validation schemas.
"""
from typing import Any

from rest_framework import serializers

from apps.assessments.models import Assessment
from apps.assessments.services.dto import sanitize_candidate_content_payload


class AssessmentCatalogSerializer(serializers.ModelSerializer):
    """
    Candidate-safe summary of an assessment in the public catalog.
    Excludes internal evaluation rubrics, answer keys, and authoring notes.
    """
    time_limit_seconds = serializers.SerializerMethodField(
        help_text="Time limit in seconds for active version, or null if untimed."
    )
    allow_backtracking = serializers.SerializerMethodField(
        help_text="Whether candidates are permitted to navigate backward."
    )
    question_count = serializers.SerializerMethodField(
        help_text="Total number of pinned questions in active version."
    )

    class Meta:
        model = Assessment
        fields = [
            'id',
            'code',
            'title',
            'description',
            'time_limit_seconds',
            'allow_backtracking',
            'question_count',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields

    def get_time_limit_seconds(self, obj: Assessment) -> int | None:
        if obj.active_version:
            return obj.active_version.time_limit_seconds
        return None

    def get_allow_backtracking(self, obj: Assessment) -> bool:
        if obj.active_version:
            return obj.active_version.allow_backtracking
        return True

    def get_question_count(self, obj: Assessment) -> int:
        if obj.active_version:
            return obj.active_version.questions.count()
        return 0


class AttemptSummarySerializer(serializers.Serializer):
    """
    Candidate-safe representation of an assessment attempt lifecycle status and metrics.
    """
    attempt_id = serializers.UUIDField(help_text="Unique UUID identifier of the attempt.")
    assessment_id = serializers.UUIDField(help_text="UUID of the parent assessment.")
    assessment_code = serializers.CharField(help_text="Canonical code of the assessment.")
    assessment_title = serializers.CharField(help_text="Catalog title of the assessment.")
    version_number = serializers.IntegerField(help_text="Pinned version number.")
    status = serializers.CharField(help_text="Current attempt lifecycle status (IN_PROGRESS, SUBMITTED, EXPIRED, CANCELLED).")
    attempt_number = serializers.IntegerField(help_text="Sequential attempt index for candidate.")
    started_at = serializers.DateTimeField(help_text="UTC timestamp when attempt began.")
    completed_at = serializers.DateTimeField(allow_null=True, help_text="UTC timestamp when attempt concluded.")
    deadline = serializers.DateTimeField(allow_null=True, help_text="Server-authoritative UTC completion deadline.")
    time_limit_seconds = serializers.IntegerField(allow_null=True, help_text="Configured duration in seconds.")
    question_count = serializers.IntegerField(help_text="Total number of questions in attempt.")
    answer_count = serializers.IntegerField(help_text="Number of distinct questions answered.")
    current_order_index = serializers.IntegerField(help_text="Current 1-based question position.")
    allow_backtracking = serializers.BooleanField(help_text="Whether backward navigation is permitted.")


class CandidateQuestionSerializer(serializers.Serializer):
    """
    Strictly sanitized candidate question representation.
    Guarantees zero leakage of correct answers, scoring rubrics, explanations,
    or internal competency mappings.
    """
    attempt_id = serializers.UUIDField(help_text="UUID of the active attempt.")
    attempt_question_id = serializers.UUIDField(help_text="UUID of the attempt question snapshot.")
    order_index = serializers.IntegerField(help_text="1-based presentation sequence number.")
    question_count = serializers.IntegerField(help_text="Total question count in attempt.")
    prompt = serializers.CharField(help_text="Candidate question prompt.")
    question_type = serializers.CharField(help_text="Question type identifier.")
    content_payload = serializers.DictField(help_text="Sanitized question choices and assets.")
    time_limit_seconds = serializers.IntegerField(allow_null=True, help_text="Question-specific time limit in seconds.")
    current_answer = serializers.DictField(allow_null=True, help_text="Current candidate answer payload if already recorded.")
    is_answered = serializers.BooleanField(help_text="Whether candidate has answered this question.")
    allow_backtracking = serializers.BooleanField(help_text="Whether backward navigation is permitted.")
    current_order_index = serializers.IntegerField(help_text="Current active question index.")
    deadline = serializers.DateTimeField(allow_null=True, help_text="Attempt completion deadline.")
    time_remaining_seconds = serializers.IntegerField(allow_null=True, help_text="Seconds remaining until attempt deadline.")

    def to_representation(self, instance: Any) -> dict[str, Any]:
        data = super().to_representation(instance)
        # Defense-in-depth: enforce candidate payload sanitization
        if 'content_payload' in data and isinstance(data['content_payload'], dict):
            data['content_payload'] = sanitize_candidate_content_payload(data['content_payload'])
        return data


class NavigateRequestSerializer(serializers.Serializer):
    """
    Payload schema for candidate navigation between questions.
    """
    order_index = serializers.IntegerField(
        min_value=1,
        required=True,
        help_text="Target 1-based question order index.",
    )


class AssessmentAnswerSubmitSerializer(serializers.Serializer):
    """
    Payload schema for candidate answer submission.
    Requires 'answer_payload' containing the candidate's response dictionary:
    {
        "answer_payload": {
            "selected_option_id": "opt_example"
        }
    }
    """
    answer_payload = serializers.DictField(
        required=True,
        allow_empty=False,
        help_text="Candidate answer payload dict matching the question type schema.",
    )

