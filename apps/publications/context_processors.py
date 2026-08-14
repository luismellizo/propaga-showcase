"""
Context processors globales del sitio.
"""
from django.conf import settings


def site_meta(request):
    """
    Expone metadatos del sitio a todas las plantillas.

    `GOOGLE_SITE_VERIFICATION`: token de Google Search Console. Se renderiza como
    <meta name="google-site-verification"> en base.html para poder verificar la
    propiedad del dominio (requisito de la verificación de marca de Google OAuth).
    Vacío = no se renderiza nada.
    """
    return {
        'GOOGLE_SITE_VERIFICATION': settings.GOOGLE_SITE_VERIFICATION,
    }
