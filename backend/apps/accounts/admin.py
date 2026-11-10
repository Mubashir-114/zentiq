"""
Django Admin Configuration for Accounts.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from .models import User, UserProfile

class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = _('Profile')
    fk_name = 'user'
    extra = 0

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ['email']
    list_display = ['email', 'get_username', 'is_staff', 'is_active', 'date_joined']
    list_filter = ['is_staff', 'is_active']
    inlines = [UserProfileInline]
    fieldsets = [
        (None, {'fields': ['email', 'password']}),
        (_('Permissions'), {'fields': ['is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions']}),
        (_('Important dates'), {'fields': ['last_login', 'date_joined', 'updated_at']}),
    ]
    readonly_fields = ['date_joined', 'updated_at', 'last_login']
    add_fieldsets = [
        (
            None,
            {
                'classes': ['wide'],
                'fields': ['email', 'password'],
            },
        ),
    ]
    search_fields = ['email', 'profile__username', 'profile__display_name']

    @admin.display(description=_('Username'))
    def get_username(self, obj):
        return getattr(obj, 'profile', None) and obj.profile.username or '-'

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['username', 'user', 'display_name', 'avatar_key', 'created_at']
    search_fields = ['username', 'display_name', 'user__email']
    list_filter = ['avatar_key', 'created_at']
    readonly_fields = ['created_at', 'updated_at']


