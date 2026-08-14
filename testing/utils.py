"""
Utilidades de la suite independiente.

Estos tests corren como scripts sueltos contra una base de datos real, no bajo
`manage.py test`. La razón: verifican el pipeline completo contra la
configuración que efectivamente tiene el entorno (SocialApps cargadas, permisos
de escritura en MEDIA_ROOT, Redis vivo), cosas que un test con base de datos
efímera no puede afirmar. Los tests de dominio con base de datos aislada viven
en `apps/` y `tests/`.
"""
import os
import sys
import unittest

import django
from django.conf import settings


def setup_django():
    """Configura el entorno de Django para scripts independientes."""
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    try:
        django.setup()
        if 'testserver' not in settings.ALLOWED_HOSTS:
            settings.ALLOWED_HOSTS.append('testserver')
        print("✅ Django setup completed successfully.")
    except Exception as e:
        print(f"❌ Error setting up Django: {e}")
        sys.exit(1)


def print_result(test_name, success, message=""):
    """Imprime el resultado de un test con formato."""
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"[{status}] {test_name}")
    if message:
        print(f"   Note: {message}")
    print("-" * 50)


def run_suite(*test_cases):
    """Corre las TestCase dadas y termina el proceso con el código correcto.

    Sin esto los scripts salían con 0 aunque hubiera fallos, y `run_all.py`
    —que decide por el returncode— reportaba verde una suite rota. Un test que
    no puede fallar no es un test.
    """
    loader = unittest.TestLoader()
    suite = unittest.TestSuite(
        loader.loadTestsFromTestCase(case) for case in test_cases
    )
    resultado = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if resultado.wasSuccessful() else 1)
