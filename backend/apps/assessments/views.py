"""
API Views for ZENTIQ Assessment Execution REST API (Phase 2D.3).
Provides secure, candidate-safe REST endpoints for assessment catalog browsing,
attempt creation with mandatory idempotency, question navigation, answering, skipping,
and authoritative lifecycle submission.
"""
import uuid
from typing import Any

from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import permissions, serializers, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.assessments.exceptions import assessment_exception_handler
from apps.assessments.models import Assessment
from apps.assessments.serializers import (
    AssessmentAnswerSubmitSerializer,
    AssessmentCatalogSerializer,
    AttemptSummarySerializer,
    CandidateQuestionSerializer,
    NavigateRequestSerializer,
)
from apps.assessments.services import (
    AssessmentAnswerService,
    AssessmentAttemptService,
    AssessmentDeprecatedError,
    AssessmentNavigationService,
    AssessmentNoActiveVersionError,
    AssessmentNotFoundError,
    AssessmentValidationError,
    build_attempt_summary,
)

# Standard inline error schema for OpenAPI documentation
API_ERROR_SCHEMA = inline_serializer(
    name="AssessmentApiErrorEnvelope",
    fields={
        "error": inline_serializer(
            name="AssessmentApiErrorBody",
            fields={
                "code": serializers.CharField(),
                "message": serializers.CharField(),
                "details": serializers.DictField(required=False, allow_null=True),
            },
        )
    },
)


class BaseAssessmentView(APIView):
    """
    Base view for all candidate-facing assessment endpoints.
    Enforces session authentication, candidate active status,
    and attaches the assessment-scoped exception handler adapter.
    """
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get_exception_handler(self):
        return assessment_exception_handler


# ==============================================================================
# Catalog Endpoints
# ==============================================================================

class AssessmentListView(BaseAssessmentView):
    """
    GET /api/v1/assessments/
    Lists published, active assessments available to candidates.
    Excludes deprecated assessments and assessments without active published versions.
    """

    @extend_schema(
        tags=['assessments'],
        summary="List Available Assessments",
        description="Retrieves catalog list of active, published assessments available for attempts.",
        responses={
            200: AssessmentCatalogSerializer(many=True),
            401: API_ERROR_SCHEMA,
        },
    )
    def get(self, request, *args, **kwargs):
        assessments = (
            Assessment.objects.filter(
                is_deprecated=False,
                active_version__isnull=False,
                active_version__status='PUBLISHED',
            )
            .select_related('active_version')
            .prefetch_related('active_version__questions')
            .order_by('code')
        )
        serializer = AssessmentCatalogSerializer(assessments, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AssessmentDetailView(BaseAssessmentView):
    """
    GET /api/v1/assessments/{assessment_id}/
    Retrieves catalog metadata for a specific published assessment.
    """

    @extend_schema(
        tags=['assessments'],
        summary="Retrieve Assessment Catalog Detail",
        description="Retrieves metadata, timing, and question count for a published assessment.",
        responses={
            200: AssessmentCatalogSerializer,
            400: API_ERROR_SCHEMA,
            401: API_ERROR_SCHEMA,
            404: API_ERROR_SCHEMA,
            409: API_ERROR_SCHEMA,
        },
    )
    def get(self, request, assessment_id: uuid.UUID, *args, **kwargs):
        try:
            assessment = (
                Assessment.objects.select_related('active_version')
                .prefetch_related('active_version__questions')
                .get(pk=assessment_id)
            )
        except Assessment.DoesNotExist as exc:
            raise AssessmentNotFoundError(f"Assessment '{assessment_id}' does not exist.") from exc

        if assessment.is_deprecated:
            raise AssessmentDeprecatedError(
                f"Assessment '{assessment.code}' is deprecated and cannot be accessed."
            )

        if not assessment.active_version or assessment.active_version.status != 'PUBLISHED':
            raise AssessmentNoActiveVersionError(
                f"Assessment '{assessment.code}' does not have an active published version."
            )

        serializer = AssessmentCatalogSerializer(assessment)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ==============================================================================
# Attempt Start Endpoint
# ==============================================================================

class AssessmentAttemptStartView(BaseAssessmentView):
    """
    POST /api/v1/assessments/{assessment_id}/attempts/
    Starts a new assessment attempt or resumes an existing one using an Idempotency-Key.
    Requires the 'Idempotency-Key' HTTP header (1-64 non-empty chars).
    """

    @extend_schema(
        tags=['assessments'],
        summary="Start or Resume Assessment Attempt",
        description=(
            "Initiates a new assessment attempt or idempotently replays an existing attempt. "
            "Requires the 'Idempotency-Key' HTTP header (1–64 characters). "
            "Returns 201 Created on new attempt creation or 200 OK on idempotent resumption."
        ),
        request=None,
        parameters=[
            OpenApiParameter(
                name='Idempotency-Key',
                type=str,
                location=OpenApiParameter.HEADER,
                required=True,
                description="Unique client idempotency key (1–64 non-empty characters).",
            ),
        ],
        responses={
            201: AttemptSummarySerializer,
            200: AttemptSummarySerializer,
            400: API_ERROR_SCHEMA,
            401: API_ERROR_SCHEMA,
            404: API_ERROR_SCHEMA,
            409: API_ERROR_SCHEMA,
            503: API_ERROR_SCHEMA,
        },
    )
    def post(self, request, assessment_id: uuid.UUID, *args, **kwargs):
        # Mandatory Idempotency-Key header extraction and validation
        raw_key = request.headers.get('Idempotency-Key') or request.META.get('HTTP_IDEMPOTENCY_KEY')
        if not raw_key or not isinstance(raw_key, str) or not raw_key.strip():
            raise AssessmentValidationError(
                "Missing required 'Idempotency-Key' HTTP header.",
                details={'idempotency_key': ["Header 'Idempotency-Key' must be a non-empty string of 1 to 64 characters."]},
            )

        clean_key = raw_key.strip()
        if len(clean_key) > 64:
            raise AssessmentValidationError(
                "Invalid 'Idempotency-Key' header: length exceeds 64 characters.",
                details={'idempotency_key': ["Idempotency-Key must not exceed 64 characters."]},
            )

        attempt, created = AssessmentAttemptService.start_or_resume_attempt(
            assessment_id=assessment_id,
            user=request.user,
            idempotency_key=clean_key,
        )

        summary = build_attempt_summary(attempt)
        serializer = AttemptSummarySerializer(summary)
        status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(serializer.data, status=status_code)


# ==============================================================================
# Attempt Detail & Lifecycle Endpoints
# ==============================================================================

class AssessmentAttemptDetailView(BaseAssessmentView):
    """
    GET /api/v1/assessments/attempts/{attempt_id}/
    Retrieves current summary status and progress metrics for an attempt.
    Verifies candidate ownership.
    """

    @extend_schema(
        tags=['assessments'],
        summary="Retrieve Attempt Summary",
        description="Retrieves current status, question counts, and deadline metrics for an assessment attempt.",
        responses={
            200: AttemptSummarySerializer,
            401: API_ERROR_SCHEMA,
            403: API_ERROR_SCHEMA,
            404: API_ERROR_SCHEMA,
        },
    )
    def get(self, request, attempt_id: uuid.UUID, *args, **kwargs):
        summary = AssessmentAttemptService.get_attempt_summary(
            attempt_id=attempt_id,
            user=request.user,
        )
        serializer = AttemptSummarySerializer(summary)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AssessmentAttemptSubmitView(BaseAssessmentView):
    """
    POST /api/v1/assessments/attempts/{attempt_id}/submit/
    Authoritatively concludes and submits an in-progress attempt.
    Enforces strict server-side deadline.
    """

    @extend_schema(
        tags=['assessments'],
        summary="Submit Assessment Attempt",
        description="Concludes and submits an in-progress assessment attempt, recording completion metrics.",
        request=None,
        responses={
            200: AttemptSummarySerializer,
            400: API_ERROR_SCHEMA,
            401: API_ERROR_SCHEMA,
            403: API_ERROR_SCHEMA,
            404: API_ERROR_SCHEMA,
            409: API_ERROR_SCHEMA,
            410: API_ERROR_SCHEMA,
        },
    )
    def post(self, request, attempt_id: uuid.UUID, *args, **kwargs):
        summary = AssessmentAttemptService.submit_attempt(
            attempt_id=attempt_id,
            user=request.user,
        )
        serializer = AttemptSummarySerializer(summary)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ==============================================================================
# Navigation & Question Retrieval Endpoints
# ==============================================================================

class AssessmentAttemptNavigateView(BaseAssessmentView):
    """
    POST /api/v1/assessments/attempts/{attempt_id}/navigate/
    Navigates candidate to a specific question order index within an in-progress attempt.
    Enforces forward-only rules when backtracking is disabled.
    """

    @extend_schema(
        tags=['assessments'],
        summary="Navigate to Question",
        description="Updates candidate position to the specified target question order index.",
        request=NavigateRequestSerializer,
        responses={
            200: CandidateQuestionSerializer,
            400: API_ERROR_SCHEMA,
            401: API_ERROR_SCHEMA,
            403: API_ERROR_SCHEMA,
            404: API_ERROR_SCHEMA,
            409: API_ERROR_SCHEMA,
            410: API_ERROR_SCHEMA,
        },
    )
    def post(self, request, attempt_id: uuid.UUID, *args, **kwargs):
        req_serializer = NavigateRequestSerializer(data=request.data)
        req_serializer.is_valid(raise_exception=True)
        target_order = req_serializer.validated_data['order_index']

        dto = AssessmentNavigationService.navigate_to_question(
            attempt_id=attempt_id,
            target_order_index=target_order,
            user=request.user,
        )
        serializer = CandidateQuestionSerializer(dto)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AssessmentAttemptCurrentQuestionView(BaseAssessmentView):
    """
    GET /api/v1/assessments/attempts/{attempt_id}/current-question/
    Retrieves the candidate-safe question DTO for the attempt's current order index.
    """

    @extend_schema(
        tags=['assessments'],
        summary="Retrieve Current Question",
        description="Retrieves the question representation for the attempt's current active question.",
        responses={
            200: CandidateQuestionSerializer,
            400: API_ERROR_SCHEMA,
            401: API_ERROR_SCHEMA,
            403: API_ERROR_SCHEMA,
            404: API_ERROR_SCHEMA,
            409: API_ERROR_SCHEMA,
            410: API_ERROR_SCHEMA,
        },
    )
    def get(self, request, attempt_id: uuid.UUID, *args, **kwargs):
        dto = AssessmentNavigationService.get_current_question(
            attempt_id=attempt_id,
            user=request.user,
        )
        serializer = CandidateQuestionSerializer(dto)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AssessmentAttemptQuestionDetailView(BaseAssessmentView):
    """
    GET /api/v1/assessments/attempts/{attempt_id}/questions/{order_index}/
    Retrieves candidate-safe representation for a specific question order index.
    Enforces backtracking rules: if backtracking is disabled, only current_order_index is accessible.
    """

    @extend_schema(
        tags=['assessments'],
        summary="Retrieve Question by Order Index",
        description="Retrieves candidate-safe question representation for a specific question position.",
        responses={
            200: CandidateQuestionSerializer,
            400: API_ERROR_SCHEMA,
            401: API_ERROR_SCHEMA,
            403: API_ERROR_SCHEMA,
            404: API_ERROR_SCHEMA,
            409: API_ERROR_SCHEMA,
            410: API_ERROR_SCHEMA,
        },
    )
    def get(self, request, attempt_id: uuid.UUID, order_index: int, *args, **kwargs):
        dto = AssessmentNavigationService.get_question_by_order(
            attempt_id=attempt_id,
            order_index=order_index,
            user=request.user,
        )
        serializer = CandidateQuestionSerializer(dto)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ==============================================================================
# Answer & Skip Endpoints (Option A)
# ==============================================================================

class AssessmentAttemptAnswerView(BaseAssessmentView):
    """
    POST /api/v1/assessments/attempts/{attempt_id}/questions/{order_index}/answer/
    Submits candidate answer for the specified question in an in-progress attempt.
    """

    @extend_schema(
        tags=['assessments'],
        summary="Submit Question Answer",
        description="Saves candidate answer for the question, validates payload schema, and updates counters.",
        request=AssessmentAnswerSubmitSerializer,
        responses={
            200: CandidateQuestionSerializer,
            400: API_ERROR_SCHEMA,
            401: API_ERROR_SCHEMA,
            403: API_ERROR_SCHEMA,
            404: API_ERROR_SCHEMA,
            409: API_ERROR_SCHEMA,
            410: API_ERROR_SCHEMA,
        },
    )
    def post(self, request, attempt_id: uuid.UUID, order_index: int, *args, **kwargs):
        submit_serializer = AssessmentAnswerSubmitSerializer(data=request.data)
        submit_serializer.is_valid(raise_exception=True)
        answer_payload = submit_serializer.validated_data['answer_payload']

        dto = AssessmentAnswerService.submit_answer(
            attempt_id=attempt_id,
            question_order_index=order_index,
            answer_payload=answer_payload,
            user=request.user,
        )
        serializer = CandidateQuestionSerializer(dto)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AssessmentAttemptSkipView(BaseAssessmentView):
    """
    POST /api/v1/assessments/attempts/{attempt_id}/questions/{order_index}/skip/
    Explicitly skips answering the specified question.
    """

    @extend_schema(
        tags=['assessments'],
        summary="Skip Question",
        description="Records explicit question skip and advances active question when forward-only is enforced.",
        request=None,
        responses={
            200: CandidateQuestionSerializer,
            400: API_ERROR_SCHEMA,
            401: API_ERROR_SCHEMA,
            403: API_ERROR_SCHEMA,
            404: API_ERROR_SCHEMA,
            409: API_ERROR_SCHEMA,
            410: API_ERROR_SCHEMA,
        },
    )
    def post(self, request, attempt_id: uuid.UUID, order_index: int, *args, **kwargs):
        dto = AssessmentAnswerService.skip_question(
            attempt_id=attempt_id,
            question_order_index=order_index,
            user=request.user,
        )
        serializer = CandidateQuestionSerializer(dto)
        return Response(serializer.data, status=status.HTTP_200_OK)
