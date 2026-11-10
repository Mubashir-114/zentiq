"""
Models for ZENTIQ Skill Taxonomy & Player Mastery.
Provides a 3-tier hierarchy: Domain -> Subdomain -> Competency,
plus prerequisite DAG relations and user mastery matrices.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _


class Domain(models.Model):
    """
    Tier 1: High-level skill domain (e.g. Numerical Intelligence, Programming Logic).
    Maps directly to the 8 core platform domains displayed on the player dashboard.
    """
    CATEGORY_CHOICES = (
        ('COGNITIVE', 'Cognitive'),
        ('ANALYTICAL', 'Analytical'),
        ('PERCEPTUAL', 'Perceptual'),
        ('TECHNICAL', 'Technical'),
        ('APPLIED', 'Applied'),
    )

    slug = models.SlugField(
        _('slug'),
        max_length=50,
        unique=True,
        db_index=True,
        help_text=_('Unique identifier matching frontend domain keys (e.g. numerical_intelligence).'),
    )
    name = models.CharField(
        _('name'),
        max_length=100,
        help_text=_('Display name of the domain (e.g. Numerical Intelligence).'),
    )
    category = models.CharField(
        _('category'),
        max_length=30,
        choices=CATEGORY_CHOICES,
        default='COGNITIVE',
        help_text=_('Macro classification tier for radar chart and clustering.'),
    )
    description = models.TextField(
        _('description'),
        help_text=_('Detailed domain scope and cognitive dimensions evaluated.'),
    )
    icon_key = models.CharField(
        _('icon key'),
        max_length=50,
        blank=True,
        help_text=_('Frontend icon identifier (e.g. Calculator, Brain, Code2).'),
    )
    display_order = models.PositiveSmallIntegerField(
        _('display order'),
        default=0,
        help_text=_('Ordering on the dashboard grid.'),
    )
    is_active = models.BooleanField(
        _('is active'),
        default=True,
        help_text=_('Whether this domain is enabled for assessment and display.'),
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        db_table = 'skills_domain'
        verbose_name = _('skill domain')
        verbose_name_plural = _('skill domains')
        ordering = ['display_order', 'name']

    def __str__(self):
        return f"{self.name} ({self.get_category_display()})"

    def clean(self):
        super().clean()
        if self.pk:
            orig = Domain.objects.filter(pk=self.pk).values('slug').first()
            if orig and orig['slug'] != self.slug:
                raise ValidationError({'slug': _("Domain slug is immutable after creation.")})

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class Subdomain(models.Model):
    """
    Tier 2: Thematic specialization within a Domain (e.g. Algorithmic Tracing).
    """
    domain = models.ForeignKey(
        Domain,
        on_delete=models.PROTECT,
        related_name='subdomains',
        verbose_name=_('domain'),
    )
    slug = models.SlugField(
        _('slug'),
        max_length=60,
        help_text=_('URL and API friendly subdomain identifier.'),
    )
    name = models.CharField(
        _('name'),
        max_length=100,
        help_text=_('Subdomain title (e.g. Algorithmic Control Flow).'),
    )
    description = models.TextField(
        _('description'),
        blank=True,
        help_text=_('Specific thematic competencies encompassed.'),
    )
    display_order = models.PositiveSmallIntegerField(
        _('display order'),
        default=0,
    )
    is_active = models.BooleanField(
        _('is active'),
        default=True,
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        db_table = 'skills_subdomain'
        verbose_name = _('subdomain')
        verbose_name_plural = _('subdomains')
        ordering = ['domain', 'display_order', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['domain', 'slug'],
                name='uq_skills_subdomain_domain_slug',
            ),
        ]

    def __str__(self):
        return f"{self.domain.name} → {self.name}"


class Competency(models.Model):
    """
    Tier 3: Atomic measurable competency (e.g. PROG-CTRL-01: Loop State Tracing).
    Each assessment question evaluates one primary competency.
    """
    BLOOM_CHOICES = (
        ('REMEMBER', 'Remember'),
        ('UNDERSTAND', 'Understand'),
        ('APPLY', 'Apply'),
        ('ANALYZE', 'Analyze'),
        ('EVALUATE', 'Evaluate'),
        ('CREATE', 'Create'),
    )

    subdomain = models.ForeignKey(
        Subdomain,
        on_delete=models.PROTECT,
        related_name='competencies',
        verbose_name=_('subdomain'),
    )
    code = models.CharField(
        _('competency code'),
        max_length=30,
        unique=True,
        db_index=True,
        help_text=_('Standardized alphanumeric code (e.g. NUM-ARITH-01, PROG-CTRL-02).'),
    )
    name = models.CharField(
        _('name'),
        max_length=120,
        help_text=_('Descriptive competency title.'),
    )
    description = models.TextField(
        _('description'),
        help_text=_('Measurable criteria defining mastery of this competency.'),
    )
    bloom_level = models.CharField(
        _('bloom level'),
        max_length=20,
        choices=BLOOM_CHOICES,
        default='APPLY',
        help_text=_('Cognitive depth taxonomy level according to Bloom.'),
    )
    is_active = models.BooleanField(
        _('is active'),
        default=True,
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        db_table = 'skills_competency'
        verbose_name = _('competency')
        verbose_name_plural = _('competencies')
        ordering = ['code']
        indexes = [
            models.Index(fields=['subdomain', 'is_active']),
        ]

    def __str__(self):
        return f"[{self.code}] {self.name}"

    def clean(self):
        super().clean()
        if self.pk:
            orig = Competency.objects.filter(pk=self.pk).values('code').first()
            if orig and orig['code'] != self.code:
                raise ValidationError({'code': _("Competency code is immutable after creation.")})

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class SkillPrerequisite(models.Model):
    """
    Directed dependency graph edge: competency requires prerequisite_competency
    to achieve a minimum mastery score before advanced modules unlock.
    """
    competency = models.ForeignKey(
        Competency,
        on_delete=models.CASCADE,
        related_name='prerequisite_requirements',
        verbose_name=_('competency'),
    )
    prerequisite_competency = models.ForeignKey(
        Competency,
        on_delete=models.CASCADE,
        related_name='dependent_competencies',
        verbose_name=_('prerequisite competency'),
    )
    min_mastery_percentage = models.DecimalField(
        _('minimum mastery percentage'),
        max_digits=5,
        decimal_places=2,
        default=70.00,
        validators=[MinValueValidator(0.0), MaxValueValidator(100.0)],
        help_text=_('Required mastery threshold (0.00 to 100.00) in prerequisite.'),
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)

    class Meta:
        db_table = 'skills_prerequisite'
        verbose_name = _('skill prerequisite')
        verbose_name_plural = _('skill prerequisites')
        constraints = [
            models.UniqueConstraint(
                fields=['competency', 'prerequisite_competency'],
                name='uq_skills_prerequisite_pair',
            ),
            models.CheckConstraint(
                condition=~Q(competency=F('prerequisite_competency')),
                name='chk_skills_prerequisite_no_self_ref',
            ),
            models.CheckConstraint(
                condition=Q(min_mastery_percentage__gte=0.0) & Q(min_mastery_percentage__lte=100.0),
                name='chk_skills_prereq_mastery_pct_range',
            ),
        ]

    def __str__(self):
        return f"{self.competency.code} requires {self.prerequisite_competency.code} (≥{self.min_mastery_percentage}%)"

    def clean(self):
        super().clean()
        if self.competency_id and self.prerequisite_competency_id:
            from .services import PrerequisiteService
            PrerequisiteService.validate_prerequisite_addition(
                self.competency, self.prerequisite_competency
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class UserDomainMastery(models.Model):
    """
    Aggregated mastery record for a user in a specific Domain.
    Powers the player dashboard skill cards and radar charts.
    """
    CONFIDENCE_CHOICES = (
        ('UNASSESSED', 'Not Assessed'),
        ('CALIBRATING', 'Calibrating'),
        ('DEVELOPING', 'Developing'),
        ('PROFICIENT', 'Proficient'),
        ('MASTERY', 'Mastery'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='domain_masteries',
        verbose_name=_('user'),
    )
    domain = models.ForeignKey(
        Domain,
        on_delete=models.PROTECT,
        related_name='user_mastery_records',
        verbose_name=_('domain'),
    )
    mastery_score = models.DecimalField(
        _('mastery score'),
        max_digits=5,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0.0), MaxValueValidator(100.0)],
        help_text=_('Aggregated domain mastery percentage (0.00 to 100.00).'),
    )
    confidence_tier = models.CharField(
        _('confidence tier'),
        max_length=30,
        choices=CONFIDENCE_CHOICES,
        default='UNASSESSED',
        help_text=_('Confidence level based on evaluation count and consistency.'),
    )
    total_assessments_completed = models.PositiveIntegerField(
        _('total assessments completed'),
        default=0,
    )
    last_assessed_at = models.DateTimeField(
        _('last assessed at'),
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        db_table = 'skills_user_domain_mastery'
        verbose_name = _('user domain mastery')
        verbose_name_plural = _('user domain masteries')
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'domain'],
                name='uq_skills_user_domain',
            ),
            models.CheckConstraint(
                condition=Q(mastery_score__gte=0.0) & Q(mastery_score__lte=100.0),
                name='chk_user_domain_mastery_score_range',
            ),
            models.CheckConstraint(
                condition=Q(total_assessments_completed__gte=0),
                name='chk_user_domain_mastery_assessments_non_negative',
            ),
        ]

    def __str__(self):
        return f"@{self.user} - {self.domain.name}: {self.mastery_score}% ({self.get_confidence_tier_display()})"


class UserCompetencyMastery(models.Model):
    """
    Granular mastery score per atomic competency for a user.
    Updated authoritatively after each assessment evaluation.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='competency_masteries',
        verbose_name=_('user'),
    )
    competency = models.ForeignKey(
        Competency,
        on_delete=models.PROTECT,
        related_name='user_mastery_records',
        verbose_name=_('competency'),
    )
    mastery_score = models.DecimalField(
        _('mastery score'),
        max_digits=5,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0.0), MaxValueValidator(100.0)],
        help_text=_('Current calibrated mastery level (0.00 to 100.00).'),
    )
    evaluations_count = models.PositiveIntegerField(
        _('evaluations count'),
        default=0,
        help_text=_('Number of distinct evaluated questions for this competency.'),
    )
    last_assessed_at = models.DateTimeField(
        _('last assessed at'),
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        db_table = 'skills_user_competency_mastery'
        verbose_name = _('user competency mastery')
        verbose_name_plural = _('user competency masteries')
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'competency'],
                name='uq_skills_user_competency',
            ),
            models.CheckConstraint(
                condition=Q(mastery_score__gte=0.0) & Q(mastery_score__lte=100.0),
                name='chk_user_competency_mastery_score_range',
            ),
            models.CheckConstraint(
                condition=Q(evaluations_count__gte=0),
                name='chk_user_competency_mastery_evals_non_negative',
            ),
        ]

    def __str__(self):
        return f"@{self.user} - [{self.competency.code}]: {self.mastery_score}%"

