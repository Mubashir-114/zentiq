"""
Models for ZENTIQ Assessment Execution Engine.
Application: apps.assessments

Provides permanent Assessment catalog anchors, immutable AssessmentVersions,
ordered Question compositions, historical AssessmentAttempts, unconditional
ActiveAssessmentReservations, AttemptQuestions with snapshots, AttemptAnswers,
and append-only AttemptEvents.
"""
import uuid
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import F, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.arena.models import QuestionVersion


VALID_ASSESSMENT_VERSION_TRANSITIONS = {
    'DRAFT': {'PUBLISHED'},
    'PUBLISHED': {'ARCHIVED'},
    'ARCHIVED': set(),
}


class Assessment(models.Model):
    """
    Permanent canonical identity anchor for an assessment series.
    Provides a stable external code and maintains a reference to the active published version.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(
        _('assessment code'),
        max_length=50,
        unique=True,
        db_index=True,
        help_text=_('Standardized canonical identifier (e.g. ASM-SYS-ARCH-001).'),
    )
    title = models.CharField(
        _('title'),
        max_length=200,
        help_text=_('Canonical catalog title of the assessment.'),
    )
    description = models.TextField(
        _('description'),
        blank=True,
        help_text=_('Catalog description and assessment scope.'),
    )
    active_version = models.ForeignKey(
        'AssessmentVersion',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name=_('active published version'),
        help_text=_('Current published version served for live attempts.'),
    )
    is_deprecated = models.BooleanField(
        _('is deprecated'),
        default=False,
        db_index=True,
        help_text=_('Designates whether the entire assessment series is retired from future attempts.'),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='authored_assessments',
        verbose_name=_('created by'),
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        db_table = 'assessments_assessment'
        verbose_name = _('assessment')
        verbose_name_plural = _('assessments')
        ordering = ['code']
        indexes = [
            models.Index(fields=['is_deprecated', 'created_at']),
        ]

    def __str__(self):
        return f"{self.code} - {self.title}"

    def clean(self):
        super().clean()
        if self.pk:
            orig = Assessment.objects.filter(pk=self.pk).values('code').first()
            if orig and orig['code'] != self.code:
                raise ValidationError({'code': _("Assessment code is immutable after creation.")})

        if self.is_deprecated and self.active_version_id:
            raise ValidationError({
                'active_version': _("A deprecated assessment cannot have an active version.")
            })

        if self.active_version_id:
            av = getattr(self, 'active_version', None)
            av_assessment_id = av.assessment_id if av else None
            av_status = av.status if av else None
            if not av or av_assessment_id is None or av_status is None:
                row = AssessmentVersion.objects.filter(pk=self.active_version_id).values('assessment_id', 'status').first()
                if row:
                    av_assessment_id = row['assessment_id']
                    av_status = row['status']
                else:
                    raise ValidationError({'active_version': _("Referenced active version does not exist.")})

            if self.pk and av_assessment_id != self.pk:
                raise ValidationError({
                    'active_version': _("Active version must belong to this assessment.")
                })
            if av_status != 'PUBLISHED':
                raise ValidationError({
                    'active_version': _(f"Active version must have PUBLISHED status, but has status '{av_status}'.")
                })

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class AssessmentVersion(models.Model):
    """
    Immutable versioned snapshot of an assessment's configuration,
    presentation content, duration, and navigation rules.
    Approved lifecycle states: DRAFT -> PUBLISHED -> ARCHIVED.
    """
    STATUS_CHOICES = (
        ('DRAFT', 'Draft'),
        ('PUBLISHED', 'Published'),
        ('ARCHIVED', 'Archived'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assessment = models.ForeignKey(
        Assessment,
        on_delete=models.CASCADE,
        related_name='versions',
        verbose_name=_('parent assessment'),
    )
    version_number = models.PositiveIntegerField(
        _('version number'),
        default=1,
        validators=[MinValueValidator(1)],
        help_text=_('Monotonically increasing version counter for this assessment.'),
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
        help_text=_('Display title of this assessment version.'),
    )
    description = models.TextField(
        _('description'),
        blank=True,
        help_text=_('Instructions, syllabus, and guidelines for the test taker.'),
    )
    time_limit_seconds = models.PositiveIntegerField(
        _('time limit (seconds)'),
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text=_('Authoritative assessment duration in seconds. Null indicates untimed assessment.'),
    )
    allow_backtracking = models.BooleanField(
        _('allow backtracking'),
        default=True,
        help_text=_('Whether candidate can navigate backwards to previous questions.'),
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
        related_name='created_assessment_versions',
        verbose_name=_('author'),
    )
    published_at = models.DateTimeField(
        _('published at'),
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        db_table = 'assessments_assessment_version'
        verbose_name = _('assessment version')
        verbose_name_plural = _('assessment versions')
        ordering = ['assessment', '-version_number']
        constraints = [
            models.UniqueConstraint(
                fields=['assessment', 'version_number'],
                name='uq_assessments_ver_number',
            ),
            models.CheckConstraint(
                condition=Q(version_number__gt=0),
                name='chk_assessments_ver_number_gt_0',
            ),
            models.CheckConstraint(
                condition=Q(time_limit_seconds__isnull=True) | Q(time_limit_seconds__gt=0),
                name='chk_assessments_ver_time_limit',
            ),
            models.CheckConstraint(
                condition=Q(status__in=['DRAFT', 'PUBLISHED', 'ARCHIVED']),
                name='chk_assessments_ver_status_valid',
            ),
        ]
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['assessment', 'status']),
        ]

    def __str__(self):
        return f"{self.assessment.code} (v{self.version_number}) [{self.status}]"

    @property
    def duration_minutes(self):
        """Helper read-only property returning duration in integer minutes if configured."""
        if self.time_limit_seconds:
            return self.time_limit_seconds // 60
        return None

    def clean(self):
        super().clean()
        exists_in_db = self.pk and AssessmentVersion.objects.filter(pk=self.pk).exists()
        if not exists_in_db:
            if self.status != 'DRAFT':
                raise ValidationError({
                    'status': _(f"New assessment versions must be created with DRAFT status, not '{self.status}'.")
                })
        else:
            orig = AssessmentVersion.objects.filter(pk=self.pk).values(
                'status', 'title', 'description', 'time_limit_seconds', 'allow_backtracking',
                'version_number', 'assessment_id', 'created_by_id', 'published_at', 'change_summary'
            ).first()
            if orig:
                if orig['status'] != self.status:
                    allowed = VALID_ASSESSMENT_VERSION_TRANSITIONS.get(orig['status'], set())
                    if self.status not in allowed:
                        raise ValidationError({
                            'status': _(
                                f"Invalid status transition from '{orig['status']}' to '{self.status}'. "
                                f"Permitted transitions: {sorted(list(allowed)) or 'None (terminal state)'}."
                            )
                        })

                if orig['status'] in ('PUBLISHED', 'ARCHIVED'):
                    forbidden_fields = []
                    immutable_checks = [
                        ('title', self.title),
                        ('description', self.description),
                        ('time_limit_seconds', self.time_limit_seconds),
                        ('allow_backtracking', self.allow_backtracking),
                        ('version_number', self.version_number),
                        ('assessment_id', self.assessment_id),
                        ('created_by_id', self.created_by_id),
                        ('published_at', self.published_at),
                        ('change_summary', self.change_summary),
                    ]
                    for field_name, new_val in immutable_checks:
                        if orig[field_name] != new_val:
                            forbidden_fields.append(field_name)

                    if forbidden_fields:
                        raise ValidationError(
                            _("Published assessment versions are immutable. Forbidden modifications on: %s. "
                              "Create a new assessment version instead.") % ", ".join(forbidden_fields)
                        )

    def save(self, *args, **kwargs):
        self.clean()
        if self.status == 'PUBLISHED' and not self.published_at:
            self.published_at = timezone.now()

        # Update fields check
        update_fields = kwargs.get('update_fields')
        if update_fields is None and len(args) > 3:
            update_fields = args[3]
        if args:
            param_names = ['force_insert', 'force_update', 'using', 'update_fields']
            for name, val in zip(param_names, args):
                kwargs.setdefault(name, val)
            args = ()

        status_will_persist = (update_fields is None) or ('status' in update_fields)

        # Enforce active-version invariant when version transitions to ARCHIVED
        if self.pk and self.status == 'ARCHIVED' and status_will_persist:
            with transaction.atomic():
                assessment = Assessment.objects.select_for_update().get(pk=self.assessment_id)
                if assessment.is_deprecated:
                    # Deprecated assessment must NEVER have an active version
                    if assessment.active_version_id is not None:
                        assessment.active_version = None
                        assessment.save(update_fields=['active_version', 'updated_at'])
                elif assessment.active_version_id == self.pk:
                    # Active version transitioned: reconcile only to highest remaining PUBLISHED version
                    replacement = (
                        AssessmentVersion.objects.filter(
                            assessment_id=self.assessment_id,
                            status='PUBLISHED',
                        )
                        .exclude(pk=self.pk)
                        .order_by('-version_number')
                        .first()
                    )
                    assessment.active_version = replacement
                    assessment.save(update_fields=['active_version', 'updated_at'])

                super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)


class AssessmentVersionQuestion(models.Model):
    """
    Ordered composition of a QuestionVersion within an AssessmentVersion.
    Maintains exact question-version FK, explicit ordering, weight, and
    validates canonical Question uniqueness within the assessment version.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assessment_version = models.ForeignKey(
        AssessmentVersion,
        on_delete=models.CASCADE,
        related_name='questions',
        verbose_name=_('assessment version'),
    )
    question_version = models.ForeignKey(
        QuestionVersion,
        on_delete=models.PROTECT,
        related_name='assessment_version_questions',
        verbose_name=_('question version'),
    )
    order_index = models.PositiveIntegerField(
        _('order index'),
        validators=[MinValueValidator(1)],
        help_text=_('1-based presentation sequence within the assessment.'),
    )
    weight = models.DecimalField(
        _('question weight'),
        max_digits=5,
        decimal_places=2,
        default=Decimal('1.00'),
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text=_('Relative evaluation weight of the question.'),
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)

    class Meta:
        db_table = 'assessments_version_question'
        verbose_name = _('assessment version question')
        verbose_name_plural = _('assessment version questions')
        ordering = ['assessment_version', 'order_index']
        constraints = [
            models.UniqueConstraint(
                fields=['assessment_version', 'question_version'],
                name='uq_assessments_ver_q_version',
            ),
            models.UniqueConstraint(
                fields=['assessment_version', 'order_index'],
                name='uq_assessments_ver_order_index',
            ),
            models.CheckConstraint(
                condition=Q(order_index__gte=1),
                name='chk_assessments_ver_q_order_gte_1',
            ),
            models.CheckConstraint(
                condition=Q(weight__gt=Decimal('0.00')),
                name='chk_assessments_ver_q_weight_gt_0',
            ),
        ]
        indexes = [
            models.Index(fields=['assessment_version', 'order_index']),
            models.Index(fields=['question_version']),
        ]

    def __str__(self):
        return f"{self.assessment_version} [Q#{self.order_index}: {self.question_version}]"

    def clean(self):
        super().clean()

        # Prevent duplicate canonical question in assessment version
        if self.assessment_version_id and self.question_version_id:
            qv = getattr(self, 'question_version', None)
            canonical_q_id = qv.question_id if qv else None
            if canonical_q_id is None:
                canonical_q_id = QuestionVersion.objects.filter(pk=self.question_version_id).values_list('question_id', flat=True).first()

            if canonical_q_id:
                conflict = AssessmentVersionQuestion.objects.filter(
                    assessment_version_id=self.assessment_version_id,
                    question_version__question_id=canonical_q_id,
                )
                if self.pk:
                    conflict = conflict.exclude(pk=self.pk)
                if conflict.exists():
                    raise ValidationError({
                        'question_version': _("Another version of this canonical Question is already included in this assessment version.")
                    })

        # Prevent duplicate order_index in assessment version
        if self.assessment_version_id and self.order_index:
            order_conflict = AssessmentVersionQuestion.objects.filter(
                assessment_version_id=self.assessment_version_id,
                order_index=self.order_index,
            )
            if self.pk:
                order_conflict = order_conflict.exclude(pk=self.pk)
            if order_conflict.exists():
                raise ValidationError({
                    'order_index': _("A question with this order index already exists in this assessment version.")
                })

        # Parent assessment version immutability
        if self.assessment_version_id:
            av = getattr(self, 'assessment_version', None)
            av_status = av.status if av else None
            if not av_status:
                av_status = AssessmentVersion.objects.filter(pk=self.assessment_version_id).values_list('status', flat=True).first()
            if av_status in ('PUBLISHED', 'ARCHIVED'):
                raise ValidationError(_("Cannot modify questions for an already published assessment version."))

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.assessment_version_id:
            av_status = getattr(self.assessment_version, 'status', None)
            if not av_status:
                av_status = AssessmentVersion.objects.filter(pk=self.assessment_version_id).values_list('status', flat=True).first()
            if av_status in ('PUBLISHED', 'ARCHIVED'):
                raise ValidationError(_("Cannot remove questions from an already published assessment version."))
        super().delete(*args, **kwargs)


class AssessmentAttempt(models.Model):
    """
    Historical execution record of an assessment attempt by a user.
    Maintains exact assessment-version snapshot, approved lifecycle statuses:
    IN_PROGRESS, SUBMITTED, EXPIRED, CANCELLED.
    Counters and idempotency guarantees.
    """
    STATUS_CHOICES = (
        ('IN_PROGRESS', 'In Progress'),
        ('SUBMITTED', 'Submitted'),
        ('EXPIRED', 'Expired'),
        ('CANCELLED', 'Cancelled'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='assessment_attempts',
        verbose_name=_('user'),
    )
    assessment = models.ForeignKey(
        Assessment,
        on_delete=models.PROTECT,
        related_name='attempts',
        verbose_name=_('assessment'),
    )
    assessment_version = models.ForeignKey(
        AssessmentVersion,
        on_delete=models.PROTECT,
        related_name='attempts',
        verbose_name=_('assessment version'),
    )
    attempt_number = models.PositiveIntegerField(
        _('attempt number'),
        default=1,
        validators=[MinValueValidator(1)],
        help_text=_('Sequential attempt counter for this user on this assessment.'),
    )
    status = models.CharField(
        _('lifecycle status'),
        max_length=20,
        choices=STATUS_CHOICES,
        default='IN_PROGRESS',
        db_index=True,
    )
    started_at = models.DateTimeField(_('started at'), default=timezone.now)
    completed_at = models.DateTimeField(_('completed at'), null=True, blank=True)
    deadline = models.DateTimeField(
        _('deadline'),
        null=True,
        blank=True,
        help_text=_('Server-enforced deadline for timed attempts.'),
    )
    time_limit_seconds = models.PositiveIntegerField(
        _('snapshotted time limit (seconds)'),
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text=_('Frozen time limit in seconds at attempt creation.'),
    )
    allow_backtracking = models.BooleanField(
        _('snapshotted allow backtracking'),
        default=True,
        help_text=_('Frozen navigation setting at attempt creation.'),
    )
    current_order_index = models.PositiveIntegerField(
        _('current order index'),
        default=1,
        validators=[MinValueValidator(1)],
        help_text=_('Current question order index the user is viewing/answering.'),
    )
    question_count = models.PositiveIntegerField(
        _('question count'),
        default=0,
        validators=[MinValueValidator(0)],
        help_text=_('Total questions in this attempt.'),
    )
    answer_count = models.PositiveIntegerField(
        _('answer count'),
        default=0,
        validators=[MinValueValidator(0)],
        help_text=_('Total questions answered so far.'),
    )
    idempotency_key = models.CharField(
        _('idempotency key'),
        max_length=64,
        db_index=True,
        help_text=_('Mandatory client/server idempotency key for attempt creation.'),
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        db_table = 'assessments_attempt'
        verbose_name = _('assessment attempt')
        verbose_name_plural = _('assessment attempts')
        ordering = ['-started_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'assessment', 'idempotency_key'],
                name='uq_assessments_attempt_idempotency',
            ),
            models.UniqueConstraint(
                fields=['user', 'assessment', 'attempt_number'],
                name='uq_assessments_attempt_user_asm_num',
            ),
            models.CheckConstraint(
                condition=Q(attempt_number__gte=1),
                name='chk_assessments_attempt_number_gte_1',
            ),
            models.CheckConstraint(
                condition=Q(current_order_index__gte=1),
                name='chk_assessments_attempt_curr_order_gte_1',
            ),
            models.CheckConstraint(
                condition=Q(question_count__gte=0),
                name='chk_assessments_attempt_q_count_gte_0',
            ),
            models.CheckConstraint(
                condition=Q(answer_count__gte=0),
                name='chk_assessments_attempt_ans_count_gte_0',
            ),
            models.CheckConstraint(
                condition=Q(answer_count__lte=F('question_count')),
                name='chk_assessments_attempt_ans_lte_q',
            ),
            models.CheckConstraint(
                condition=Q(time_limit_seconds__isnull=True) | Q(time_limit_seconds__gt=0),
                name='chk_assessments_attempt_time_limit',
            ),
            models.CheckConstraint(
                condition=Q(status__in=['IN_PROGRESS', 'SUBMITTED', 'EXPIRED', 'CANCELLED']),
                name='chk_assessments_attempt_status_valid',
            ),
        ]
        indexes = [
            models.Index(fields=['user', 'assessment', 'status']),
            models.Index(fields=['assessment_version', 'status']),
            models.Index(fields=['status', 'started_at']),
        ]

    def __str__(self):
        return f"Attempt #{self.attempt_number} by {self.user} on {self.assessment.code} [{self.status}]"

    def clean(self):
        super().clean()
        if not self.idempotency_key or not self.idempotency_key.strip():
            raise ValidationError({'idempotency_key': _("Mandatory idempotency key must not be blank.")})

        # Validate that assessment matches assessment_version's parent assessment
        if self.assessment_id and self.assessment_version_id:
            av_assessment_id = getattr(self.assessment_version, 'assessment_id', None)
            if av_assessment_id is None:
                av_assessment_id = AssessmentVersion.objects.filter(pk=self.assessment_version_id).values_list('assessment_id', flat=True).first()
            if av_assessment_id and av_assessment_id != self.assessment_id:
                raise ValidationError({
                    'assessment_version': _("AssessmentVersion parent does not match the referenced Assessment.")
                })

        # Snapshot duration & navigation from version if not explicitly set
        if self.assessment_version_id:
            av = getattr(self, 'assessment_version', None)
            if not av:
                av = AssessmentVersion.objects.filter(pk=self.assessment_version_id).first()
            if av:
                if self.time_limit_seconds is None and av.time_limit_seconds is not None:
                    self.time_limit_seconds = av.time_limit_seconds
                if self._state.adding and self.allow_backtracking is None:
                    self.allow_backtracking = av.allow_backtracking

        if self.answer_count > self.question_count:
            raise ValidationError({'answer_count': _("Answer count cannot exceed question count.")})

    def save(self, *args, **kwargs):
        self.clean()
        if self.status in ('SUBMITTED', 'EXPIRED', 'CANCELLED'):
            if not self.completed_at:
                self.completed_at = timezone.now()
            if self.pk:
                ActiveAssessmentReservation.objects.filter(attempt_id=self.pk).delete()
        super().save(*args, **kwargs)


class ActiveAssessmentReservation(models.Model):
    """
    Guarantees unconditional uniqueness of an active attempt per (user, assessment).
    Avoids conditional/partial unique indexing, providing 100% portable MySQL 8.4
    and SQLite concurrency safety.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='active_assessment_reservations',
        verbose_name=_('user'),
    )
    assessment = models.ForeignKey(
        Assessment,
        on_delete=models.CASCADE,
        related_name='active_reservations',
        verbose_name=_('assessment'),
    )
    attempt = models.OneToOneField(
        AssessmentAttempt,
        on_delete=models.CASCADE,
        related_name='active_reservation',
        verbose_name=_('active attempt'),
    )
    idempotency_key = models.CharField(
        _('idempotency key'),
        max_length=64,
        help_text=_('Idempotency key of the active attempt reservation.'),
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)

    class Meta:
        db_table = 'assessments_reservation'
        verbose_name = _('active assessment reservation')
        verbose_name_plural = _('active assessment reservations')
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'assessment'],
                name='uq_assessments_reservation_user_asm',
            ),
        ]
        indexes = [
            models.Index(fields=['user', 'assessment']),
        ]

    def __str__(self):
        return f"ActiveReservation: {self.user} -> {self.assessment.code} (Attempt: {self.attempt_id})"

    def clean(self):
        super().clean()
        if self.attempt_id:
            attempt = getattr(self, 'attempt', None)
            if not attempt:
                attempt = AssessmentAttempt.objects.filter(pk=self.attempt_id).first()
            if attempt:
                if not self.user_id:
                    self.user = attempt.user
                elif self.user_id != attempt.user_id:
                    raise ValidationError({'user': _("Reservation user must match attempt user.")})

                if not self.assessment_id:
                    self.assessment = attempt.assessment
                elif self.assessment_id != attempt.assessment_id:
                    raise ValidationError({'assessment': _("Reservation assessment must match attempt assessment.")})

                if not self.idempotency_key:
                    self.idempotency_key = attempt.idempotency_key
                elif self.idempotency_key != attempt.idempotency_key:
                    raise ValidationError({'idempotency_key': _("Reservation idempotency key must match attempt idempotency key.")})

                if attempt.status != 'IN_PROGRESS':
                    raise ValidationError({'attempt': _("Reservation can only be created for an IN_PROGRESS attempt.")})

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class AttemptQuestion(models.Model):
    """
    A Question instance bound to an AssessmentAttempt.
    Captures presentation snapshots, order, weight, and references exact QuestionVersion.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt = models.ForeignKey(
        AssessmentAttempt,
        on_delete=models.CASCADE,
        related_name='questions',
        verbose_name=_('attempt'),
    )
    question_version = models.ForeignKey(
        QuestionVersion,
        on_delete=models.PROTECT,
        related_name='attempt_questions',
        verbose_name=_('question version'),
    )
    order_index = models.PositiveIntegerField(
        _('order index'),
        validators=[MinValueValidator(1)],
        help_text=_('1-based presentation sequence within this attempt.'),
    )
    weight = models.DecimalField(
        _('question weight'),
        max_digits=5,
        decimal_places=2,
        default=Decimal('1.00'),
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text=_('Frozen weight of this question for this attempt.'),
    )
    prompt_snapshot = models.TextField(
        _('prompt snapshot'),
        blank=True,
        help_text=_('Snapshot of question prompt at attempt generation.'),
    )
    content_payload_snapshot = models.JSONField(
        _('content payload snapshot'),
        default=dict,
        blank=True,
        help_text=_('Snapshot of presentation choices/payload at attempt generation.'),
    )
    question_type_snapshot = models.CharField(
        _('question type snapshot'),
        max_length=30,
        blank=True,
        help_text=_('Snapshot of question type at attempt generation.'),
    )
    time_limit_seconds_snapshot = models.PositiveIntegerField(
        _('time limit seconds snapshot'),
        null=True,
        blank=True,
        help_text=_('Per-question time limit if applicable.'),
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)

    class Meta:
        db_table = 'assessments_attempt_question'
        verbose_name = _('attempt question')
        verbose_name_plural = _('attempt questions')
        ordering = ['attempt', 'order_index']
        constraints = [
            models.UniqueConstraint(
                fields=['attempt', 'question_version'],
                name='uq_assessments_att_q_version',
            ),
            models.UniqueConstraint(
                fields=['attempt', 'order_index'],
                name='uq_assessments_att_order_index',
            ),
            models.CheckConstraint(
                condition=Q(order_index__gte=1),
                name='chk_assessments_att_q_order_gte_1',
            ),
            models.CheckConstraint(
                condition=Q(weight__gt=Decimal('0.00')),
                name='chk_assessments_att_q_weight_gt_0',
            ),
        ]
        indexes = [
            models.Index(fields=['attempt', 'order_index']),
            models.Index(fields=['question_version']),
        ]

    def __str__(self):
        return f"{self.attempt} [Q#{self.order_index}: {self.question_version}]"

    def clean(self):
        super().clean()

        # Auto-populate presentation snapshots from question_version if empty
        if self.question_version_id:
            qv = getattr(self, 'question_version', None)
            if not qv:
                qv = QuestionVersion.objects.filter(pk=self.question_version_id).first()
            if qv:
                if not self.prompt_snapshot:
                    self.prompt_snapshot = qv.prompt
                if not self.content_payload_snapshot:
                    self.content_payload_snapshot = qv.content_payload
                if not self.question_type_snapshot:
                    self.question_type_snapshot = qv.question_type
                if self.time_limit_seconds_snapshot is None:
                    self.time_limit_seconds_snapshot = qv.time_limit_seconds

        # Prevent duplicate canonical question within this attempt
        if self.attempt_id and self.question_version_id:
            qv = getattr(self, 'question_version', None)
            canonical_q_id = qv.question_id if qv else None
            if canonical_q_id is None:
                canonical_q_id = QuestionVersion.objects.filter(pk=self.question_version_id).values_list('question_id', flat=True).first()

            if canonical_q_id:
                conflict = AttemptQuestion.objects.filter(
                    attempt_id=self.attempt_id,
                    question_version__question_id=canonical_q_id,
                )
                if self.pk:
                    conflict = conflict.exclude(pk=self.pk)
                if conflict.exists():
                    raise ValidationError({
                        'question_version': _("Another version of this canonical Question is already included in this attempt.")
                    })

        # Prevent duplicate order_index within this attempt
        if self.attempt_id and self.order_index:
            order_conflict = AttemptQuestion.objects.filter(
                attempt_id=self.attempt_id,
                order_index=self.order_index,
            )
            if self.pk:
                order_conflict = order_conflict.exclude(pk=self.pk)
            if order_conflict.exists():
                raise ValidationError({
                    'order_index': _("A question with this order index already exists in this attempt.")
                })

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class AttemptAnswer(models.Model):
    """
    Candidate answer submission for an AttemptQuestion.
    Enforces strictly one answer record per attempt question via OneToOne relationship.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt_question = models.OneToOneField(
        AttemptQuestion,
        on_delete=models.CASCADE,
        related_name='answer',
        verbose_name=_('attempt question'),
    )
    answer_payload = models.JSONField(
        _('answer payload'),
        default=dict,
        blank=True,
        help_text=_('Candidate answer payload (e.g. selected option IDs, numeric value, text).'),
    )
    is_answered = models.BooleanField(
        _('is answered'),
        default=False,
        db_index=True,
        help_text=_('Designates whether this question has been answered.'),
    )
    answered_at = models.DateTimeField(
        _('answered at'),
        null=True,
        blank=True,
        help_text=_('Server timestamp when the answer was recorded.'),
    )
    redacted_at = models.DateTimeField(
        _('redacted at'),
        null=True,
        blank=True,
        help_text=_(
            'Authoritative indicator that candidate answer content has been redacted. '
            'Redacted answers cannot be evaluated or regraded.'
        ),
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        db_table = 'assessments_attempt_answer'
        verbose_name = _('attempt answer')
        verbose_name_plural = _('attempt answers')
        constraints = [
            models.UniqueConstraint(
                fields=['attempt_question'],
                name='uq_assessments_answer_attempt_question',
            ),
        ]

    def __str__(self):
        return f"Answer for {self.attempt_question} [answered={self.is_answered}]"

    def clean(self):
        super().clean()
        if self.answer_payload:
            self.is_answered = True
            if not self.answered_at:
                self.answered_at = timezone.now()
        elif self.is_answered and not self.answered_at:
            self.answered_at = timezone.now()

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class AttemptEventQuerySet(models.QuerySet):
    """
    QuerySet that prevents bulk update and delete operations on append-only audit event logs.
    """
    def update(self, **kwargs):
        raise ValidationError(_("AttemptEvent records are append-only audit entries and cannot be updated."))

    def delete(self):
        raise ValidationError(_("AttemptEvent records are append-only audit entries and cannot be deleted."))


class AttemptEvent(models.Model):
    """
    Append-only audit trail for candidate actions during an AssessmentAttempt.
    Modifications are rejected to preserve audit integrity.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt = models.ForeignKey(
        AssessmentAttempt,
        on_delete=models.PROTECT,
        related_name='events',
        verbose_name=_('attempt'),
    )
    event_type = models.CharField(
        _('event type'),
        max_length=50,
        db_index=True,
        help_text=_('Classification of the audit event (e.g. ATTEMPT_STARTED, ANSWER_SUBMITTED).'),
    )
    payload = models.JSONField(
        _('audit payload'),
        default=dict,
        blank=True,
        help_text=_('Minimal structured event metadata without IP or user-agent.'),
    )
    created_at = models.DateTimeField(
        _('timestamp'),
        default=timezone.now,
        editable=False,
        db_index=True,
    )

    objects = AttemptEventQuerySet.as_manager()

    class Meta:
        db_table = 'assessments_attempt_event'
        verbose_name = _('attempt event')
        verbose_name_plural = _('attempt events')
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['attempt', 'created_at']),
            models.Index(fields=['event_type', 'created_at']),
        ]

    def __str__(self):
        return f"Event [{self.event_type}] for Attempt {self.attempt_id} at {self.created_at}"

    def clean(self):
        super().clean()
        if self.pk and AttemptEvent.objects.filter(pk=self.pk).exists():
            raise ValidationError(_("AttemptEvent records are append-only audit entries and cannot be modified."))

    def save(self, *args, **kwargs):
        if self.pk and AttemptEvent.objects.filter(pk=self.pk).exists():
            raise ValidationError(_("AttemptEvent records are append-only audit entries and cannot be modified."))
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("AttemptEvent records are append-only audit entries and cannot be deleted."))


# ---------------------------------------------------------------------------
# Phase 2E.2 — Scoring & Evaluation foundation (Rev. 3.7 frozen architecture)
# ---------------------------------------------------------------------------

RESULT_STATUS_CHOICES = (
    ('PROVISIONAL', 'Provisional'),
    ('FINAL', 'Final'),
)

EVALUATION_STATUS_CHOICES = (
    ('COMPLETE', 'Complete'),
    ('AWAITING_MANUAL_GRADING', 'Awaiting manual grading'),
    ('INCOMPLETE_COVERAGE', 'Incomplete coverage'),
    ('CONFIGURATION_UNGRADABLE', 'Configuration ungradable'),
)

OUTCOME_CHOICES = (
    ('CORRECT', 'Correct'),
    ('PARTIALLY_CORRECT', 'Partially correct'),
    ('INCORRECT', 'Incorrect'),
    ('UNANSWERED', 'Unanswered'),
    ('UNGRADED', 'Ungraded'),
    ('PENDING_MANUAL', 'Pending manual evaluation'),
)

DISPOSITION_CHOICES = (
    ('SCORED', 'Scored'),
    ('EXCLUDED', 'Excluded'),
    ('UNDECIDED', 'Undecided'),
)

ANSWER_PRESENCE_CHOICES = (
    ('PRESENT', 'Present'),
    ('ABSENT', 'Absent'),
)

ABSENCE_REASON_CHOICES = (
    ('SKIPPED', 'Skipped'),
    ('NOT_REACHED', 'Not reached'),
    ('EMPTY_SUBMISSION', 'Empty submission'),
)

TERMINAL_STATUS_CHOICES = (
    ('SUBMITTED', 'Submitted'),
    ('EXPIRED', 'Expired'),
    ('CANCELLED', 'Cancelled'),
)

OUTBOX_STATE_CHOICES = (
    ('PENDING', 'Pending'),
    ('CLAIMED', 'Claimed'),
    ('PROCESSED', 'Processed'),
    ('DEAD', 'Dead'),
)

RESULT_TERMINAL_STATUSES = ('SUBMITTED', 'EXPIRED', 'CANCELLED')


def _reject_persisted_mutation(instance, label):
    """Rejects updates to write-once rows (insert-only immutability guard)."""
    if instance.pk and type(instance).objects.filter(pk=instance.pk).exists():
        raise ValidationError(_(f"{label} records are immutable and cannot be modified."))


class ImmutableResultQuerySet(models.QuerySet):
    """QuerySet that blocks bulk mutation of write-once result records."""

    def update(self, **kwargs):
        raise ValidationError(_("Result records are immutable and cannot be updated in bulk."))

    def delete(self):
        raise ValidationError(_("Result records are immutable and cannot be deleted in bulk."))


class AttemptTerminalSnapshot(models.Model):
    """
    Immutable terminal-transition policy snapshot (Phase 2E.2).
    Freezes the three independent eligibility flags and the policy version in force
    at the moment an attempt reached a terminal status, so later policy changes can
    never retroactively evaluate, reward, or credit a past attempt.
    Created only by the terminal transition services, inside their transaction.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt = models.OneToOneField(
        AssessmentAttempt,
        on_delete=models.PROTECT,
        related_name='terminal_snapshot',
        verbose_name=_('attempt'),
    )
    terminal_status = models.CharField(
        _('terminal status'),
        max_length=20,
        choices=TERMINAL_STATUS_CHOICES,
    )
    evaluate_eligible = models.BooleanField(_('evaluate eligible'), default=False)
    mastery_eligible = models.BooleanField(_('mastery eligible'), default=False)
    xp_eligible = models.BooleanField(_('xp eligible'), default=False)
    policy_version = models.CharField(_('policy version'), max_length=30)
    decision_source = models.CharField(_('decision source'), max_length=20)
    decided_at = models.DateTimeField(_('decided at'), default=timezone.now)

    objects = ImmutableResultQuerySet.as_manager()

    class Meta:
        db_table = 'assessments_attempt_terminal_snapshot'
        verbose_name = _('attempt terminal snapshot')
        verbose_name_plural = _('attempt terminal snapshots')
        constraints = [
            models.CheckConstraint(
                condition=~Q(terminal_status='IN_PROGRESS'),
                name='chk_assessments_terminal_snapshot_not_in_progress',
            ),
            models.CheckConstraint(
                condition=Q(terminal_status__in=[c[0] for c in TERMINAL_STATUS_CHOICES]),
                name='chk_assessments_terminal_snapshot_status_valid',
            ),
        ]

    def __str__(self):
        return f"TerminalSnapshot[{self.attempt_id}] = {self.terminal_status}"

    def save(self, *args, **kwargs):
        _reject_persisted_mutation(self, 'AttemptTerminalSnapshot')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("AttemptTerminalSnapshot records are immutable and cannot be deleted."))


class AttemptResultRevision(models.Model):
    """
    Immutable, complete snapshot of a single evaluation pass over an attempt.
    Revisions are never updated or deleted; supersession is expressed by a new
    revision whose ``supersedes`` pointer references the previous one, while
    AttemptResultHead names the single authoritative current revision.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt = models.ForeignKey(
        AssessmentAttempt,
        on_delete=models.PROTECT,
        related_name='result_revisions',
        verbose_name=_('attempt'),
    )
    revision_number = models.PositiveIntegerField(
        _('revision number'),
        validators=[MinValueValidator(1)],
    )
    supersedes = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='superseded_by',
        verbose_name=_('supersedes'),
    )
    terminal_snapshot = models.ForeignKey(
        AttemptTerminalSnapshot,
        on_delete=models.PROTECT,
        related_name='result_revisions',
        verbose_name=_('terminal snapshot'),
    )
    status = models.CharField(_('result status'), max_length=20, choices=RESULT_STATUS_CHOICES)
    evaluation_status = models.CharField(
        _('evaluation status'),
        max_length=30,
        choices=EVALUATION_STATUS_CHOICES,
    )
    final_score = models.DecimalField(
        _('final score'),
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    provisional_score = models.DecimalField(
        _('provisional score'),
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    total_weight = models.DecimalField(_('total weight'), max_digits=12, decimal_places=6)
    graded_weight = models.DecimalField(_('graded weight'), max_digits=12, decimal_places=6)
    excluded_weight = models.DecimalField(_('excluded weight'), max_digits=12, decimal_places=6)
    earned_weight = models.DecimalField(_('earned weight'), max_digits=12, decimal_places=6)
    question_count = models.PositiveIntegerField(_('question count'))
    answered_count = models.PositiveIntegerField(_('answered count'))
    correct_count = models.PositiveIntegerField(_('correct count'), default=0)
    incorrect_count = models.PositiveIntegerField(_('incorrect count'), default=0)
    partially_correct_count = models.PositiveIntegerField(_('partially correct count'), default=0)
    unanswered_count = models.PositiveIntegerField(_('unanswered count'), default=0)
    ungraded_count = models.PositiveIntegerField(_('ungraded count'), default=0)
    pending_manual_count = models.PositiveIntegerField(_('pending manual count'), default=0)
    scoring_policy_version = models.CharField(_('scoring policy version'), max_length=30)
    evaluator_version = models.CharField(_('evaluator version'), max_length=20)
    actor_type = models.CharField(_('actor type'), max_length=20, default='SYSTEM')
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='+',
        verbose_name=_('actor'),
    )
    reason = models.CharField(_('reason'), max_length=30, default='INITIAL_EVALUATION')
    reason_detail = models.CharField(_('reason detail'), max_length=255, blank=True, default='')
    created_at = models.DateTimeField(_('created at'), default=timezone.now)

    objects = ImmutableResultQuerySet.as_manager()

    class Meta:
        db_table = 'assessments_attempt_result_revision'
        verbose_name = _('attempt result revision')
        verbose_name_plural = _('attempt result revisions')
        ordering = ['attempt', 'revision_number']
        constraints = [
            models.UniqueConstraint(
                fields=['attempt', 'revision_number'],
                name='uq_assessments_result_revision_number',
            ),
            models.UniqueConstraint(
                fields=['attempt', 'supersedes'],
                name='uq_assessments_result_revision_supersedes',
            ),
            models.CheckConstraint(
                condition=Q(revision_number__gte=1),
                name='chk_assessments_result_revision_number_gte_1',
            ),
            models.CheckConstraint(
                condition=(
                    Q(revision_number=1, supersedes__isnull=True)
                    | Q(revision_number__gt=1, supersedes__isnull=False)
                ),
                name='chk_assessments_result_revision_chain_parity',
            ),
            models.CheckConstraint(
                condition=(
                    Q(status='FINAL', final_score__isnull=False)
                    | Q(status='PROVISIONAL', final_score__isnull=True)
                ),
                name='chk_assessments_result_revision_score_by_status',
            ),
            models.CheckConstraint(
                condition=Q(final_score__isnull=True) | Q(final_score__gte=0, final_score__lte=100),
                name='chk_assessments_result_revision_final_range',
            ),
            models.CheckConstraint(
                condition=Q(provisional_score__isnull=True)
                | Q(provisional_score__gte=0, provisional_score__lte=100),
                name='chk_assessments_result_revision_provisional_range',
            ),
            models.CheckConstraint(
                condition=Q(status='FINAL', provisional_score__isnull=True) | Q(status='PROVISIONAL'),
                name='chk_assessments_result_revision_no_provisional_when_final',
            ),
            models.CheckConstraint(
                condition=Q(status='FINAL') | Q(graded_weight=0) | Q(provisional_score__isnull=False),
                name='chk_assessments_result_revision_provisional_required',
            ),
            models.CheckConstraint(
                condition=(
                    Q(status='FINAL', evaluation_status='COMPLETE')
                    | (Q(status='PROVISIONAL') & ~Q(evaluation_status='COMPLETE'))
                ),
                name='chk_assessments_result_revision_complete_iff_final',
            ),
            models.CheckConstraint(
                condition=Q(total_weight__gt=0),
                name='chk_assessments_result_revision_total_weight_gt_0',
            ),
            models.CheckConstraint(
                condition=(
                    Q(graded_weight__gte=0)
                    & Q(excluded_weight__gte=0)
                    & Q(graded_weight__lte=F('total_weight') - F('excluded_weight'))
                ),
                name='chk_assessments_result_revision_weight_bounds',
            ),
            models.CheckConstraint(
                condition=(
                    Q(earned_weight__gte=0)
                    & Q(earned_weight__lte=F('graded_weight'))
                ),
                name='chk_assessments_result_revision_earned_bounds',
            ),
            models.CheckConstraint(
                condition=Q(status='PROVISIONAL') | Q(graded_weight__gt=0),
                name='chk_assessments_result_revision_final_requires_graded',
            ),
            models.CheckConstraint(
                condition=(
                    Q(question_count=F('correct_count') + F('incorrect_count')
                      + F('partially_correct_count') + F('unanswered_count')
                      + F('ungraded_count') + F('pending_manual_count'))
                ),
                name='chk_assessments_result_revision_outcome_counts_sum',
            ),
            models.CheckConstraint(
                condition=Q(question_count=F('answered_count') + F('unanswered_count')),
                name='chk_assessments_result_revision_answered_plus_unanswered',
            ),
            models.CheckConstraint(
                condition=(
                    Q(actor_type='SYSTEM', actor__isnull=True)
                    | Q(actor_type='STAFF', actor__isnull=False)
                ),
                name='chk_assessments_result_revision_actor_coherence',
            ),
        ]
        indexes = [
            models.Index(fields=['attempt', 'revision_number']),
            models.Index(fields=['supersedes']),
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        return f"Revision #{self.revision_number} of {self.attempt_id} [{self.status}]"

    def save(self, *args, **kwargs):
        _reject_persisted_mutation(self, 'AttemptResultRevision')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("AttemptResultRevision records are immutable and cannot be deleted."))


class AttemptResultHead(models.Model):
    """Authoritative pointer to an attempt's current result revision (mutable pointer only)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt = models.OneToOneField(
        AssessmentAttempt,
        on_delete=models.PROTECT,
        related_name='result_head',
        verbose_name=_('attempt'),
    )
    current_revision = models.ForeignKey(
        AttemptResultRevision,
        on_delete=models.PROTECT,
        related_name='+',
        verbose_name=_('current revision'),
    )
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        db_table = 'assessments_attempt_result_head'
        verbose_name = _('attempt result head')
        verbose_name_plural = _('attempt result heads')

    def __str__(self):
        return f"ResultHead[{self.attempt_id}] -> rev {self.current_revision_id}"

    def clean(self):
        super().clean()
        if self.current_revision_id and self.attempt_id:
            rev = getattr(self, 'current_revision', None)
            rev_attempt_id = rev.attempt_id if rev else None
            if rev_attempt_id is None:
                rev_attempt_id = (
                    AttemptResultRevision.objects.filter(pk=self.current_revision_id)
                    .values_list('attempt_id', flat=True)
                    .first()
                )
            if rev_attempt_id != self.attempt_id:
                raise ValidationError({
                    'current_revision': _("Current revision must belong to the head's attempt.")
                })

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class AttemptQuestionEvaluation(models.Model):
    """
    Immutable per-question outcome belonging to one result revision.
    Outcomes are children of the revision snapshot: superseding a result creates a
    complete new outcome set rather than mutating individual rows.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    result_revision = models.ForeignKey(
        AttemptResultRevision,
        on_delete=models.PROTECT,
        related_name='question_evaluations',
        verbose_name=_('result revision'),
    )
    attempt_question = models.ForeignKey(
        AttemptQuestion,
        on_delete=models.PROTECT,
        related_name='evaluations',
        verbose_name=_('attempt question'),
    )
    outcome = models.CharField(_('outcome'), max_length=20, choices=OUTCOME_CHOICES)
    disposition = models.CharField(_('disposition'), max_length=20, choices=DISPOSITION_CHOICES)
    awarded_fraction = models.DecimalField(
        _('awarded fraction'),
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
    )
    awarded_points = models.DecimalField(
        _('awarded points'), max_digits=12, decimal_places=6, null=True, blank=True,
    )
    max_points = models.DecimalField(_('max points'), max_digits=12, decimal_places=6)
    grading_strategy = models.CharField(_('grading strategy'), max_length=30, blank=True, default='')
    evaluation_config_hash = models.CharField(
        _('evaluation config hash'), max_length=64, blank=True, default='',
    )
    evaluator_version = models.CharField(_('evaluator version'), max_length=20, blank=True, default='')
    ungraded_reason = models.CharField(_('ungraded reason'), max_length=30, blank=True, default='')
    excluded_reason = models.CharField(_('excluded reason'), max_length=30, blank=True, default='')
    answer_presence = models.CharField(
        _('answer presence'), max_length=10, choices=ANSWER_PRESENCE_CHOICES, default='ABSENT',
    )
    absence_reason = models.CharField(
        _('absence reason'), max_length=20, choices=ABSENCE_REASON_CHOICES, blank=True, default='',
    )
    answer_payload_hash = models.CharField(
        _('answer payload hash'), max_length=64, blank=True, default='',
    )
    answer_canonicalization_version = models.CharField(
        _('answer canonicalization version'), max_length=20, default='answer_canon_v1',
    )
    details = models.JSONField(_('details'), default=dict, blank=True)
    created_at = models.DateTimeField(_('created at'), default=timezone.now)

    objects = ImmutableResultQuerySet.as_manager()

    class Meta:
        db_table = 'assessments_attempt_question_evaluation'
        verbose_name = _('attempt question evaluation')
        verbose_name_plural = _('attempt question evaluations')
        ordering = ['result_revision', 'attempt_question__order_index']
        constraints = [
            models.UniqueConstraint(
                fields=['result_revision', 'attempt_question'],
                name='uq_assessments_question_eval_revision_question',
            ),
            models.CheckConstraint(
                condition=(
                    Q(outcome__in=['UNGRADED', 'PENDING_MANUAL'], disposition='UNDECIDED')
                    | (~Q(outcome__in=['UNGRADED', 'PENDING_MANUAL']) & ~Q(disposition='UNDECIDED'))
                ),
                name='chk_assessments_question_eval_undecided_pairing',
            ),
            models.CheckConstraint(
                condition=(
                    Q(disposition='SCORED', awarded_fraction__isnull=False)
                    | (Q(disposition__in=['EXCLUDED', 'UNDECIDED']) & Q(awarded_fraction__isnull=True))
                ),
                name='chk_assessments_question_eval_scored_fraction',
            ),
            models.CheckConstraint(
                condition=Q(awarded_fraction__isnull=True)
                | Q(awarded_fraction__gte=0, awarded_fraction__lte=1),
                name='chk_assessments_question_eval_fraction_range',
            ),
            models.CheckConstraint(
                condition=(
                    Q(outcome='CORRECT', awarded_fraction=1)
                    | Q(outcome='INCORRECT', awarded_fraction=0)
                    | Q(outcome='PARTIALLY_CORRECT', awarded_fraction__gt=0, awarded_fraction__lt=1)
                    | Q(outcome='UNANSWERED', awarded_fraction__isnull=True)
                    | Q(outcome='UNANSWERED', awarded_fraction=0)
                    | Q(outcome__in=['UNGRADED', 'PENDING_MANUAL'], awarded_fraction__isnull=True)
                ),
                name='chk_assessments_question_eval_outcome_fraction',
            ),
            models.CheckConstraint(
                condition=(
                    Q(disposition='EXCLUDED') & ~Q(excluded_reason='')
                    | (~Q(disposition='EXCLUDED') & Q(excluded_reason=''))
                ),
                name='chk_assessments_question_eval_excluded_reason',
            ),
            models.CheckConstraint(
                condition=(
                    Q(outcome__in=['UNGRADED', 'PENDING_MANUAL']) & ~Q(ungraded_reason='')
                    | (~Q(outcome__in=['UNGRADED', 'PENDING_MANUAL']) & Q(ungraded_reason=''))
                ),
                name='chk_assessments_question_eval_ungraded_reason',
            ),
            models.CheckConstraint(
                condition=(
                    Q(answer_presence='PRESENT', absence_reason='')
                    | Q(answer_presence='ABSENT')
                ),
                name='chk_assessments_question_eval_presence_absence',
            ),
        ]
        indexes = [
            models.Index(fields=['attempt_question', 'created_at']),
        ]

    def __str__(self):
        return f"{self.outcome}/{self.disposition} for {self.attempt_question_id}"

    def save(self, *args, **kwargs):
        _reject_persisted_mutation(self, 'AttemptQuestionEvaluation')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("AttemptQuestionEvaluation records are immutable and cannot be deleted."))


class ResultOutboxEvent(models.Model):
    """
    Transactional outbox row written atomically with a result revision.
    Phase 2E.2 creates rows only; no dispatcher or worker is implemented here.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type = models.CharField(_('event type'), max_length=40)
    attempt_id = models.UUIDField(_('attempt id'), db_index=True)
    result_revision = models.ForeignKey(
        AttemptResultRevision,
        on_delete=models.PROTECT,
        related_name='outbox_events',
        verbose_name=_('result revision'),
    )
    dedupe_key = models.CharField(_('dedupe key'), max_length=128, unique=True)
    payload = models.JSONField(_('payload'), default=dict, blank=True)
    state = models.CharField(
        _('state'), max_length=20, choices=OUTBOX_STATE_CHOICES, default='PENDING', db_index=True,
    )
    available_at = models.DateTimeField(_('available at'), default=timezone.now)
    attempt_count = models.PositiveIntegerField(_('attempt count'), default=0)
    last_error = models.CharField(_('last error'), max_length=500, blank=True, default='')
    lease_owner = models.CharField(_('lease owner'), max_length=64, blank=True, default='')
    lease_until = models.DateTimeField(_('lease until'), null=True, blank=True)
    processed_at = models.DateTimeField(_('processed at'), null=True, blank=True)
    dead_reason = models.CharField(_('dead reason'), max_length=60, blank=True, default='')
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)

    class Meta:
        db_table = 'assessments_result_outbox_event'
        verbose_name = _('result outbox event')
        verbose_name_plural = _('result outbox events')
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(state='CLAIMED', lease_owner__gt='', lease_until__isnull=False)
                    | Q(state='PENDING', lease_owner='')
                    | Q(state='PROCESSED', lease_owner='', processed_at__isnull=False)
                    | Q(state='DEAD', lease_owner='')
                ),
                name='chk_assessments_outbox_state_fields',
            ),
            models.CheckConstraint(
                condition=~Q(state='DEAD') | ~Q(dead_reason=''),
                name='chk_assessments_outbox_dead_reason',
            ),
        ]
        indexes = [
            models.Index(fields=['state', 'available_at']),
            models.Index(fields=['processed_at', 'available_at']),
        ]

    def __str__(self):
        return f"Outbox[{self.event_type}] {self.state} rev={self.result_revision_id}"

