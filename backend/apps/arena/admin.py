"""
Django Admin Configuration for ZENTIQ Arena & Question Bank.
Provides administration for questions, immutable versions, confidential evaluation rules,
and competency mappings.
"""
from django.contrib import admin
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from .models import (
    Question,
    QuestionCompetencyMapping,
    QuestionEvaluationData,
    QuestionVersion,
    QuestionVersionTag,
    Tag,
    reconcile_active_version_on_lifecycle_transition,
)


class QuestionEvaluationDataInline(admin.StackedInline):
    model = QuestionEvaluationData
    extra = 0
    can_delete = False
    fields = ['grading_strategy', 'correct_payload', 'scoring_rubric']

    def has_change_permission(self, request, obj=None):
        if obj and obj.status in ('PUBLISHED', 'ARCHIVED', 'DEPRECATED'):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj and obj.status in ('PUBLISHED', 'ARCHIVED', 'DEPRECATED'):
            return False
        return super().has_delete_permission(request, obj)


class QuestionCompetencyMappingInline(admin.TabularInline):
    model = QuestionCompetencyMapping
    extra = 0
    fields = ['competency', 'weight', 'is_primary']

    def has_add_permission(self, request, obj=None):
        if obj and obj.status in ('PUBLISHED', 'ARCHIVED', 'DEPRECATED'):
            return False
        return super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if obj and obj.status in ('PUBLISHED', 'ARCHIVED', 'DEPRECATED'):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj and obj.status in ('PUBLISHED', 'ARCHIVED', 'DEPRECATED'):
            return False
        return super().has_delete_permission(request, obj)


class QuestionVersionTagInline(admin.TabularInline):
    model = QuestionVersionTag
    extra = 0

    def has_add_permission(self, request, obj=None):
        if obj and obj.status in ('PUBLISHED', 'ARCHIVED', 'DEPRECATED'):
            return False
        return super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if obj and obj.status in ('PUBLISHED', 'ARCHIVED', 'DEPRECATED'):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj and obj.status in ('PUBLISHED', 'ARCHIVED', 'DEPRECATED'):
            return False
        return super().has_delete_permission(request, obj)


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ['code', 'active_version', 'is_deprecated', 'versions_count', 'created_at', 'updated_at']
    list_filter = ['is_deprecated']
    search_fields = ['code']
    readonly_fields = ['created_at', 'updated_at']

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return list(self.readonly_fields) + ['code']
        return self.readonly_fields

    @admin.display(description=_('Versions'))
    def versions_count(self, obj):
        return obj.versions.count()


@admin.register(QuestionVersion)
class QuestionVersionAdmin(admin.ModelAdmin):
    list_display = [
        'question',
        'version_number',
        'title',
        'question_type',
        'difficulty_tier',
        'primary_competency',
        'bloom_level',
        'status',
        'published_at',
    ]
    list_filter = ['status', 'question_type', 'difficulty_tier', 'bloom_level']
    search_fields = ['question__code', 'title', 'prompt']
    inlines = [QuestionEvaluationDataInline, QuestionCompetencyMappingInline, QuestionVersionTagInline]
    actions = ['archive_versions', 'deprecate_versions']

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.status in ('PUBLISHED', 'ARCHIVED', 'DEPRECATED'):
            return [
                'question',
                'version_number',
                'status',
                'title',
                'prompt',
                'question_type',
                'difficulty_tier',
                'primary_competency',
                'bloom_level',
                'time_limit_seconds',
                'content_payload',
                'explanation',
                'created_by',
                'change_summary',
                'published_at',
                'created_at',
                'updated_at',
            ]
        return ['published_at', 'created_at', 'updated_at']

    @admin.action(description=_('Archive selected published versions'))
    def archive_versions(self, request, queryset):
        with transaction.atomic():
            count = 0
            for obj in queryset.filter(status='PUBLISHED'):
                reconcile_active_version_on_lifecycle_transition(obj, 'ARCHIVED')
                count += 1
            self.message_user(request, f"{count} question version(s) successfully archived.")

    @admin.action(description=_('Deprecate selected versions'))
    def deprecate_versions(self, request, queryset):
        with transaction.atomic():
            count = 0
            for obj in queryset.filter(status__in=['PUBLISHED', 'ARCHIVED']):
                reconcile_active_version_on_lifecycle_transition(obj, 'DEPRECATED')
                count += 1
            self.message_user(request, f"{count} question version(s) successfully deprecated.")


@admin.register(QuestionEvaluationData)
class QuestionEvaluationDataAdmin(admin.ModelAdmin):
    list_display = ['question_version', 'grading_strategy', 'updated_at']
    list_filter = ['grading_strategy']
    search_fields = ['question_version__question__code', 'question_version__title']


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'category', 'created_at']
    list_filter = ['category']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}

