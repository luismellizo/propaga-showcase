from django.apps import AppConfig

class TestingUiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.testing_ui'
    verbose_name = 'Testing Center'
