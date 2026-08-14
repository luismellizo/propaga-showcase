"""
Pipeline de procesamiento: `process_publication`, con todo lo externo mockeado.

Lo que se verifica es el CONTRATO de la tarea, no que Groq o Gemini estén en
línea: que el texto generado se persista, y —sobre todo— que la publicación
termine en `AWAITING_APPROVAL` y no en `PUBLISHED`. Esa distinción es la
frontera entre las dos tareas del sistema: `process_publication` deja el video
listo, publicar es una decisión del usuario que dispara `propagate_publication`.
"""
from utils import setup_django, run_suite
setup_django()

import os
import unittest
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.publications.models import Publication
from apps.publications.tasks import process_publication

User = get_user_model()


def _ffmpeg_falso(cmd, *args, **kwargs):
    """Sustituto de `subprocess.run` que se comporta como ffmpeg/ffprobe.

    No basta con devolver `returncode=0`: el pipeline consulta el tamaño del
    audio extraído antes de mandarlo a transcribir, así que el mock tiene que
    dejar el archivo en disco. Un mock que solo dice "salió bien" hace que el
    código falle más adelante por una razón que no tiene nada que ver con lo
    que se está probando.
    """
    binario = os.path.basename(cmd[0])

    if binario == 'ffprobe':
        # stdout vacío → `_es_compatible_redes` devuelve False → camino de re-encode.
        return MagicMock(returncode=0, stdout="", stderr="")

    # ffmpeg: el archivo de salida es el último argumento que no es una bandera.
    salida = next(a for a in reversed(cmd) if not a.startswith('-'))
    os.makedirs(os.path.dirname(salida), exist_ok=True)
    with open(salida, 'wb') as fh:
        fh.write(b'\x00' * 1024)
    return MagicMock(returncode=0, stdout="", stderr="")


class TestVideoProcessing(unittest.TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="videotester", email="videotester@example.com", password="password"
        )
        self.publication = Publication.objects.create(
            user=self.user,
            title="Test Pub",
            video_file=SimpleUploadedFile("test_video.mp4", b"fake video content header"),
            status='PENDING',
        )
        print(f"📝 Created dummy publication ID: {self.publication.id}")

    def tearDown(self):
        try:
            pub = Publication.objects.get(id=self.publication.id)
            if pub.video_file:
                pub.video_file.delete()
            pub.delete()
        except Publication.DoesNotExist:
            pass
        self.user.delete()
        residuo = f'/tmp/final_video_{self.publication.id}.mp4'
        if os.path.exists(residuo):
            os.remove(residuo)

    @patch('apps.publications.tasks.call_gemini_api')
    @patch('apps.publications.tasks.Groq')
    @patch('apps.publications.tasks.subprocess.run')
    @patch('apps.publications.tasks.shutil.copy2')
    def test_process_publication_flow(self, mock_copy, mock_subprocess, mock_groq, mock_gemini):
        print("\n🎬 Testing Process Publication Flow (Mocked)...")

        # El generador devuelve el JSON ya normalizado al formato estilo OpenAI
        # que espera el resto del pipeline.
        mock_gemini.return_value = {
            'choices': [{
                'message': {
                    'content': '{"title": "Viral Video 2024", "description": "Amazing content", "hashtags": "#viral #wow #2024"}'
                }
            }]
        }

        mock_transcription = MagicMock()
        mock_transcription.text = "This is a transcribed text from the video."
        mock_groq_instance = MagicMock()
        mock_groq_instance.audio.transcriptions.create.return_value = mock_transcription
        mock_groq.return_value = mock_groq_instance

        mock_subprocess.side_effect = _ffmpeg_falso
        mock_copy.return_value = True

        # `.apply()` ejecuta la tarea en el proceso actual, sin worker ni broker,
        # respetando el `bind=True` del decorador.
        resultado = process_publication.apply(args=[self.publication.id])
        print(f"Task Result: {resultado.result}")

        pub = Publication.objects.get(id=self.publication.id)
        self.assertEqual(
            pub.status, 'AWAITING_APPROVAL',
            f"La tarea de procesamiento debe dejar la publicación por aprobar, no en {pub.status}. "
            f"Error registrado: {pub.error_message}"
        )
        self.assertEqual(pub.title, "Viral Video 2024")
        self.assertEqual(pub.description, "Amazing content")
        self.assertEqual(pub.hashtags, "#viral #wow #2024")
        self.assertEqual(pub.processing_step, '', "El sub-paso debe quedar limpio al terminar")

    @patch('apps.publications.tasks.call_gemini_api', side_effect=RuntimeError("cuota agotada"))
    @patch('apps.publications.tasks.Groq')
    @patch('apps.publications.tasks.subprocess.run')
    @patch('apps.publications.tasks.shutil.copy2')
    def test_fallback_cuando_la_ia_falla(self, mock_copy, mock_subprocess, mock_groq, mock_gemini):
        """Si el proveedor de IA se cae, la publicación no puede morir en FAILED.

        El usuario ya esperó descarga, extracción y transcripción. Degradar a un
        título recortado de la transcripción es peor contenido, pero es contenido
        editable en pantalla — y eso es infinitamente mejor que un error.
        """
        print("\n🛟 Testing fallback path (IA caída)...")

        mock_transcription = MagicMock()
        mock_transcription.text = "Hoy vamos a hablar de algo que casi nadie sabe sobre el café."
        mock_groq_instance = MagicMock()
        mock_groq_instance.audio.transcriptions.create.return_value = mock_transcription
        mock_groq.return_value = mock_groq_instance

        mock_subprocess.side_effect = _ffmpeg_falso
        mock_copy.return_value = True

        process_publication.apply(args=[self.publication.id])

        pub = Publication.objects.get(id=self.publication.id)
        self.assertEqual(pub.status, 'AWAITING_APPROVAL')
        self.assertTrue(pub.title, "El fallback debe producir algún título")
        self.assertTrue(pub.hashtags, "El fallback debe producir algún hashtag")


if __name__ == "__main__":
    run_suite(TestVideoProcessing)
