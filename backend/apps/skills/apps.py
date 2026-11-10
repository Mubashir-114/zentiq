from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class SkillsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.skills'
    label = 'skills'
    verbose_name = _('Skills & Taxonomy')

