# Adaptador de allauth para el flujo de conexion de cuentas sociales.
import logging
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

logger = logging.getLogger(__name__)

class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        # Si el usuario ya está logueado en nuestra plataforma...
        if request.user.is_authenticated:
            # Se registra el pk, no el email: los logs de aplicación se envían a
            # agregadores, se respaldan y los lee gente que no necesita saber la
            # dirección de nadie. El pk identifica igual de bien para depurar.
            logger.info(
                f"Usuario pk={request.user.pk} ya autenticado. Conectando cuenta social "
                f"'{sociallogin.account.provider}'."
            )
            # ...detenemos cualquier intento de crear un usuario nuevo y
            # simplemente enlazamos la cuenta social a su perfil existente.
            sociallogin.connect(request, request.user)
        else:
            logger.info(f"Nuevo login social para el proveedor '{sociallogin.account.provider}'. Dejando que allauth maneje el flujo estándar.")
