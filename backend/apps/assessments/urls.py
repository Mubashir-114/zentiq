"""
URL Routing for ZENTIQ Assessment Execution REST API (Phase 2D.3).
Provides versioned /api/v1/ endpoints for catalog, attempt lifecycle, navigation,
answering, and skipping.
"""
from django.urls import path

from .views import (
    AssessmentAttemptAnswerView,
    AssessmentAttemptCurrentQuestionView,
    AssessmentAttemptDetailView,
    AssessmentAttemptNavigateView,
    AssessmentAttemptQuestionDetailView,
    AssessmentAttemptSkipView,
    AssessmentAttemptStartView,
    AssessmentAttemptSubmitView,
    AssessmentDetailView,
    AssessmentListView,
)

app_name = 'assessments'

urlpatterns = [
    # Assessment Catalog
    path('assessments/', AssessmentListView.as_view(), name='assessment-list'),
    path('assessments/<uuid:assessment_id>/', AssessmentDetailView.as_view(), name='assessment-detail'),

    # Attempt Start & Resumption (Requires Idempotency-Key header)
    path('assessments/<uuid:assessment_id>/attempts/', AssessmentAttemptStartView.as_view(), name='attempt-start'),

    # Attempt Detail & Lifecycle
    path('assessments/attempts/<uuid:attempt_id>/', AssessmentAttemptDetailView.as_view(), name='attempt-detail'),
    path('assessments/attempts/<uuid:attempt_id>/submit/', AssessmentAttemptSubmitView.as_view(), name='attempt-submit'),

    # Question Navigation & Retrieval
    path('assessments/attempts/<uuid:attempt_id>/navigate/', AssessmentAttemptNavigateView.as_view(), name='attempt-navigate'),
    path('assessments/attempts/<uuid:attempt_id>/current-question/', AssessmentAttemptCurrentQuestionView.as_view(), name='attempt-current-question'),
    path('assessments/attempts/<uuid:attempt_id>/questions/<int:order_index>/', AssessmentAttemptQuestionDetailView.as_view(), name='attempt-question-detail'),

    # Answer Submission & Question Skipping (Option A)
    path('assessments/attempts/<uuid:attempt_id>/questions/<int:order_index>/answer/', AssessmentAttemptAnswerView.as_view(), name='attempt-question-answer'),
    path('assessments/attempts/<uuid:attempt_id>/questions/<int:order_index>/skip/', AssessmentAttemptSkipView.as_view(), name='attempt-question-skip'),
]

