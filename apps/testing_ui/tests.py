"""
El panel de tests ejecuta procesos en el servidor. Estos tests cuidan la única
puerta por la que pasa una ruta antes de llegar a un intérprete.
"""
import os

from django.test import SimpleTestCase

from .admin import DIRECTORIO_TESTS, RAIZ_PROYECTO, _ruta_permitida


class RutaPermitidaTests(SimpleTestCase):
    def test_acepta_script_dentro_de_testing(self):
        ruta = _ruta_permitida('testing/test_01_auth.py')
        self.assertIsNotNone(ruta)
        self.assertTrue(ruta.startswith(os.path.realpath(DIRECTORIO_TESTS) + os.sep))

    def test_rechaza_traversal(self):
        """`..` tiene que morir DESPUÉS de resolver, no antes.

        Comparar la cadena cruda con un startswith deja pasar esto: el prefijo
        'testing/' está ahí, y aun así la ruta final apunta fuera del proyecto.
        """
        for intento in (
            'testing/../config/settings.py',
            'testing/../../../../etc/passwd.py',
            '../evil.py',
        ):
            with self.subTest(intento=intento):
                self.assertIsNone(_ruta_permitida(intento))

    def test_rechaza_ruta_absoluta(self):
        self.assertIsNone(_ruta_permitida('/tmp/evil.py'))

    def test_rechaza_directorio_hermano_con_mismo_prefijo(self):
        """`testing_malicioso/` no puede colar por comparación de prefijo."""
        self.assertIsNone(_ruta_permitida('testing_malicioso/x.py'))

    def test_rechaza_extensiones_que_no_son_py(self):
        for intento in ('testing/utils.pyc', 'testing/run.sh', 'testing/x'):
            with self.subTest(intento=intento):
                self.assertIsNone(_ruta_permitida(intento))

    def test_rechaza_vacio(self):
        self.assertIsNone(_ruta_permitida(''))
        self.assertIsNone(_ruta_permitida(None))

    def test_rechaza_archivo_inexistente_dentro_de_testing(self):
        self.assertIsNone(_ruta_permitida('testing/no_existe_este_test.py'))

    def test_todos_los_scripts_sembrados_son_validos(self):
        """Lo que siembra `init_tests` tiene que pasar la barrera.

        Si un día alguien mueve `testing/`, este test falla antes que el panel.
        """
        from .management.commands.init_tests import Command

        sembrados = [t['script_path'] for t in getattr(Command, 'TESTS', [])]
        if not sembrados:
            self.skipTest("init_tests no expone la lista como atributo de clase")
        for script in sembrados:
            with self.subTest(script=script):
                self.assertIsNotNone(_ruta_permitida(script))
