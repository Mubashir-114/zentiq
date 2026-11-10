"""
Custom User Model for ZENTIQ.
Replaces Django's default username-based user with an email-based user model.
Designed before initial database migrations.
"""
from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from .managers import UserManager

username_validator = RegexValidator(
    regex=r'^[a-zA-Z0-9_]{3,30}$',
    message=_('Username must be 3-30 characters and contain only letters, numbers, and underscores.'),
)

class User(AbstractBaseUser, PermissionsMixin):
    """
    Primary user entity for ZENTIQ.
    Authenticates via email; separates identity from speculative profile fields.
    """
    email = models.EmailField(
        _('email address'),
        unique=True,
        max_length=255,
        db_index=True,
        error_messages={
            'unique': _('A user with that email already exists.'),
        },
    )
    is_active = models.BooleanField(
        _('active'),
        default=True,
        help_text=_(
            'Designates whether this user should be treated as active. '
            'Unselect this instead of deleting accounts.'
        ),
    )
    is_staff = models.BooleanField(
        _('staff status'),
        default=False,
        help_text=_('Designates whether the user can log into this admin site.'),
    )
    date_joined = models.DateTimeField(_('date joined'), default=timezone.now)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    class Meta:
        db_table = 'accounts_user'
        verbose_name = _('user')
        verbose_name_plural = _('users')
        ordering = ['-date_joined']

    def __str__(self):
        return self.email

    def clean(self):
        super().clean()
        self.email = self.__class__.objects.normalize_email(self.email)


class UserProfile(models.Model):
    """
    Public identity and preferences for a ZENTIQ user.
    Linked 1-to-1 with the core User entity.
    """
    AVATAR_CHOICES = (
        ('default', 'Default Sentinel'),
        ('cyber_ninja', 'Cyber Ninja'),
        ('data_hacker', 'Data Hacker'),
        ('quantum_mage', 'Quantum Mage'),
        ('logic_sentinel', 'Logic Sentinel'),
        ('binary_phantom', 'Binary Phantom'),
    )

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
        verbose_name=_('user'),
    )
    username = models.CharField(
        _('username'),
        max_length=30,
        unique=True,
        db_index=True,
        validators=[username_validator],
        help_text=_('Unique public ZENTIQ handle (3-30 alphanumeric or underscore characters).'),
    )
    display_name = models.CharField(
        _('display name'),
        max_length=50,
        blank=True,
        help_text=_('Friendly public name. Defaults to username if left blank.'),
    )
    avatar_key = models.CharField(
        _('avatar key'),
        max_length=50,
        choices=AVATAR_CHOICES,
        default='default',
        help_text=_('Predefined avatar identifier from the curated ZENTIQ collection.'),
    )
    bio = models.CharField(
        _('bio'),
        max_length=250,
        blank=True,
        help_text=_('Short player biography or focus statement (max 250 characters).'),
    )
    preferences = models.JSONField(
        _('preferences'),
        default=dict,
        blank=True,
        help_text=_('User-configured client preferences (e.g. sound_effects, email_notifications).'),
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        db_table = 'accounts_userprofile'
        verbose_name = _('user profile')
        verbose_name_plural = _('user profiles')

    def __str__(self):
        return f"@{self.username} ({self.user.email})"

    def clean(self):
        super().clean()
        if self.username:
            self.username = self.username.strip().lower()
        if not self.display_name and self.username:
            self.display_name = self.username

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


