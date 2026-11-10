from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AssessmentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.assessments'
    label = 'assessments'
    verbose_name = _('Assessments & Execution Engine')

    def ready(self) -> None:
        from .services.concurrency import _enable_shared_locks
        _enable_shared_locks()

