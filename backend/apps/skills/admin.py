"""
Django Admin Configuration for ZENTIQ Skills & Taxonomy.
"""
from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from .models import (
    Competency,
    Domain,
    SkillPrerequisite,
    Subdomain,
    UserCompetencyMastery,
    UserDomainMastery,
)


class SubdomainInline(admin.TabularInline):
    model = Subdomain
    extra = 1
    fields = ['name', 'slug', 'display_order', 'is_active']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'category', 'display_order', 'is_active', 'subdomains_count', 'updated_at']
    list_filter = ['category', 'is_active']
    search_fields = ['name', 'slug', 'description']
    prepopulated_fields = {'slug': ('name',)}
    inlines = [SubdomainInline]

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return list(self.readonly_fields) + ['slug']
        return self.readonly_fields

    @admin.display(description=_('Subdomains'))
    def subdomains_count(self, obj):
        return obj.subdomains.count()


class CompetencyInline(admin.TabularInline):
    model = Competency
    extra = 1
    fields = ['code', 'name', 'bloom_level', 'is_active']


@admin.register(Subdomain)
class SubdomainAdmin(admin.ModelAdmin):
    list_display = ['name', 'domain', 'slug', 'display_order', 'is_active', 'competencies_count']
    list_filter = ['domain', 'is_active']
    search_fields = ['name', 'slug', 'domain__name']
    inlines = [CompetencyInline]

    @admin.display(description=_('Competencies'))
    def competencies_count(self, obj):
        return obj.competencies.count()


@admin.register(Competency)
class CompetencyAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'subdomain', 'get_domain', 'bloom_level', 'is_active']
    list_filter = ['bloom_level', 'is_active', 'subdomain__domain']
    search_fields = ['code', 'name', 'description']

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return list(self.readonly_fields) + ['code']
        return self.readonly_fields

    @admin.display(description=_('Domain'))
    def get_domain(self, obj):
        return obj.subdomain.domain.name


@admin.register(SkillPrerequisite)
class SkillPrerequisiteAdmin(admin.ModelAdmin):
    list_display = ['competency', 'prerequisite_competency', 'min_mastery_percentage', 'created_at']
    list_filter = ['competency__subdomain__domain']
    search_fields = ['competency__code', 'competency__name', 'prerequisite_competency__code']


@admin.register(UserDomainMastery)
class UserDomainMasteryAdmin(admin.ModelAdmin):
    list_display = ['user', 'domain', 'mastery_score', 'confidence_tier', 'total_assessments_completed', 'last_assessed_at']
    list_filter = ['confidence_tier', 'domain']
    search_fields = ['user__email', 'domain__name']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(UserCompetencyMastery)
class UserCompetencyMasteryAdmin(admin.ModelAdmin):
    list_display = ['user', 'competency', 'mastery_score', 'evaluations_count', 'last_assessed_at']
    list_filter = ['competency__subdomain__domain']
    search_fields = ['user__email', 'competency__code', 'competency__name']
    readonly_fields = ['created_at', 'updated_at']

