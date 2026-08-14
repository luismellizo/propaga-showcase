# Persistencia del token OAuth al conectar o reconectar una cuenta social.

import logging
from django.dispatch import receiver
from allauth.socialaccount.models import SocialLogin, SocialToken
from allauth.socialaccount.signals import social_account_added, social_account_updated

logger = logging.getLogger(__name__)

# Escuchamos ambas señales, 'added' y 'updated', para máxima cobertura.
@receiver([social_account_added, social_account_updated])
def update_or_create_social_token(request, sociallogin: SocialLogin, **kwargs):
    """
    Esta función se activa cuando una cuenta social es añadida o actualizada.
    Su misión es asegurar que el token se guarde o se actualice en la base de datos
    sin crear duplicados, usando el método "update_or_create".
    """
    # El UID es el identificador de la persona EN la red social. No va al log:
    # el pk local identifica igual para depurar y no exporta a nadie.
    logger.info(
        f"Señal recibida para la cuenta {sociallogin.account.provider} "
        f"(pk={sociallogin.account.pk})"
    )
    
    if sociallogin.token:
        # Usamos update_or_create para evitar errores de duplicados.
        # Busca un token para esta cuenta...
        token, created = SocialToken.objects.update_or_create(
            account=sociallogin.account,
            # ...y si lo encuentra, lo actualiza con estos valores. Si no, lo crea.
            defaults={
                'token': sociallogin.token.token,
                'token_secret': sociallogin.token.token_secret,
                'expires_at': sociallogin.token.expires_at
            }
        )

        if created:
            logger.info(f"¡Nuevo token para {sociallogin.account.provider} creado y guardado exitosamente!")
        else:
            logger.info(f"Token existente para {sociallogin.account.provider} actualizado exitosamente.")
        
        if token.token_secret:
            logger.info("¡Confirmado! El refresh_token (token_secret) fue encontrado y almacenado.")
        else:
            logger.warning("Advertencia: No se encontró un refresh_token (token_secret) en esta conexión.")
