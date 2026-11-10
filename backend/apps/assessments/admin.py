"""
Django Admin Configuration for ZENTIQ Assessment Execution Engine.
Application: apps.assessments
"""
from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import (
    ActiveAssessmentReservation,
    Assessment,
    AssessmentAttempt,
    AssessmentVersion,
    AssessmentVersionQuestion,
    AttemptAnswer,
    AttemptEvent,
    AttemptQuestion,
)


class AssessmentVersionInline(admin.TabularInline):
    model = AssessmentVersion
    extra = 0
    fields = ['version_number', 'status', 'title', 'time_limit_seconds', 'allow_backtracking']
    show_change_link = True

    def has_change_permission(self, request, obj=None):
        return True


class AssessmentVersionQuestionInline(admin.TabularInline):
    model = AssessmentVersionQuestion
    extra = 0
    fields = ['order_index', 'question_version', 'weight']
    autocomplete_fields = ['question_version']

    def has_change_permission(self, request, obj=None):
        if obj and obj.status in ('PUBLISHED', 'ARCHIVED'):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj and obj.status in ('PUBLISHED', 'ARCHIVED'):
            return False
        return super().has_delete_permission(request, obj)


@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    list_display = ['code', 'title', 'active_version', 'is_deprecated', 'created_at']
    list_filter = ['is_deprecated', 'created_at']
    search_fields = ['code', 'title']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [AssessmentVersionInline]


@admin.register(AssessmentVersion)
class AssessmentVersionAdmin(admin.ModelAdmin):
    list_display = ['assessment', 'version_number', 'title', 'status', 'time_limit_seconds', 'published_at']
    list_filter = ['status', 'allow_backtracking', 'created_at']
    search_fields = ['assessment__code', 'title']
    readonly_fields = ['published_at', 'created_at', 'updated_at']
    inlines = [AssessmentVersionQuestionInline]


@admin.register(AssessmentVersionQuestion)
class AssessmentVersionQuestionAdmin(admin.ModelAdmin):
    list_display = ['assessment_version', 'order_index', 'question_version', 'weight']
    list_filter = ['assessment_version__status']
    search_fields = ['assessment_version__assessment__code', 'question_version__question__code']


class AttemptQuestionInline(admin.TabularInline):
    model = AttemptQuestion
    extra = 0
    fields = ['order_index', 'question_version', 'weight']
    readonly_fields = ['order_index', 'question_version', 'weight']
    can_delete = False
    show_change_link = True


class AttemptEventInline(admin.TabularInline):
    model = AttemptEvent
    extra = 0
    fields = ['event_type', 'payload', 'created_at']
    readonly_fields = ['event_type', 'payload', 'created_at']
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AssessmentAttempt)
class AssessmentAttemptAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'user',
        'assessment',
        'attempt_number',
        'status',
        'question_count',
        'answer_count',
        'started_at',
    ]
    list_filter = ['status', 'started_at']
    search_fields = ['user__email', 'assessment__code', 'idempotency_key']
    readonly_fields = [
        'id',
        'user',
        'assessment',
        'assessment_version',
        'idempotency_key',
        'time_limit_seconds',
        'allow_backtracking',
        'started_at',
        'completed_at',
        'created_at',
        'updated_at',
    ]
    inlines = [AttemptQuestionInline, AttemptEventInline]


@admin.register(ActiveAssessmentReservation)
class ActiveAssessmentReservationAdmin(admin.ModelAdmin):
    list_display = ['user', 'assessment', 'attempt', 'idempotency_key', 'created_at']
    search_fields = ['user__email', 'assessment__code', 'idempotency_key']
    readonly_fields = ['user', 'assessment', 'attempt', 'idempotency_key', 'created_at']


class AttemptAnswerInline(admin.StackedInline):
    model = AttemptAnswer
    extra = 0
    fields = ['answer_payload', 'is_answered', 'answered_at']


@admin.register(AttemptQuestion)
class AttemptQuestionAdmin(admin.ModelAdmin):
    list_display = ['attempt', 'order_index', 'question_version', 'weight']
    search_fields = ['attempt__user__email', 'question_version__question__code']
    inlines = [AttemptAnswerInline]


@admin.register(AttemptAnswer)
class AttemptAnswerAdmin(admin.ModelAdmin):
    list_display = ['attempt_question', 'is_answered', 'answered_at', 'updated_at']
    list_filter = ['is_answered']
    search_fields = ['attempt_question__attempt__user__email']


@admin.register(AttemptEvent)
class AttemptEventAdmin(admin.ModelAdmin):
    list_display = ['attempt', 'event_type', 'created_at']
    list_filter = ['event_type', 'created_at']
    search_fields = ['attempt__user__email', 'event_type']
    readonly_fields = ['attempt', 'event_type', 'payload', 'created_at']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
