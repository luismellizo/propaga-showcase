"""
Descarga: que yt-dlp siga pudiendo resolver un video de YouTube.

Este test SÍ sale a la red, a propósito: yt-dlp es la dependencia más frágil del
sistema — YouTube le cambia el terreno cada tantas semanas y la versión pineada
deja de resolver. Ningún mock avisa de eso.

Por eso mismo no corre por defecto: un test que depende de un tercero no puede
hacer fallar el CI de un cambio que no lo tocó. Se habilita con:

    PROPAGA_NETWORK_TESTS=1 python testing/test_04_downloads.py
"""
from utils import setup_django, run_suite
setup_django()

import os
import unittest

import yt_dlp

# "Me at the zoo": el primer video de YouTube. Público, estable y de 19 segundos.
TEST_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


@unittest.skipUnless(
    os.environ.get('PROPAGA_NETWORK_TESTS') == '1',
    "Test de red desactivado. Habilitar con PROPAGA_NETWORK_TESTS=1.",
)
class TestDownloads(unittest.TestCase):
    def test_ytdlp_extrae_metadatos(self):
        print("⬇️  Testing yt-dlp info fetching...")
        opciones = {'quiet': True, 'no_warnings': True, 'simulate': True}

        with yt_dlp.YoutubeDL(opciones) as ydl:
            info = ydl.extract_info(TEST_URL, download=False)

        self.assertTrue(info.get('title'), "yt-dlp no devolvió título")
        self.assertTrue(info.get('formats'), "yt-dlp no devolvió formatos disponibles")
        print(f"   Título resuelto: {info['title']}")

    def test_hay_formato_compatible_con_redes(self):
        """Debe existir al menos un formato H.264 ≤1080p.

        Es la premisa del selector de formato del pipeline: si no hubiera ninguno,
        cada descarga caería al fallback y habría que re-encodear el video entero
        con libx264 — minutos de CPU por publicación en vez de segundos.
        """
        opciones = {'quiet': True, 'no_warnings': True, 'simulate': True}

        with yt_dlp.YoutubeDL(opciones) as ydl:
            info = ydl.extract_info(TEST_URL, download=False)

        compatibles = [
            f for f in info.get('formats', [])
            if (f.get('vcodec') or '').startswith('avc1') and (f.get('height') or 0) <= 1080
        ]
        self.assertTrue(compatibles, "Ningún formato H.264 ≤1080p disponible")


if __name__ == "__main__":
    run_suite(TestDownloads)
