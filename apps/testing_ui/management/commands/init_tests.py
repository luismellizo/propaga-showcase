from django.core.management.base import BaseCommand
from apps.testing_ui.models import TestResult

class Command(BaseCommand):
    """Siembra el catálogo de tests que el panel del admin puede ejecutar.

    Esta lista es la fuente de verdad de `script_path`: el campo es de solo
    lectura en el admin justamente para que nadie lo escriba por web. Ver
    `apps/testing_ui/admin.py`.
    """

    help = 'Inicializa los tests disponibles en el sistema'

    # Atributo de clase para que los tests puedan verificar que cada ruta
    # sembrada pasa la validación de `_ruta_permitida`.
    TESTS = [
            {
                'name': '1. Authentication Flow',
                'script_path': 'testing/test_01_auth.py',
                'description': 'Verifica creación de usuario, login y acceso a vistas protegidas.'
            },
            {
                'name': '2. Video Processing Pipeline',
                'script_path': 'testing/test_02_video_processing.py',
                'description': 'Prueba simulación de descarga, whisper, generación IA y transcodificación ffmpeg (Mocked).'
            },
            {
                'name': '3. Social Propagation',
                'script_path': 'testing/test_03_social_propagation.py',
                'description': 'Prueba integración con APIs de Facebook, YouTube y Twitter (Mocked).'
            },
            {
                'name': '4. Downloads (yt-dlp)',
                'script_path': 'testing/test_04_downloads.py',
                'description': 'Verifica capacidad de yt-dlp para extraer info de videos reales.'
            },
            {
                'name': '5. Infrastructure Health',
                'script_path': 'testing/test_05_infrastructure.py',
                'description': 'Verifica conectividad DB, Redis, Permisos de Sistema y Configuración Social.'
            },
            {
                'name': '>>> RUN ALL TESTS <<<',
                'script_path': 'testing/run_all.py',
                'description': 'Ejecuta la suite completa secuencialmente.'
            }
    ]

    def handle(self, *args, **options):
        for t in self.TESTS:
            obj, created = TestResult.objects.get_or_create(
                script_path=t['script_path'],
                name=t['name'],
                defaults={
                    'description': t['description']
                }
            )
            # Update if exists
            obj.script_path = t['script_path']
            obj.description = t['description']
            obj.save()
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created test: {t["name"]}'))
            else:
                self.stdout.write(self.style.SUCCESS(f'Updated test: {t["name"]}'))
