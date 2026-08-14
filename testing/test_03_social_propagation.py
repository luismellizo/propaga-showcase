"""
Orquestación de la propagación.

Las implementaciones por red están omitidas en este snapshot (ver
`apps/publications/publishers.py`), pero lo que estos tests verifican nunca
estuvo en ellas: cómo `propagate_publication` reparte el trabajo, qué hace
cuando una red falla y qué le queda al usuario en pantalla.

Esa separación es justamente el argumento del módulo `publishers`: la lógica
que decide el destino de una publicación se puede probar sin tocar una API.

Las cuentas y los tokens son filas reales de allauth, no mocks: el único doble
es el publicador, que es la frontera con el mundo exterior.
"""
from utils import setup_django, run_suite
setup_django()

import os
import unittest
from unittest.mock import MagicMock, patch

from allauth.socialaccount.models import SocialAccount, SocialToken, SocialApp
from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site

from apps.publications.models import Publication
from apps.publications.tasks import propagate_publication

User = get_user_model()


class TestPropagacion(unittest.TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="socialtester", email="socialtester@example.com", password="password"
        )
        self.publication = Publication.objects.create(
            user=self.user,
            title="Título de prueba",
            description="Descripción de prueba",
            hashtags="#uno #dos",
            status='PUBLISHING',
        )
        # El archivo tiene que existir: la tarea lo borra en su `finally`.
        self.video_path = f'/tmp/final_video_{self.publication.id}.mp4'
        with open(self.video_path, 'wb') as fh:
            fh.write(b'\x00' * 128)

        self._creados = []

    def tearDown(self):
        for obj in self._creados:
            obj.delete()
        self.publication.delete()
        self.user.delete()
        if os.path.exists(self.video_path):
            os.remove(self.video_path)

    def _conectar(self, provider, con_token=True):
        """Crea una SocialAccount real del usuario y la marca como destino."""
        cuenta = SocialAccount.objects.create(
            user=self.user, provider=provider, uid=f'uid-{provider}-{self.user.pk}'
        )
        self._creados.append(cuenta)

        if con_token:
            app, creada = SocialApp.objects.get_or_create(
                provider=provider,
                defaults={'name': provider, 'client_id': 'test-id', 'secret': 'test-secret'},
            )
            if creada:
                app.sites.add(Site.objects.get_current())
                self._creados.append(app)
            token = SocialToken.objects.create(app=app, account=cuenta, token='test-token')
            self._creados.append(token)

        self.publication.target_accounts.add(cuenta)
        return cuenta

    def _propagar(self, publicadores):
        with patch('apps.publications.tasks.PUBLICADORES', publicadores):
            propagate_publication(self.publication.id)
        self.publication.refresh_from_db()
        return self.publication

    # ------------------------------------------------------------------ tests

    def test_publica_en_todas_las_redes_seleccionadas(self):
        yt, fb = MagicMock(), MagicMock()
        self._conectar('google')
        self._conectar('facebook')

        pub = self._propagar({'google': ('YouTube', yt), 'facebook': ('Facebook', fb)})

        yt.assert_called_once()
        fb.assert_called_once()
        self.assertEqual(pub.status, 'PUBLISHED')
        self.assertEqual(pub.error_message, '')

    def test_exito_parcial_publica_y_reporta(self):
        """Si una red falla y otra no: PUBLISHED, pero el fallo tiene que verse.

        Es el caso que más importa. Marcar éxito y dejar el error solo en los
        logs del worker hacía que el usuario creyera que había publicado en dos
        redes cuando había sido una.
        """
        yt = MagicMock()
        x = MagicMock(side_effect=RuntimeError("client-not-enrolled"))
        self._conectar('google')
        self._conectar('twitter')

        pub = self._propagar({'google': ('YouTube', yt), 'twitter': ('X (Twitter)', x)})

        yt.assert_called_once()
        self.assertEqual(pub.status, 'PUBLISHED')
        self.assertIn('X (Twitter)', pub.error_message)
        self.assertIn('client-not-enrolled', pub.error_message)

    def test_si_fallan_todas_el_estado_es_failed(self):
        yt = MagicMock(side_effect=RuntimeError("cuota excedida"))
        self._conectar('google')

        pub = self._propagar({'google': ('YouTube', yt)})

        self.assertEqual(pub.status, 'FAILED')
        self.assertIn('cuota excedida', pub.error_message)

    def test_cuenta_sin_token_no_intenta_publicar(self):
        """Sin SocialToken no se llama al publicador: se reporta y se sigue."""
        yt = MagicMock()
        self._conectar('google', con_token=False)

        pub = self._propagar({'google': ('YouTube', yt)})

        yt.assert_not_called()
        self.assertEqual(pub.status, 'FAILED')
        self.assertIn('reconéctala', pub.error_message)

    def test_proveedor_desconocido_se_omite_sin_reventar(self):
        """Una cuenta de un proveedor sin publicador no puede tumbar la tarea."""
        yt = MagicMock()
        self._conectar('linkedin')
        self._conectar('google')

        pub = self._propagar({'google': ('YouTube', yt)})

        yt.assert_called_once()
        self.assertEqual(pub.status, 'PUBLISHED')

    def test_sin_destinos_falla_temprano(self):
        pub = self._propagar({'google': ('YouTube', MagicMock())})

        self.assertEqual(pub.status, 'FAILED')
        self.assertIn('destino', pub.error_message)

    def test_limpia_el_video_temporal(self):
        """El archivo de /tmp se borra pase lo que pase: está en el `finally`."""
        self._conectar('google')

        self._propagar({'google': ('YouTube', MagicMock())})

        self.assertFalse(
            os.path.exists(self.video_path),
            "El video temporal quedó en disco tras la propagación",
        )

    def test_el_publicador_recibe_el_contrato_acordado(self):
        """(publication, account, social_token, video_path), en ese orden."""
        yt = MagicMock()
        cuenta = self._conectar('google')

        self._propagar({'google': ('YouTube', yt)})

        args, _ = yt.call_args
        self.assertEqual(args[0].pk, self.publication.pk)
        self.assertEqual(args[1].pk, cuenta.pk)
        self.assertEqual(args[2].token, 'test-token')
        self.assertEqual(args[3], self.video_path)


if __name__ == "__main__":
    run_suite(TestPropagacion)
