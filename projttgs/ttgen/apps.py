from django.apps import AppConfig

class TtgenConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ttgen'

    def ready(self):
        # Register login/logout activity signal receivers.
        from . import activity  # noqa: F401
