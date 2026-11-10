"""
Models for ZENTIQ Question Bank & Question Versioning.
Application: apps.arena
Provides permanent Question anchors, immutable QuestionVersions,
confidential QuestionEvaluationData, and weighted Competency mappings.
"""
import uuid
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.skills.models import Competency

VALID_TRANSITIONS = {
    'DRAFT': {'IN_REVIEW'},
    'IN_REVIEW': {'DRAFT', 'PUBLISHED'},
    'PUBLISHED': {'ARCHIVED', 'DEPRECATED'},
    'ARCHIVED': {'DEPRECATED'},
    'DEPRECATED': set(),
}

RESERVED_CONFIDENTIAL_KEYS = {
    'correct_payload',
    'correct_option_id',
    'correct_option_ids',
    'correct_value',
    'target_value',
    'expected_stdout',
    'scoring_rubric',
}


def scan_for_confidential_keys(payload, reserved_keys=RESERVED_CONFIDENTIAL_KEYS, path=''):
    """
    Recursively scans a dict or list payload for reserved confidential keys.
    Returns a list of found forbidden key paths.
    """
    found = []
    if isinstance(payload, dict):
        for k, v in payload.items():
            current_path = f"{path}.{k}" if path else str(k)
            if k in reserved_keys:
                found.append(current_path)
            found.extend(scan_for_confidential_keys(v, reserved_keys, current_path))
    elif isinstance(payload, list):
        for idx, item in enumerate(payload):
            current_path = f"{path}[{idx}]"
            found.extend(scan_for_confidential_keys(item, reserved_keys, current_path))
    return found


class Question(models.Model):
    """
    Permanent canonical identity anchor for a question series.
    Provides a stable external code and maintains a reference to the active published version.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(
        _('question code'),
        max_length=40,
        unique=True,
        db_index=True,
        help_text=_('Standardized canonical identifier (e.g. QST-NUM-ARITH-001).'),
    )
    active_version = models.ForeignKey(
        'QuestionVersion',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name=_('active published version'),
        help_text=_('Current published version served in live assessments.'),
    )
    is_deprecated = models.BooleanField(
        _('is deprecated'),
        default=False,
        db_index=True,
        help_text=_('Designates whether the entire question series is retired from future selection.'),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='authored_questions',
        verbose_name=_('created by'),
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        db_table = 'arena_question'
        verbose_name = _('question')
        verbose_name_plural = _('questions')
        ordering = ['code']
        indexes = [
            models.Index(fields=['is_deprecated', 'created_at']),
        ]

    def __str__(self):
        return self.code

    def clean(self):
        super().clean()
        if self.pk:
            orig = Question.objects.filter(pk=self.pk).values('code').first()
            if orig and orig['code'] != self.code:
                raise ValidationError({'code': _("Question code is immutable after creation.")})

        if self.active_version_id:
            av = getattr(self, 'active_version', None)
            av_question_id = av.question_id if av else None
            av_status = av.status if av else None
            if not av or av_question_id is None:
                row = QuestionVersion.objects.filter(pk=self.active_version_id).values('question_id', 'status').first()
                if row:
                    av_question_id = row['question_id']
                    av_status = row['status']
                else:
                    raise ValidationError({'active_version': _("Referenced active version does not exist.")})

            if self.pk and av_question_id != self.pk:
                raise ValidationError({
                    'active_version': _("Active version must belong to this question.")
                })
            if av_status != 'PUBLISHED':
                raise ValidationError({
                    'active_version': _(f"Active version must have PUBLISHED status, but has status '{av_status}'.")
                })

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class Tag(models.Model):
    """
    Taxonomy-orthogonal tagging for topic clustering and exam filters.
    """
    CATEGORY_CHOICES = (
        ('TOPIC', 'Topic / Concept'),
        ('TOOL', 'Tool / Library'),
        ('LANGUAGE', 'Language / Dialect'),
        ('EXAM', 'Standardized Exam Format'),
    )

    slug = models.SlugField(
        _('slug'),
        max_length=50,
        unique=True,
        db_index=True,
    )
    name = models.CharField(
        _('name'),
        max_length=50,
        unique=True,
    )
    category = models.CharField(
        _('category'),
        max_length=30,
        choices=CATEGORY_CHOICES,
        default='TOPIC',
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)

    class Meta:
        db_table = 'arena_tag'
        verbose_name = _('tag')
        verbose_name_plural = _('tags')
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.get_category_display()})"


class QuestionVersion(models.Model):
    """
    Immutable versioned snapshot of a question's public presentation content,
    taxonomy alignment, and metadata.
    """
    STATUS_CHOICES = (
        ('DRAFT', 'Draft'),
        ('IN_REVIEW', 'In Review'),
        ('PUBLISHED', 'Published'),
        ('ARCHIVED', 'Archived'),
        ('DEPRECATED', 'Deprecated'),
    )

    TYPE_CHOICES = (
        ('SINGLE_CHOICE', 'Single-Choice MCQ'),
        ('MULTIPLE_CHOICE', 'Multiple-Select MCQ'),
        ('TRUE_FALSE', 'True / False'),
        ('NUMERICAL', 'Numerical Answer'),
        ('SHORT_TEXT', 'Short Text Answer'),
        ('CODE_OUTPUT', 'Code Output Prediction'),
    )

    DIFFICULTY_CHOICES = (
        ('NOVICE', 'Novice (Level 1)'),
        ('BEGINNER', 'Beginner (Level 2)'),
        ('INTERMEDIATE', 'Intermediate (Level 3)'),
        ('ADVANCED', 'Advanced (Level 4)'),
        ('EXPERT', 'Expert (Level 5)'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name='versions',
        verbose_name=_('parent question'),
    )
    version_number = models.PositiveIntegerField(
        _('version number'),
        default=1,
        help_text=_('Monotonically increasing version counter for this question.'),
    )
    status = models.CharField(
        _('lifecycle status'),
        max_length=20,
        choices=STATUS_CHOICES,
        default='DRAFT',
        db_index=True,
    )
    title = models.CharField(
        _('title'),
        max_length=200,
        help_text=_('Authoring title describing the problem premise.'),
    )
    prompt = models.TextField(
        _('question prompt'),
        help_text=_('Rich-text / Markdown / LaTeX question stem presented to the user.'),
    )
    question_type = models.CharField(
        _('question type'),
        max_length=30,
        choices=TYPE_CHOICES,
        db_index=True,
    )
    difficulty_tier = models.CharField(
        _('difficulty tier'),
        max_length=20,
        choices=DIFFICULTY_CHOICES,
        default='INTERMEDIATE',
        db_index=True,
    )
    primary_competency = models.ForeignKey(
        Competency,
        on_delete=models.PROTECT,
        related_name='primary_question_versions',
        verbose_name=_('primary competency'),
        help_text=_('Core atomic competency measured by this question version.'),
    )
    bloom_level = models.CharField(
        _('bloom level'),
        max_length=20,
        choices=Competency.BLOOM_CHOICES,
        default='APPLY',
        help_text=_('Target cognitive depth according to Bloom taxonomy.'),
    )
    time_limit_seconds = models.PositiveIntegerField(
        _('time limit (seconds)'),
        default=60,
        validators=[MinValueValidator(5), MaxValueValidator(600)],
        help_text=_('Expected response time window for anti-cheat pacing.'),
    )
    content_payload = models.JSONField(
        _('content payload'),
        default=dict,
        blank=True,
        help_text=_('Structured presentation data (options, code snippets, units) without answers.'),
    )
    explanation = models.TextField(
        _('post-assessment explanation'),
        blank=True,
        help_text=_('Detailed educational rationale provided only during post-submission review.'),
    )
    change_summary = models.CharField(
        _('change summary'),
        max_length=255,
        blank=True,
        help_text=_('Changelog description of alterations made in this revision.'),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_question_versions',
        verbose_name=_('author'),
    )
    tags = models.ManyToManyField(
        Tag,
        through='QuestionVersionTag',
        related_name='question_versions',
        blank=True,
        verbose_name=_('tags'),
    )
    published_at = models.DateTimeField(
        _('published at'),
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        db_table = 'arena_question_version'
        verbose_name = _('question version')
        verbose_name_plural = _('question versions')
        ordering = ['question', '-version_number']
        permissions = [
            ('publish_questionversion', _('Can publish question version')),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['question', 'version_number'],
                name='uq_arena_question_version_number',
            ),
            models.CheckConstraint(
                condition=Q(version_number__gt=0),
                name='chk_arena_question_version_gt_zero',
            ),
            models.CheckConstraint(
                condition=Q(time_limit_seconds__gte=5) & Q(time_limit_seconds__lte=600),
                name='chk_arena_question_version_time_limit',
            ),
        ]
        indexes = [
            models.Index(fields=['status', 'question_type']),
            models.Index(fields=['primary_competency', 'status']),
            models.Index(fields=['difficulty_tier', 'status']),
        ]

    def __str__(self):
        return f"{self.question.code} (v{self.version_number}) [{self.status}]"

    def clean(self):
        super().clean()

        # Reject confidential evaluation keys in public content_payload
        if self.content_payload:
            leaked = scan_for_confidential_keys(self.content_payload)
            if leaked:
                raise ValidationError({
                    'content_payload': _(
                        f"Confidential evaluation keys are forbidden in public content_payload: {', '.join(leaked)}."
                    )
                })

        exists_in_db = self.pk and QuestionVersion.objects.filter(pk=self.pk).exists()
        if not exists_in_db:
            if self.status != 'DRAFT':
                raise ValidationError({
                    'status': _(f"New question versions must be created with DRAFT status, not '{self.status}'.")
                })
        else:
            orig = QuestionVersion.objects.filter(pk=self.pk).values(
                'status', 'title', 'prompt', 'content_payload', 'primary_competency_id',
                'question_type', 'difficulty_tier', 'time_limit_seconds', 'version_number',
                'question_id', 'bloom_level', 'explanation', 'created_by_id', 'published_at',
                'change_summary'
            ).first()
            if orig:
                # Validate lifecycle state transition
                if orig['status'] != self.status:
                    allowed = VALID_TRANSITIONS.get(orig['status'], set())
                    if self.status not in allowed:
                        raise ValidationError({
                            'status': _(
                                f"Invalid status transition from '{orig['status']}' to '{self.status}'. "
                                f"Permitted transitions: {sorted(list(allowed)) or 'None (terminal state)'}."
                            )
                        })

                # If previously published or archived or deprecated, forbid modifying substantive content
                if orig['status'] in ('PUBLISHED', 'ARCHIVED', 'DEPRECATED'):
                    forbidden_fields = []
                    immutable_checks = [
                        ('title', self.title),
                        ('prompt', self.prompt),
                        ('content_payload', self.content_payload),
                        ('primary_competency_id', self.primary_competency_id),
                        ('question_type', self.question_type),
                        ('difficulty_tier', self.difficulty_tier),
                        ('time_limit_seconds', self.time_limit_seconds),
                        ('version_number', self.version_number),
                        ('question_id', self.question_id),
                        ('bloom_level', self.bloom_level),
                        ('explanation', self.explanation),
                        ('created_by_id', self.created_by_id),
                        ('published_at', self.published_at),
                        ('change_summary', self.change_summary),
                    ]
                    for field_name, new_val in immutable_checks:
                        if orig[field_name] != new_val:
                            forbidden_fields.append(field_name)

                    if forbidden_fields:
                        raise ValidationError(
                            _("Published question versions are immutable. Forbidden modifications on: %s. "
                              "Create a new question version instead.") % ", ".join(forbidden_fields)
                        )

    def save(self, *args, **kwargs):
        self.clean()
        if self.status == 'PUBLISHED' and not self.published_at:
            self.published_at = timezone.now()

        # Determine effective update_fields supporting both keyword and positional invocation
        # (Django's Model.save positional signature places update_fields at index 3).
        update_fields = kwargs.get('update_fields')
        if update_fields is None and len(args) > 3:
            update_fields = args[3]
        if args:
            param_names = ['force_insert', 'force_update', 'using', 'update_fields']
            for name, val in zip(param_names, args):
                kwargs.setdefault(name, val)
            args = ()

        status_will_persist = (update_fields is None) or ('status' in update_fields)

        # Enforce active-version invariant across all standard model save paths:
        # When any version transitions to an inactive status (ARCHIVED or DEPRECATED),
        # atomically reconcile the parent Question's active_version pointer only if the
        # status transition will actually be persisted by this save operation.
        if self.pk and self.status in ('ARCHIVED', 'DEPRECATED') and status_will_persist:
            from django.db import transaction

            with transaction.atomic():
                # 1. Retrieve and lock parent Question by primary key alone
                question = Question.objects.select_for_update().get(pk=self.question_id)

                # 2. Authoritative reconciliation decisions:
                if question.is_deprecated:
                    # Invariant: A deprecated Question series must NEVER possess an active version.
                    # If an inconsistent non-null active pointer exists (referencing ANY version), clear it.
                    if question.active_version_id is not None:
                        question.active_version = None
                        question.save(update_fields=['active_version', 'updated_at'])
                elif question.active_version_id == self.pk:
                    # Active version transitioned on an active Question: reconcile to highest remaining PUBLISHED
                    replacement = (
                        QuestionVersion.objects.filter(
                            question_id=self.question_id,
                            status='PUBLISHED',
                        )
                        .exclude(pk=self.pk)
                        .order_by('-version_number')
                        .first()
                    )
                    question.active_version = replacement
                    question.save(update_fields=['active_version', 'updated_at'])
                else:
                    # Non-active version transitioned on an active Question: leave active pointer unchanged
                    pass

                super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)


def reconcile_active_version_on_lifecycle_transition(version: QuestionVersion, target_status: str) -> None:
    """
    Safely transitions a QuestionVersion to target_status (e.g. ARCHIVED or DEPRECATED)
    and reconciles its parent Question's active_version pointer within an atomic transaction.

    Invariants enforced:
    1. If the version is the parent Question's active_version:
       - Locates a replacement only if another valid PUBLISHED version for the same Question exists.
       - Selects the replacement with the highest version_number.
       - If no other PUBLISHED version exists for this Question, clears active_version (sets to None).
       - Never selects a version belonging to another Question.
       - Never selects DRAFT, IN_REVIEW, ARCHIVED, or DEPRECATED versions.
    2. Updates the Question active_version pointer and transitions the version within the same transaction.
    3. Normal Question.clean() and QuestionVersion.clean() validations are strictly preserved.
    Delegates to QuestionVersion.save() to preserve a single authoritative validation
    and reconciliation execution path.
    """
    from django.db import transaction

    with transaction.atomic():
        version.status = target_status
        version.save()


class QuestionEvaluationData(models.Model):
    """
    Confidential evaluation rules, answer keys, and grading rubrics.
    Stored in a dedicated table isolated from public question APIs.
    """
    STRATEGY_CHOICES = (
        ('EXACT_MATCH', 'Exact Match Equality'),
        ('SET_MATCH', 'Set Match (All or Partial)'),
        ('NUMERIC_TOLERANCE', 'Numeric Window / Tolerance'),
        ('NORMALIZED_STRING', 'Normalized String Equality'),
        ('REGEX_MATCH', 'Regular Expression Pattern'),
        ('STDOUT_MATCH', 'Standard Output Exact/Normalized'),
    )

    question_version = models.OneToOneField(
        QuestionVersion,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='evaluation_data',
        verbose_name=_('question version'),
    )
    grading_strategy = models.CharField(
        _('grading strategy'),
        max_length=40,
        choices=STRATEGY_CHOICES,
        default='EXACT_MATCH',
    )
    correct_payload = models.JSONField(
        _('correct answer payload'),
        help_text=_('Confidential answer criteria (option IDs, numeric targets, patterns).'),
    )
    scoring_rubric = models.JSONField(
        _('scoring rubric'),
        default=dict,
        blank=True,
        help_text=_('Scoring policies: partial credit, penalty weights, tolerance thresholds.'),
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        db_table = 'arena_question_evaluation_data'
        verbose_name = _('question evaluation data')
        verbose_name_plural = _('question evaluation data records')

    def __str__(self):
        return f"EvaluationData for {self.question_version}"

    def clean(self):
        super().clean()
        if self.question_version_id:
            qv = QuestionVersion.objects.filter(pk=self.question_version_id).values('status').first()
            if qv and qv['status'] in ('PUBLISHED', 'ARCHIVED', 'DEPRECATED'):
                exists_in_db = self.pk and QuestionEvaluationData.objects.filter(pk=self.pk).exists()
                if exists_in_db:
                    orig = QuestionEvaluationData.objects.filter(pk=self.pk).values(
                        'correct_payload', 'grading_strategy', 'scoring_rubric'
                    ).first()
                    if orig and (orig['correct_payload'] != self.correct_payload or
                                 orig['grading_strategy'] != self.grading_strategy or
                                 orig['scoring_rubric'] != self.scoring_rubric):
                        raise ValidationError(
                            _("Evaluation data for a published question version is immutable.")
                        )
                else:
                    raise ValidationError(
                        _("Cannot attach evaluation data to an already published question version.")
                    )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class QuestionCompetencyMapping(models.Model):
    """
    Weighted secondary competency relationships.
    Enables interdisciplinary questions to contribute calibrated mastery to multiple competencies.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question_version = models.ForeignKey(
        QuestionVersion,
        on_delete=models.CASCADE,
        related_name='competency_mappings',
        verbose_name=_('question version'),
    )
    competency = models.ForeignKey(
        Competency,
        on_delete=models.PROTECT,
        related_name='question_mappings',
        verbose_name=_('competency'),
    )
    weight = models.DecimalField(
        _('evaluation weight'),
        max_digits=4,
        decimal_places=2,
        default=Decimal('1.00'),
        validators=[MinValueValidator(Decimal('0.05')), MaxValueValidator(Decimal('1.00'))],
        help_text=_('Proportional mastery contribution (0.05 to 1.00).'),
    )
    is_primary = models.BooleanField(
        _('is primary'),
        default=False,
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)

    class Meta:
        db_table = 'arena_question_competency_mapping'
        verbose_name = _('question competency mapping')
        verbose_name_plural = _('question competency mappings')
        constraints = [
            models.UniqueConstraint(
                fields=['question_version', 'competency'],
                name='uq_arena_question_version_competency',
            ),
            models.CheckConstraint(
                condition=Q(weight__gte=Decimal('0.05')) & Q(weight__lte=Decimal('1.00')),
                name='chk_arena_mapping_weight_range',
            ),
        ]

    def __str__(self):
        return f"{self.question_version} -> [{self.competency.code}] (weight: {self.weight})"

    def clean(self):
        super().clean()
        if self.question_version_id and self.competency_id:
            # Resolve question_version primary competency and status
            qv = getattr(self, 'question_version', None)
            qv_primary_id = qv.primary_competency_id if qv else None
            qv_status = qv.status if qv else None
            if not qv or qv_primary_id is None or qv_status is None:
                row = QuestionVersion.objects.filter(pk=self.question_version_id).values('primary_competency_id', 'status').first()
                if row:
                    qv_primary_id = row['primary_competency_id']
                    qv_status = row['status']

            # Primary mapping consistency checks
            if self.is_primary:
                if qv_primary_id and self.competency_id != qv_primary_id:
                    raise ValidationError({
                        'competency': _("A primary mapping must reference the question version's primary competency.")
                    })
                # Check for existing primary mapping on this question version
                existing_primary = QuestionCompetencyMapping.objects.filter(
                    question_version_id=self.question_version_id,
                    is_primary=True,
                )
                if self.pk:
                    existing_primary = existing_primary.exclude(pk=self.pk)
                if existing_primary.exists():
                    raise ValidationError({
                        'is_primary': _("A question version cannot have more than one primary competency mapping.")
                    })
            else:
                if qv_primary_id and self.competency_id == qv_primary_id:
                    raise ValidationError({
                        'competency': _("The primary competency cannot also be added as a secondary mapping.")
                    })

            # Immutability check on published parent version
            if qv_status and qv_status in ('PUBLISHED', 'ARCHIVED', 'DEPRECATED'):
                exists_in_db = self.pk and QuestionCompetencyMapping.objects.filter(pk=self.pk).exists()
                if exists_in_db:
                    orig = QuestionCompetencyMapping.objects.filter(pk=self.pk).values(
                        'competency_id', 'weight', 'is_primary'
                    ).first()
                    if orig and (orig['competency_id'] != self.competency_id or
                                 orig['weight'] != self.weight or
                                 orig['is_primary'] != self.is_primary):
                        raise ValidationError(
                            _("Competency mappings for a published question version are immutable.")
                        )
                else:
                    raise ValidationError(
                        _("Cannot add competency mappings to an already published question version.")
                    )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class QuestionVersionTag(models.Model):
    """
    Many-to-Many association between QuestionVersion and Tag.
    """
    id = models.BigAutoField(primary_key=True)
    question_version = models.ForeignKey(
        QuestionVersion,
        on_delete=models.CASCADE,
        related_name='version_tags',
        verbose_name=_('question version'),
    )
    tag = models.ForeignKey(
        Tag,
        on_delete=models.CASCADE,
        related_name='tagged_versions',
        verbose_name=_('tag'),
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)

    class Meta:
        db_table = 'arena_question_version_tag'
        verbose_name = _('question version tag')
        verbose_name_plural = _('question version tags')
        constraints = [
            models.UniqueConstraint(
                fields=['question_version', 'tag'],
                name='uq_arena_version_tag_pair',
            ),
        ]

    def __str__(self):
        return f"{self.question_version} <-> #{self.tag.slug}"

    def clean(self):
        super().clean()
        if self.question_version_id:
            qv = QuestionVersion.objects.filter(pk=self.question_version_id).values('status').first()
            if qv and qv['status'] in ('PUBLISHED', 'ARCHIVED', 'DEPRECATED'):
                raise ValidationError(
                    _("Cannot modify tags on an already published question version.")
                )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
