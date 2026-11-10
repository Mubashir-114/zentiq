from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ArenaConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.arena'
    label = 'arena'
    verbose_name = _('Arena & Question Bank')

