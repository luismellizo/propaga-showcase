# =============================================================================
# PROPAGA - Tests de Despliegue
# =============================================================================
# Estos tests verifican que la configuración de Docker y el proyecto
# están correctos antes de hacer deploy a producción.
# 
# Ejecutar con: python manage.py test tests.deploy --verbosity=2
# =============================================================================

import os
import subprocess
from pathlib import Path
from django.test import TestCase, SimpleTestCase, override_settings
from django.urls import reverse
from django.conf import settings


class DockerConfigurationTests(SimpleTestCase):
    """Tests para verificar que los archivos Docker existen y son válidos."""
    
    def setUp(self):
        self.base_dir = Path(settings.BASE_DIR)
    
    def test_dockerfile_exists(self):
        """Verificar que Dockerfile existe."""
        dockerfile = self.base_dir / 'Dockerfile'
        self.assertTrue(
            dockerfile.exists(),
            "Dockerfile no encontrado. Es necesario para el despliegue."
        )
    
    def test_docker_compose_exists(self):
        """Verificar que docker-compose.yml existe."""
        docker_compose = self.base_dir / 'docker-compose.yml'
        self.assertTrue(
            docker_compose.exists(),
            "docker-compose.yml no encontrado. Es necesario para la orquestación."
        )
    
    def test_entrypoint_exists(self):
        """Verificar que el script de entrypoint existe."""
        entrypoint = self.base_dir / 'scripts' / 'entrypoint.sh'
        self.assertTrue(
            entrypoint.exists(),
            "scripts/entrypoint.sh no encontrado. Es necesario para iniciar contenedores."
        )
    
    def test_entrypoint_is_executable(self):
        """Verificar que entrypoint.sh tiene permisos de ejecución."""
        entrypoint = self.base_dir / 'scripts' / 'entrypoint.sh'
        if entrypoint.exists():
            # Verificar permisos en Unix
            is_executable = os.access(entrypoint, os.X_OK)
            self.assertTrue(
                is_executable,
                "scripts/entrypoint.sh no tiene permisos de ejecución. "
                "Ejecuta: chmod +x scripts/entrypoint.sh"
            )
    
    def test_env_example_exists(self):
        """Verificar que .env.example existe como template."""
        env_example = self.base_dir / '.env.example'
        self.assertTrue(
            env_example.exists(),
            ".env.example no encontrado. Es necesario como template de configuración."
        )
    
    def test_dockerfile_has_required_stages(self):
        """Verificar que Dockerfile tiene las etapas requeridas."""
        dockerfile = self.base_dir / 'Dockerfile'
        if dockerfile.exists():
            content = dockerfile.read_text()
            self.assertIn(
                'FROM python:3.11',
                content,
                "Dockerfile debe usar Python 3.11 como base"
            )
            self.assertIn(
                'HEALTHCHECK',
                content,
                "Dockerfile debe incluir HEALTHCHECK para monitoreo"
            )


class GitHubActionsTests(SimpleTestCase):
    """Tests para verificar la configuración de GitHub Actions.

    En el repo privado estos tests apuntan al workflow de despliegue
    (build → GHCR → webhook de Coolify). Este snapshot público solo tiene el
    workflow de verificación, así que verifican ese.
    """

    def setUp(self):
        self.base_dir = Path(settings.BASE_DIR)
        self.workflow = self.base_dir / '.github' / 'workflows' / 'ci.yml'

    def test_ci_workflow_exists(self):
        """Verificar que el workflow de CI existe."""
        self.assertTrue(
            self.workflow.exists(),
            ".github/workflows/ci.yml no encontrado. Es necesario para CI."
        )

    def test_workflow_runs_verification_steps(self):
        """El CI tiene que correr los tres pasos de verificación, no solo los tests.

        La guardia de deriva de migraciones es la que más veces ha atajado un
        problema: un modelo cambiado sin su migración pasa todos los tests en
        local (la base ya está migrada a mano) y revienta en el arranque del
        contenedor, cuando ya es tarde.
        """
        content = self.workflow.read_text()
        self.assertIn('manage.py check', content, "Falta el system check de Django")
        self.assertIn('makemigrations --check', content, "Falta la guardia de deriva de migraciones")
        self.assertIn('manage.py test', content, "Falta la ejecución de los tests")


class HealthCheckTests(TestCase):
    """Tests para verificar el endpoint de health check."""
    
    def test_health_endpoint_exists(self):
        """Verificar que /health/ existe."""
        response = self.client.get('/health/')
        self.assertEqual(
            response.status_code,
            200,
            "El endpoint /health/ debe responder con 200 OK"
        )
    
    def test_health_endpoint_returns_json(self):
        """Verificar que /health/ devuelve JSON válido."""
        response = self.client.get('/health/')
        self.assertEqual(response['content-type'], 'application/json')
        
        data = response.json()
        self.assertIn('status', data)
        self.assertEqual(data['status'], 'healthy')


class SettingsProductionTests(SimpleTestCase):
    """Tests para verificar que la configuración de producción es segura."""
    
    def test_debug_can_be_disabled(self):
        """Verificar que DEBUG puede ser False."""
        # Este test verifica que el setting puede ser False
        # En CI debe ser True, pero debe poder ser False
        self.assertIsInstance(settings.DEBUG, bool)
    
    def test_secret_key_is_configured(self):
        """Verificar que SECRET_KEY está configurado."""
        self.assertIsNotNone(settings.SECRET_KEY)
        self.assertNotEqual(settings.SECRET_KEY, '')
        # No debe ser el valor por defecto de Django
        self.assertNotIn('django-insecure', settings.SECRET_KEY)
    
    def test_allowed_hosts_sin_comodin(self):
        """ALLOWED_HOSTS nunca puede traer '*'.

        El comodín deja pasar cualquier cabecera Host, que es el vector de los
        ataques de Host header poisoning. Los dominios reales entran por la
        variable de entorno ALLOWED_HOSTS, no hardcodeados en el código.
        """
        self.assertNotIn('*', settings.ALLOWED_HOSTS)

    def test_origenes_csrf_sin_tls_solo_locales(self):
        """Un origen CSRF sin TLS solo se tolera si apunta a la máquina local.

        Los orígenes en `http://` existen para el runserver de desarrollo. Uno
        que apunte a un host remoto significaría confiar en tráfico que puede
        ser interceptado, y ahí el token de CSRF deja de proteger nada.

        Nota: este test no puede mirar `settings.DEBUG` para decidir. El runner
        de Django fuerza DEBUG=False al preparar el entorno de pruebas, pero
        las listas ya se construyeron al importar el módulo de settings, con el
        DEBUG real. El invariante de abajo se sostiene en ambos modos.
        """
        locales = ('http://localhost', 'http://127.0.0.1', 'http://[::1]')
        for origin in settings.CSRF_TRUSTED_ORIGINS:
            if origin.startswith('https://'):
                continue
            self.assertTrue(
                origin.startswith(locales),
                f"Origen CSRF sin TLS apuntando fuera de la máquina local: {origin}",
            )
    
    def test_database_is_postgresql(self):
        """Verificar que la base de datos es PostgreSQL."""
        self.assertIn(
            'postgresql',
            settings.DATABASES['default']['ENGINE'],
            "La base de datos debe ser PostgreSQL para producción"
        )
    
    def test_celery_broker_url_is_configured(self):
        """Verificar que Celery broker está configurado."""
        self.assertIsNotNone(settings.CELERY_BROKER_URL)
        self.assertIn('redis://', settings.CELERY_BROKER_URL)


class StaticFilesTests(SimpleTestCase):
    """Tests para verificar la configuración de archivos estáticos."""
    
    def test_static_url_is_set(self):
        """Verificar que STATIC_URL está configurado."""
        self.assertIsNotNone(settings.STATIC_URL)
    
    def test_static_root_is_set(self):
        """Verificar que STATIC_ROOT está configurado para collectstatic."""
        self.assertIsNotNone(settings.STATIC_ROOT)
    
    def test_media_root_is_set(self):
        """Verificar que MEDIA_ROOT está configurado."""
        self.assertIsNotNone(settings.MEDIA_ROOT)


class RequiredFilesTests(SimpleTestCase):
    """Tests para verificar que archivos críticos no están en .gitignore."""
    
    def setUp(self):
        self.base_dir = Path(settings.BASE_DIR)
    
    def test_requirements_exists(self):
        """Verificar que requirements.txt existe."""
        requirements = self.base_dir / 'requirements.txt'
        self.assertTrue(
            requirements.exists(),
            "requirements.txt no encontrado"
        )
    
    def test_manage_py_exists(self):
        """Verificar que manage.py existe."""
        manage = self.base_dir / 'manage.py'
        self.assertTrue(manage.exists(), "manage.py no encontrado")
    
    def test_config_package_exists(self):
        """Verificar que el paquete config existe."""
        config = self.base_dir / 'config' / '__init__.py'
        self.assertTrue(config.exists(), "config/__init__.py no encontrado")
    
    def test_wsgi_exists(self):
        """Verificar que wsgi.py existe."""
        wsgi = self.base_dir / 'config' / 'wsgi.py'
        self.assertTrue(wsgi.exists(), "config/wsgi.py no encontrado")


class DockerBuildTest(SimpleTestCase):
    """Test para verificar que Docker puede construir la imagen (opcional)."""
    
    def test_dockerfile_syntax_valid(self):
        """
        Verificar sintaxis básica del Dockerfile.
        Este test NO construye la imagen (sería muy lento),
        solo valida la estructura básica.
        """
        dockerfile = Path(settings.BASE_DIR) / 'Dockerfile'
        if not dockerfile.exists():
            self.skipTest("Dockerfile no existe")
        
        content = dockerfile.read_text()
        lines = content.split('\n')
        
        # Debe tener al menos un FROM
        from_count = sum(1 for line in lines if line.strip().startswith('FROM'))
        self.assertGreaterEqual(
            from_count, 1,
            "Dockerfile debe tener al menos una instrucción FROM"
        )
        
        # Debe tener WORKDIR
        self.assertIn('WORKDIR', content, "Dockerfile debe definir WORKDIR")
        
        # Debe tener EXPOSE
        self.assertIn('EXPOSE', content, "Dockerfile debe exponer un puerto")
        
        # Debe tener CMD o ENTRYPOINT
        has_cmd = 'CMD' in content
        has_entrypoint = 'ENTRYPOINT' in content
        self.assertTrue(
            has_cmd or has_entrypoint,
            "Dockerfile debe tener CMD o ENTRYPOINT"
        )
