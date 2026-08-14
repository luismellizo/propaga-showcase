"""
Autenticación: creación de usuario, login y protección del dashboard.

El caso que importa es el tercero. `/dashboard/` es la vista con todo el
contenido del usuario; que responda 302 a un anónimo no es un detalle de UX, es
la única barrera entre una publicación y quien no debería verla.
"""
from utils import setup_django, run_suite
setup_django()

import unittest

from django.contrib.auth import get_user_model
from django.test import Client

User = get_user_model()

EMAIL = "testuser@example.com"
PASSWORD = "securepassword123"


class TestAuth(unittest.TestCase):
    def setUp(self):
        User.objects.filter(email=EMAIL).delete()
        self.user = User.objects.create_user(
            username="testuser", email=EMAIL, password=PASSWORD
        )
        self.client = Client()

    def tearDown(self):
        self.user.delete()

    def test_user_creation(self):
        db_user = User.objects.get(email=EMAIL)
        self.assertEqual(db_user.username, "testuser")
        self.assertTrue(db_user.check_password(PASSWORD))
        self.assertFalse(
            db_user.has_usable_password() and db_user.password == PASSWORD,
            "La contraseña no puede quedar guardada en claro",
        )

    def test_login(self):
        self.assertTrue(
            self.client.login(username="testuser", password=PASSWORD),
            "El login con credenciales válidas debe funcionar",
        )

    def test_dashboard_requiere_sesion(self):
        """Un anónimo no puede ver el dashboard: lo mandan al login."""
        response = self.client.get('/dashboard/')
        self.assertEqual(
            response.status_code, 302,
            f"El dashboard respondió {response.status_code} a un anónimo",
        )
        self.assertIn('/accounts/login/', response.url)

    def test_dashboard_accesible_con_sesion(self):
        self.client.login(username="testuser", password=PASSWORD)
        response = self.client.get('/dashboard/')
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    run_suite(TestAuth)
