"""
Publicadores por red. Cinco protocolos, una interfaz.

┌──────────────────────────────────────────────────────────────────────────┐
│  ⚠️  IMPLEMENTACIONES DE PRODUCCIÓN OMITIDAS — NÚCLEO DEL PRODUCTO        │
│                                                                          │
│  Este archivo es un STUB. Las cinco integraciones son lo que PROPAGA      │
│  realmente vende: no la idea de "publicar en varias redes", sino la       │
│  secuencia exacta que cada API acepta, y las decenas de formas en que     │
│  cada una rechaza una subida antes de que des con esa secuencia.          │
│                                                                          │
│  Lo que SÍ se documenta aquí es el PROTOCOLO de cada red: las fases, el   │
│  modelo de autenticación, dónde está la trampa y qué se persiste. Eso     │
│  es lo que tiene valor de ingeniería y lo que un lector quiere entender.  │
│  La implementación no se publica.                                        │
└──────────────────────────────────────────────────────────────────────────┘

CONTRATO COMÚN
==============

Todos los publicadores tienen la misma firma:

    publicar_X(publication, account, social_token, video_path) -> None

y el mismo contrato:

  * **Éxito** = retorno normal. El publicador es responsable de persistir el
    ID y la URL de SU red con `save(update_fields=[...])` antes de retornar.
    Se guarda ahí y no al final del bucle a propósito: si la siguiente red
    revienta o el worker muere, lo que ya salió al aire queda registrado.

  * **Fallo** = excepción con mensaje legible. `propagate_publication` la
    atrapa, la acumula en `fallos` y sigue con la siguiente red. Ninguna red
    puede cancelar a las demás.

Esa uniformidad es lo que permite que la orquestación sea un diccionario y un
bucle de doce líneas en vez de una cadena de `if/elif` de trescientas.

POR QUÉ UN MÓDULO APARTE
========================

Las cinco integraciones no comparten nada salvo el contrato: distinto modelo de
auth, distinto transporte, distintos límites de texto. Lo único que comparten es
*cuándo* se las llama. Mezclarlas dentro de la tarea de Celery hacía que un
cambio en el flujo de TikTok obligara a releer el manejo de errores de YouTube.

Además: aislar el código específico de cada red permite testear la ORQUESTACIÓN
—reparto, éxito parcial, acumulación de fallos, limpieza— sin tocar ninguna API.
Ver `testing/test_03_social_propagation.py`, que en este snapshot es lo que sigue
siendo verificable.
"""
import logging

logger = logging.getLogger(__name__)

GRAPH_API = 'https://graph.facebook.com/v18.0'


class ImplementacionOmitida(NotImplementedError):
    """Se lanza al invocar un publicador en el snapshot público.

    Hereda de NotImplementedError a propósito: el snapshot no es desplegable y
    esta excepción es la frontera exacta donde deja de serlo. `propagate_publication`
    la trata como cualquier otro fallo de red — la acumula y sigue — así que el
    flujo de éxito parcial se puede recorrer y testear igual.
    """

    def __init__(self, red):
        super().__init__(
            f"La implementación de {red} está omitida en el snapshot público de PROPAGA. "
            f"Ver apps/publications/publishers.py para el protocolo."
        )


def publicar_youtube(publication, account, social_token, video_path):
    """YouTube — Data API v3, upload resumible.

    Auth
        OAuth 2.0. El `access_token` de allauth se combina con el `token_secret`
        (que aquí guarda el refresh token, ver `apps/users/signals.py`) y con el
        client_id/secret de la `SocialApp` para construir unas `Credentials`
        que la librería de Google puede refrescar sola.

    Protocolo
        `videos().insert()` con `MediaFileUpload(chunksize=-1, resumable=True)`.
        Chunk -1 = subida en una sola petición; resumable, para que un corte de
        red no obligue a empezar de cero.

    Trampas
        1. `privacyStatus` se envía explícito. Sin él, el default de la API no
           es el que uno espera y un video privado aparece público.
        2. Los hashtags viajan como `tags` (lista, sin '#'), no dentro de la
           descripción: YouTube los indexa distinto.
        3. El thumbnail es una llamada APARTE. Su fallo NO puede tumbar la
           publicación — el video ya está arriba, y morir después de subir 200 MB
           por una miniatura es el peor intercambio posible.
        4. `insufficient authentication scopes` aquí significa que el usuario
           entró con Google pero nunca otorgó el permiso de subida. Ver
           `social_permissions.puede_publicar_en_youtube()`, que lo verifica
           ANTES para que la UI no prometa lo que el worker no puede cumplir.

    Persiste
        `youtube_video_id`, `youtube_video_url`.
    """
    raise ImplementacionOmitida('YouTube')


def publicar_facebook(publication, account, social_token, video_path):
    """Facebook — Graph API, subida a una página.

    Auth
        El token del USUARIO no sirve para publicar en una página. Hay que pedir
        `/me/accounts`, encontrar la página elegida (`publication.facebook_page_id`)
        y usar el `access_token` DE ESA PÁGINA. Es el error más común de la
        integración con Meta y no da un mensaje que lo insinúe.

    Protocolo
        `POST multipart` a `/{page_id}/videos` con el archivo, título y
        descripción + hashtags concatenados.

    Trampas
        1. La Graph API devuelve HTTP 200 con un objeto `error` dentro del JSON.
           Un `raise_for_status()` no detecta nada: hay que inspeccionar el cuerpo.
        2. Si el usuario revocó el permiso de la página después de conectarse,
           `/me/accounts` responde bien pero sin esa página.

    Persiste
        `facebook_video_id`, `facebook_video_url`.
    """
    raise ImplementacionOmitida('Facebook')


def publicar_instagram_reels(publication, account, social_token, video_path):
    """Instagram — Reels vía Graph API. La más indirecta de las cinco.

    Auth
        Instagram no tiene login propio: su Basic Display API murió el
        2024-12-04. Se publica sobre la cuenta IG profesional (Business o
        Creator) VINCULADA a una página de Facebook, con el token de esa página.
        Por eso este publicador recibe la cuenta de Facebook y no una de IG:
        no existe tal cosa.

        La resolución recorre `/me/accounts` buscando `instagram_business_account`,
        y prefiere la misma página que el usuario ya eligió para Facebook.

    Protocolo (tres fases + espera)
        1. `POST /{ig_user_id}/media` con `media_type=REELS` → devuelve un
           `creation_id`. **La API no acepta el archivo**: recibe una URL y
           descarga el video ella misma.
        2. Polling de `status_code` sobre el contenedor hasta `FINISHED`.
           Timeout de ~6 minutos; `ERROR` es terminal.
        3. `POST /{ig_user_id}/media_publish` con el `creation_id`.
        4. Consulta aparte del `permalink` — el publish no lo devuelve.

    Trampas
        1. El punto 1 obliga a exponer el video en una URL PÚBLICA. El worker lo
           copia a `MEDIA_ROOT` bajo un nombre con UUID y arma la URL con el
           dominio del `Site` actual. Es también la razón por la que el worker
           comparte volumen con el proceso web (ver docker-compose.yml).
        2. Esa copia pública **se borra en un `finally`**, falle lo que falle. Un
           video huérfano y accesible por URL no es un problema de espacio en
           disco, es una fuga de contenido del usuario.
        3. El caption va concatenado y truncado a 2200 caracteres.

    Persiste
        `instagram_media_id`, `instagram_permalink`.
    """
    raise ImplementacionOmitida('Instagram')


def publicar_x(publication, account, social_token, video_path):
    """X (Twitter) — subida por fragmentos, OAuth 1.0a.

    Auth
        **OAuth 1.0a, no 2.0.** El endpoint `media/upload` no acepta la firma
        de OAuth 2.0 de la API v2. La `SocialApp` guarda Consumer Key (25
        caracteres) y Consumer Secret (50), no el par Client ID/Secret que la
        consola de desarrolladores ofrece primero.

    Protocolo (cuatro fases)
        1. `INIT`     — declara `total_bytes` y `media_category=tweet_video`.
        2. `APPEND`   — fragmentos de 4 MB, con `segment_index` incremental.
        3. `FINALIZE` — devuelve `processing_info`; si el estado es `pending` o
                        `in_progress` hay que poletear respetando el
                        `check_after_secs` que X indica.
        4. `POST /2/tweets` con el `media_id` ya procesado.

    Trampas
        1. `INIT` puede responder 200, 201 o 202. Tratar solo el 200 como éxito
           rompe de forma intermitente.
        2. El video DEBE ser H.264/AAC con `-pix_fmt yuv420p`. X rechaza otros
           formatos de pixel — de ahí ese flag en el transcode del pipeline.
        3. `client-not-enrolled` significa que la app no está habilitada para
           ese token; se arregla revocando el acceso y reconectando, no
           reintentando.

    Persiste
        `twitter_tweet_id`, `twitter_tweet_url`.
    """
    raise ImplementacionOmitida('X (Twitter)')


def publicar_tiktok(publication, account, social_token, video_path):
    """TikTok — Content Posting API, reserva y subida.

    Auth
        OAuth 2.0, Bearer. Scopes `video.upload` y `video.publish`.

    Protocolo (dos fases)
        1. `POST /v2/post/publish/video/init/` declarando `video_size`,
           `chunk_size` y `total_chunk_count` → devuelve `upload_url` y
           `publish_id`. Se reserva el espacio ANTES de mandar un solo byte.
        2. `PUT` a esa `upload_url` con el archivo y la cabecera
           `Content-Range: bytes 0-{n-1}/{n}`.

    Trampas
        1. TikTok NO devuelve una URL pública inmediata. El video queda en el
           inbox de la cuenta o pendiente según el modo de la app; solo se
           persiste el `publish_id`. La UI no puede prometer un enlace.
        2. `privacy_level` está limitado mientras la app está en revisión: una
           app en desarrollo no puede publicar a `PUBLIC_TO_EVERYONE`.
        3. El caption es un solo campo (título + descripción + hashtags
           concatenados) con tope de 2200 caracteres.

    Persiste
        `tiktok_video_id`.
    """
    raise ImplementacionOmitida('TikTok')


# Reparto por proveedor de allauth. `propagate_publication` itera las cuentas
# destino y busca aquí; una red sin entrada simplemente no se intenta.
#
# Instagram no aparece: no es un proveedor de allauth (no hay login de IG). Se
# dispara por la bandera `publication.publish_to_instagram` sobre la conexión
# de Facebook. Ver `propagate_publication`.
PUBLICADORES = {
    'google': ('YouTube', publicar_youtube),
    'facebook': ('Facebook', publicar_facebook),
    'twitter': ('X (Twitter)', publicar_x),
    'tiktok': ('TikTok', publicar_tiktok),
}
