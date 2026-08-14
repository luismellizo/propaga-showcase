# Archivo: apps/publications/apps.py
from django.apps import AppConfig

class PublicationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.publications'

    def ready(self):
        # Esta función se ejecuta cuando Django está listo.
        # Aquí importamos nuestras señales para activarlas.
        import apps.publications.signals
