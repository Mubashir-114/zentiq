"""
Serializers for ZENTIQ Accounts and Authentication.
Handles registration, login validation, session state representation, and user profile management.
"""
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import RegexValidator
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from rest_framework import exceptions, serializers
from .models import UserProfile

User = get_user_model()

username_validator = RegexValidator(
    regex=r'^[a-zA-Z0-9_]{3,30}$',
    message=_('Username must be 3-30 characters and contain only letters, numbers, and underscores.'),
)

DEFAULT_PREFERENCES = {
    'theme': 'dark',
    'email_notifications': True,
    'sound_effects': True,
}


ALLOWED_PREFERENCE_KEYS = {'theme', 'sound_effects', 'email_notifications'}


class UserSerializer(serializers.ModelSerializer):
    """Serializes core User identity fields."""

    class Meta:
        model = User
        fields = ['id', 'email', 'date_joined']
        read_only_fields = fields


class UserProfileSerializer(serializers.ModelSerializer):
    """Serializes public profile and preferences."""
    username = serializers.CharField(read_only=True)

    class Meta:
        model = UserProfile
        fields = [
            'username',
            'display_name',
            'avatar_key',
            'bio',
            'preferences',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['username', 'created_at', 'updated_at']

    def validate_avatar_key(self, value):
        allowed = dict(UserProfile.AVATAR_CHOICES).keys()
        if value not in allowed:
            raise serializers.ValidationError(
                _("Invalid avatar key. Allowed options: %(choices)s") % {'choices': ', '.join(allowed)}
            )
        return value

    def validate_preferences(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError(_('Preferences must be a key-value object.'))

        unsupported_keys = set(value.keys()) - ALLOWED_PREFERENCE_KEYS
        if unsupported_keys:
            raise serializers.ValidationError(
                _('Unsupported preference key(s): %(keys)s. Supported keys are: %(allowed)s.') % {
                    'keys': ', '.join(sorted(unsupported_keys)),
                    'allowed': ', '.join(sorted(ALLOWED_PREFERENCE_KEYS)),
                }
            )

        if 'theme' in value:
            if not isinstance(value['theme'], str) or value['theme'] not in ('dark', 'light'):
                raise serializers.ValidationError(_('theme must be either "dark" or "light".'))

        if 'sound_effects' in value:
            if not isinstance(value['sound_effects'], bool):
                raise serializers.ValidationError(_('sound_effects must be a boolean.'))

        if 'email_notifications' in value:
            if not isinstance(value['email_notifications'], bool):
                raise serializers.ValidationError(_('email_notifications must be a boolean.'))

        return value

    def update(self, instance, validated_data):
        # Shallow merge preferences rather than replacing entirely
        if 'preferences' in validated_data and isinstance(validated_data['preferences'], dict):
            current_prefs = instance.preferences or {}
            merged_prefs = {**current_prefs, **validated_data['preferences']}
            validated_data['preferences'] = merged_prefs

        return super().update(instance, validated_data)



class UserWithProfileSerializer(serializers.Serializer):
    """Returns combined user and profile payload for authenticated sessions."""
    user = UserSerializer(source='*')
    profile = UserProfileSerializer()


class RegisterSerializer(serializers.Serializer):
    """Validates user registration, creates User and UserProfile atomically."""
    email = serializers.EmailField(max_length=255)
    username = serializers.CharField(
        max_length=30,
        min_length=3,
        validators=[username_validator],
    )
    password = serializers.CharField(
        write_only=True,
        style={'input_type': 'password'},
    )

    def validate_email(self, value):
        normalized = value.strip().lower()
        if User.objects.filter(email__iexact=normalized).exists():
            raise serializers.ValidationError(_('A user with that email already exists.'))
        return normalized

    def validate_username(self, value):
        normalized = value.strip().lower()
        if UserProfile.objects.filter(username__iexact=normalized).exists():
            raise serializers.ValidationError(_('This username is already taken.'))
        return normalized

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def create(self, validated_data):
        email = validated_data['email']
        username = validated_data['username']
        password = validated_data['password']

        with transaction.atomic():
            user = User.objects.create_user(email=email, password=password)
            UserProfile.objects.create(
                user=user,
                username=username,
                display_name=username,
                preferences=DEFAULT_PREFERENCES.copy(),
            )

        return user


class LoginSerializer(serializers.Serializer):
    """Validates login credentials and returns authenticated user."""
    email = serializers.EmailField(max_length=255)
    password = serializers.CharField(
        write_only=True,
        style={'input_type': 'password'},
    )

    def validate(self, attrs):
        email = attrs.get('email', '').strip().lower()
        password = attrs.get('password')

        if not email or not password:
            raise exceptions.AuthenticationFailed(
                _('Both email and password are required.'),
                code='invalid_credentials',
            )

        request = self.context.get('request')
        user = authenticate(request=request, email=email, password=password, username=email)

        if not user:
            # Check if user exists and password is correct, but account is deactivated
            inactive_user = User.objects.filter(email__iexact=email).first()
            if inactive_user and inactive_user.check_password(password) and not inactive_user.is_active:
                raise exceptions.PermissionDenied(
                    _('This account is inactive. Please contact support.'),
                    code='account_inactive',
                )
            raise exceptions.AuthenticationFailed(
                _('Invalid email or password.'),
                code='invalid_credentials',
            )

        if not user.is_active:
            raise exceptions.PermissionDenied(
                _('This account is inactive. Please contact support.'),
                code='account_inactive',
            )

        attrs['user'] = user
        return attrs
