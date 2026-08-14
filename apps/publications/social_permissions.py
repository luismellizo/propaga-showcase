"""
Permisos reales de las cuentas sociales conectadas.

Tener una `SocialAccount` NO significa tener permiso para publicar: el login con
Google pide solo `profile`+`email`, y el permiso de subida a YouTube se otorga
aparte (consentimiento incremental desde "Conectar Cuentas"). allauth no guarda
los scopes del token, así que hay que preguntárselos al proveedor.

Sin esto la UI mostraba "Conectada" para una cuenta que no podía publicar, y el
fallo recién aparecía como `403 insufficientPermissions` dentro del worker.
"""
import hashlib
import logging

import requests
from allauth.socialaccount.models import SocialAccount, SocialToken
from django.core.cache import cache

logger = logging.getLogger(__name__)

YOUTUBE_UPLOAD_SCOPE = 'https://www.googleapis.com/auth/youtube.upload'
TOKENINFO_URL = 'https://oauth2.googleapis.com/tokeninfo'

# El scope no cambia salvo que el usuario reconecte, pero tampoco conviene
# servir un estado viejo por mucho tiempo: 10 min es buen punto medio.
CACHE_SEGUNDOS = 600
# Si Google no responde, se reintenta pronto en vez de dar por perdido el permiso.
CACHE_SEGUNDOS_ERROR = 60


def _clave_cache(token):
    """
    El hash del token va en la clave: al reconectar, el token cambia y la consulta
    cae en otra clave, así que no hace falta invalidar nada a mano.
    """
    huella = hashlib.sha256(token.token.encode()).hexdigest()[:16]
    return f'scopes_google:{token.pk}:{huella}'


def scopes_de_google(user, refrescar=False):
    """
    Devuelve el conjunto de scopes del token de Google del usuario.
    Conjunto vacío si no hay cuenta, no hay token o Google no responde.
    """
    account = SocialAccount.objects.filter(user=user, provider='google').first()
    if not account:
        return set()

    token = SocialToken.objects.filter(account=account).first()
    if not token or not token.token:
        return set()

    clave = _clave_cache(token)
    if not refrescar:
        cacheado = cache.get(clave)
        if cacheado is not None:
            return set(cacheado)

    try:
        respuesta = requests.get(TOKENINFO_URL, params={'access_token': token.token}, timeout=5)
        if respuesta.status_code != 200:
            # 400 = token expirado o revocado. Es un "no tiene permiso" legítimo.
            logger.info(f'tokeninfo de Google respondió {respuesta.status_code} para el usuario {user.pk}')
            cache.set(clave, [], CACHE_SEGUNDOS_ERROR)
            return set()
        scopes = set((respuesta.json().get('scope') or '').split())
        cache.set(clave, list(scopes), CACHE_SEGUNDOS)
        return scopes
    except requests.RequestException as e:
        # Problema de red: no se puede afirmar que falte el permiso, pero tampoco
        # confirmarlo. Se devuelve vacío y se reintenta pronto.
        logger.warning(f'No se pudo consultar tokeninfo de Google: {e}')
        cache.set(clave, [], CACHE_SEGUNDOS_ERROR)
        return set()


def puede_publicar_en_youtube(user, refrescar=False):
    """True si el token de Google del usuario incluye el permiso de subida."""
    return YOUTUBE_UPLOAD_SCOPE in scopes_de_google(user, refrescar=refrescar)


