import os
from celery import Celery

# Establece el módulo de configuración de Django para el programa 'celery'.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('config')

# Usando un string aquí significa que el worker no necesita serializar
# el objeto de configuración a los procesos hijos.
# namespace='CELERY' significa que todas las claves de configuración de Celery
# deben tener un prefijo `CELERY_`.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Carga automáticamente los módulos de tareas de todas las aplicaciones registradas.
app.autodiscover_tasks()
