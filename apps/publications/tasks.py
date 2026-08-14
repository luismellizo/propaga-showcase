"""
Tareas de Celery: el ciclo de vida completo de una publicación.

Dos tareas, y el corte entre ellas es la decisión estructural del sistema:

    process_publication(id)    URL/archivo → video listo + texto generado
    propagate_publication(id)  video + texto → publicado en N redes

Entre las dos hay una persona: `process_publication` termina en
`AWAITING_APPROVAL` y ahí se detiene. Publicar es irreversible y lo decide el
usuario, no el pipeline.

Ambas persisten su estado en la fila de `Publication` —status y sub-paso— que
es lo que el frontend poletea para pintar el progreso. El worker es la única
fuente de verdad sobre en qué va un video.

Nota del snapshot público
-------------------------
Dos piezas están omitidas, ambas documentadas donde deberían estar:

  * `prompts.py`     — arquitectura del prompt sin sus textos de producción.
  * `publishers.py`  — protocolo de cada red sin sus implementaciones.

Lo que queda completo es todo lo demás: el locking, la degradación ante fallos
de terceros, el manejo de éxito parcial y la limpieza de residuos.
"""
import fcntl
import glob
import json
import logging
import os
import shutil
import subprocess
import time
import traceback
import uuid

import httpx
import requests
import yt_dlp
from celery import shared_task
from django.core.cache import cache
from django.db import transaction
from groq import Groq

from .integrations import get_provider_config
from .models import AIConfiguration, Publication
from .prompts import build_content_prompt
from .publishers import PUBLICADORES, publicar_instagram_reels

logger = logging.getLogger(__name__)

# --- FUNCIONES DE IA ---


def call_gemini_api(transcription, user=None):
    """Genera título, descripción y hashtags a partir de la transcripción.

    El prompt se arma en `prompts.build_content_prompt()` — ese módulo es un
    stub en este snapshot público: documenta la arquitectura por capas del
    prompt, pero los textos de producción están omitidos.
    """
    # Key y modelo desde la configuración centralizada (DB con fallback a .env)
    api_key, model = get_provider_config('gemini')
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}

    # Configuración de IA del usuario (personalidad + reglas propias)
    config = AIConfiguration.get_for_user(user) if user else None
    prompt = build_content_prompt(transcription, config)

    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    logger.info("Enviando petición con prompt mejorado a Gemini...")
    response = requests.post(url, headers=headers, json=data, timeout=60)
    response.raise_for_status()
    logger.info("Respuesta de Gemini recibida.")
    # Normaliza al formato estilo OpenAI que espera el resto del código
    gemini_json = response.json()
    content = gemini_json["candidates"][0]["content"]["parts"][0]["text"]
    return {"choices": [{"message": {"content": content}}]}

def generate_fallback_content(transcription):
    """Contenido de respaldo cuando el proveedor de IA no responde.

    Determinista y sin red: recorta la propia transcripcion. Peor contenido,
    pero contenido editable en pantalla — mejor que morir en FAILED despues de
    que el usuario ya espero descarga, extraccion y transcripcion.
    """
    logger.info("🔄 Generando contenido de fallback...")
    words = transcription.split()[:8]
    title = " ".join(words) + "..."
    if len(title) > 80:
        title = title[:77] + "..."
    description = transcription[:150] + "..." if len(transcription) > 150 else transcription
    hashtags = "#viral #contenido #video"
    return {"choices": [{"message": {"content": json.dumps({"title": f"🔥 {title}", "description": description, "hashtags": hashtags})}}]}

# --- TAREAS DE CELERY ---
@shared_task
def regenerate_ai_content(publication_id):
    """Vuelve a redactar el texto de una publicacion ya transcrita.

    No re-descarga ni re-transcribe: reusa la descripcion guardada como fuente.
    """
    logger.info(f"Recibida orden de REGENERACIÓN para ID: {publication_id}")
    try:
        publication = Publication.objects.get(id=publication_id)
        transcription_text = publication.description
        try:
            ia_response = call_gemini_api(transcription_text, user=publication.user)
            generated_content = json.loads(ia_response['choices'][0]['message']['content'])
            logger.info("✅ Contenido regenerado por Gemini")
        except Exception as ai_error:
            logger.warning(f"⚠️ Gemini falló en regeneración: {ai_error}")
            ia_response = generate_fallback_content(transcription_text)
            generated_content = json.loads(ia_response['choices'][0]['message']['content'])
            logger.info("✅ Contenido de fallback usado en regeneración")
        publication.title = generated_content.get('title', 'Título no generado')
        publication.description = generated_content.get('description', transcription_text)
        publication.hashtags = generated_content.get('hashtags', '')
        publication.status = 'AWAITING_APPROVAL'
        publication.processing_step = ''
        publication.save()
        logger.info(f"Contenido para ID: {publication_id} regenerado exitosamente.")
        return f"Contenido para {publication_id} regenerado."
    except Exception as e:
        logger.error(f"FALLO en la regeneración para ID: {publication_id}. Error: {e}")
        return "Error durante la regeneración."

def _es_compatible_redes(video_path):
    """True si el video ya viene en H.264 + AAC, los códecs que aceptan todas las
    redes. En ese caso el paso final es un remux (-c copy) y no un re-encode, que
    en videos largos cuesta minutos de CPU."""
    try:
        probe = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_name,codec_type',
             '-of', 'csv=p=0', video_path],
            capture_output=True, text=True, timeout=30,
        )
        if probe.returncode != 0:
            return False
        codecs = dict(
            (tipo, nombre)
            for nombre, tipo in (l.split(',') for l in probe.stdout.strip().splitlines() if ',' in l)
        )
        return codecs.get('video') == 'h264' and codecs.get('audio') == 'aac'
    except Exception as e:
        logger.warning(f"No se pudo inspeccionar códecs de {video_path}: {e}")
        return False


@shared_task(bind=True)
def process_publication(self, publication_id):
    """
    Descarga el video (Youtube/URL) o usa el archivo local, extrae audio, transcribe (Whisper),
    genera contenido viral (Gemini) y prepara el video final.
    """
    redis_lock_key = f'processing_pub_{publication_id}'
    worker_id = f'{self.request.id}_{uuid.uuid4().hex[:8]}'

    if cache.get(redis_lock_key):
        logger.warning(f"Publicación {publication_id} ya está siendo procesada por otro worker")
        return f"Publicación {publication_id} ya en proceso"

    # 1h: el lock se borra en el finally. Con 600s expiraba mientras la tarea seguía
    # viva y otro worker podía arrancar la misma publicación en paralelo.
    cache.set(redis_lock_key, worker_id, timeout=3600)
    logger.info(f"🔥 Worker {worker_id} inicia misión para ID: {publication_id}")

    publication = None
    temp_dir = None

    try:
        with transaction.atomic():
            publication = Publication.objects.select_for_update().get(id=publication_id)
            if publication.status == 'PROCESSING':
                logger.warning(f"Publicación {publication_id} ya tiene status PROCESSING")
                return f"Publicación {publication_id} ya procesándose"
            
            publication.status = 'PROCESSING'
            publication.error_message = "" # Limpiar error previo
            publication.processing_step = 'DOWNLOADING'
            publication.save()

        timestamp = int(time.time())
        temp_dir = f'/tmp/propaga_{publication_id}_{timestamp}_{worker_id[:8]}'
        os.makedirs(temp_dir, exist_ok=True)
        logger.info(f"📁 Directorio único: {temp_dir}")

        lock_file = os.path.join(temp_dir, '.lock')
        with open(lock_file, 'w') as f:
            # El except cubre SOLO la adquisición del lock. Antes envolvía el
            # pipeline entero, y como IOError es un alias de OSError, cualquier
            # FileNotFoundError de ffmpeg o del sistema de archivos se reportaba
            # como "no se pudo obtener el lock": la tarea retornaba sin marcar
            # FAILED y la publicación quedaba colgada en PROCESSING, sin mensaje
            # de error, sin nada que mirar en la UI.
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                logger.error(f"No se pudo obtener file lock para {publication_id}")
                return f"Otro proceso ya está procesando {publication_id}"

            f.write(worker_id)

            
            video_file_path = None
            
            # --- PASO 1: OBTENCIÓN DEL VIDEO (URL o LOCAL) ---
            if publication.video_file:
                # CASO A: Archivo Local
                logger.info(f"📂 Usando archivo local: {publication.video_file.name}")
                if not os.path.exists(publication.video_file.path):
                    raise Exception(f"El archivo local no existe en disco: {publication.video_file.path}")
                
                # Copiar a temp para procesar
                original_ext = os.path.splitext(publication.video_file.name)[1]
                if not original_ext: original_ext = ".mp4"
                
                temp_video_path = os.path.join(temp_dir, f"source_video{original_ext}")
                shutil.copy2(publication.video_file.path, temp_video_path)
                video_file_path = temp_video_path
                logger.info(f"✅ Archivo local copiado a: {video_file_path}")
                
            elif publication.video_url:
                # CASO B: Descarga desde URL (Youtube, etc)
                ydl_opts = {
                    'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
                    # Preferimos H.264 + AAC ≤1080p: es lo que aceptan todas las redes,
                    # así el transcode final se vuelve un copy de streams (segundos en vez
                    # de minutos). 'bestvideo+bestaudio' traía AV1/VP9/Opus en 4K y obligaba
                    # a re-encodear el video entero con libx264.
                    'format': (
                        'bestvideo[vcodec^=avc1][height<=1080]+bestaudio[acodec^=mp4a]/'
                        'best[ext=mp4][height<=1080]/'
                        'bestvideo[height<=1080]+bestaudio/best'
                    ),
                    'merge_output_format': 'mp4',
                    'noplaylist': True,
                    'quiet': False,
                    'no_warnings': False,
                    # Fragmentos en paralelo: descargas de varios minutos bajan a decenas de segundos
                    'concurrent_fragment_downloads': 4,
                    'retries': 3,
                    'fragment_retries': 3,
                    'writesubtitles': False,
                    'writeautomaticsub': False,
                }
                logger.info(f"🎬 Iniciando descarga con yt-dlp en: {temp_dir}")
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([publication.video_url])
                logger.info(f"✅ Descarga completada en: {temp_dir}")

                # Buscar el archivo descargado
                video_files = []
                for ext in ['*.mp4', '*.mkv', '*.webm', '*.avi', '*.mov']:
                    video_files.extend(glob.glob(os.path.join(temp_dir, ext)))
                
                if not video_files:
                    raise Exception(f"No se encontró archivo de video descargado en {temp_dir}")
                video_file_path = video_files[0]
            else:
                raise Exception("La publicación no tiene ni URL de video ni archivo local.")

            # --- PASO 2: EXTRACCIÓN DE AUDIO ---
            publication.set_step('EXTRACTING_AUDIO')
            audio_file = os.path.join(temp_dir, 'audio.mp3')
            logger.info(f"🎵 Convirtiendo: {os.path.basename(video_file_path)} → audio.mp3")

            # Audio SOLO para Whisper: 16 kHz mono a 32 kbps.
            # Whisper remuestrea internamente a 16 kHz mono, así que bajar de
            # '-q:a 0' (≈245 kbps estéreo) NO pierde precisión y reduce el archivo
            # ~8x: 16 min de video pasan de ~30 MB (sobre el límite de 25 MB de Groq
            # y del write-timeout del SDK) a ~4 MB.
            ffmpeg_audio_cmd = [
                'ffmpeg', '-i', video_file_path,
                '-vn', '-map', '0:a:0',
                '-ac', '1', '-ar', '16000',
                '-c:a', 'libmp3lame', '-b:a', '32k',
                audio_file, '-y',
            ]

            result_audio = subprocess.run(ffmpeg_audio_cmd, capture_output=True, text=True)
            if result_audio.returncode != 0:
                 # Fallback si falla extracción simple (ej. video sin audio o formato raro)
                 logger.warning(f"Falla extracción audio simple: {result_audio.stderr}. Intentando síntesis muda o reintento.")
                 # Si falla audio, quizás no tenga. Crear silencio? Por ahora fallamos.
                 raise Exception(f"Error extrayendo audio con ffmpeg: {result_audio.stderr}")

            logger.info(f"✅ Conversión audio completada")

            # --- PASO 3: TRANSCRIPCIÓN (GROQ API) ---
            publication.set_step('TRANSCRIBING')
            groq_key, groq_model = get_provider_config('groq')
            audio_mb = os.path.getsize(audio_file) / (1024 * 1024)
            logger.info(f"🎤 Iniciando transcripción con Groq API ({groq_model}), audio={audio_mb:.1f} MB...")
            if audio_mb > 24:
                raise Exception(
                    f"El audio pesa {audio_mb:.1f} MB y Groq acepta máximo 25 MB. "
                    "El video es demasiado largo para transcribirlo de una sola pieza."
                )
            # Timeouts explícitos: el default del SDK es write=60s, que reventaba
            # las subidas grandes con 'Connection error' tras 2 reintentos silenciosos.
            groq_client = Groq(
                api_key=groq_key,
                timeout=httpx.Timeout(connect=10.0, read=300.0, write=300.0, pool=300.0),
                max_retries=2,
            )
            t_transcribe = time.time()
            with open(audio_file, "rb") as audio_f:
                transcription = groq_client.audio.transcriptions.create(
                    file=("audio.mp3", audio_f.read()),
                    model=groq_model,
                    language="es"
                )
            transcription_text = transcription.text
            logger.info(
                f"✅ Transcripción completada en {time.time() - t_transcribe:.1f}s: "
                f"{len(transcription_text)} caracteres"
            )

            # --- PASO 4: GENERACIÓN IA (GEMINI) ---
            publication.set_step('GENERATING')
            logger.info(f"🤖 Iniciando IA processing...")
            try:
                ia_response = call_gemini_api(transcription_text, user=publication.user)
                generated_content = json.loads(ia_response['choices'][0]['message']['content'])
                logger.info("✅ Contenido generado por Gemini")
            except Exception as ai_error:
                logger.warning(f"⚠️ Gemini falló: {ai_error}")
                logger.info("🔄 Usando contenido de fallback...")
                ia_response = generate_fallback_content(transcription_text)
                generated_content = json.loads(ia_response['choices'][0]['message']['content'])
                logger.info("✅ Contenido de fallback generado")

            # --- ACTUALIZAR PUBLICACIÓN ---
            publication.title = generated_content.get('title', 'Título no generado por IA')
            publication.description = generated_content.get('description', transcription_text)
            publication.hashtags = generated_content.get('hashtags', '#errorIA')

            # El texto ya está listo: liberamos al usuario ANTES de transcodificar.
            # Antes el status AWAITING_APPROVAL solo se persistía después del encode
            # (`set_step` solo guarda processing_step), así que el dashboard quedaba en
            # PROCESSING durante los minutos que tardaba libx264 con el video completo.
            publication.status = 'AWAITING_APPROVAL'
            publication.save()

            # Guardar el video final procesado en /tmp para persistencia temporal (o mover a media si quisiéramos)
            # Por ahora mantenemos la lógica de copiar a /tmp/final_video_{id}.mp4
            final_destination = os.path.join('/tmp', f'final_video_{publication_id}.mp4')

            # El video debe quedar en MP4 H.264/AAC: un .mp4 puede traer códecs internos
            # (VP9, AV1, Opus) que Twitter y otras redes rechazan. Pero si ya viene en
            # H.264/AAC solo remuxeamos (-c copy): segundos en vez de minutos de CPU.
            publication.set_step('TRANSCODING')
            t_transcode = time.time()
            if _es_compatible_redes(video_file_path):
                logger.info("🔄 Video ya es H.264/AAC: remux directo (sin re-encodear)...")
                transcode_cmd = [
                    'ffmpeg', '-i', video_file_path,
                    '-map', '0:v:0', '-map', '0:a:0',
                    '-c', 'copy',
                    '-movflags', '+faststart',
                    '-y', final_destination,
                ]
            else:
                logger.info("🔄 Transcodificando a MP4 H.264/AAC para compatibilidad con redes sociales...")
                transcode_cmd = [
                    'ffmpeg', '-i', video_file_path,
                    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',  # veryfast: ~4x más rápido que medium
                    '-c:a', 'aac', '-b:a', '128k',  # Audio AAC
                    '-pix_fmt', 'yuv420p',  # Formato de pixel estándar requerido por Twitter
                    '-movflags', '+faststart',  # Optimización para streaming
                    '-y',  # Sobrescribir sin preguntar
                    final_destination,
                ]
            transcode_result = subprocess.run(transcode_cmd, capture_output=True, text=True)
            if transcode_result.returncode != 0:
                logger.error(f"Error transcodificando: {transcode_result.stderr}")
                raise Exception(f"Error transcodificando video: {transcode_result.stderr}")
            logger.info(f"✅ Video listo en {time.time() - t_transcode:.1f}s: {final_destination}")

            publication.processing_step = ''
            publication.save()
            logger.info(f"🎉 MISIÓN COMPLETADA para ID: {publication_id}")
            return f"Publicación {publication_id} procesada exitosamente."


    except Exception as e:
        error_msg = f"💥 FALLO en ID: {publication_id}: {str(e)}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        
        if publication:
            try:
                publication.status = 'FAILED'
                publication.processing_step = ''
                publication.error_message = f"{str(e)}\n\n{traceback.format_exc()}"[:5000] # Guardar log en DB
                publication.save()
            except Exception as db_err:
                logger.error(f"No se pudo guardar estado de error en DB: {db_err}")
                
        return f"Error procesando publicación {publication_id}."

    finally:
        cache.delete(redis_lock_key)
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
                logger.info(f"🗑️ Directorio temporal limpiado: {temp_dir}")
            except Exception as e:
                logger.warning(f"No se pudo limpiar {temp_dir}: {e}")

def _resumir_fallos(fallos):
    """
    Arma el texto que ve el usuario a partir de los fallos por red.
    Traduce los errores de API más frecuentes a algo accionable: el mensaje crudo
    de Google/Meta/X no le dice a nadie qué hacer.
    """
    if not fallos:
        return ''

    # Tabla de traducción error crudo → instrucción accionable.
    #
    # ⚠️  Tabla de producción recortada en este snapshot público. La real tiene
    # bastantes más entradas: es el sedimento de cada forma distinta en que
    # Google, Meta, X y TikTok rechazan una subida, y saber qué le tiene que
    # hacer el usuario ante cada una tomó meses de fallos reales. Se dejan dos
    # entradas como muestra del mecanismo.
    PISTAS = (
        ('insufficient authentication scopes', 'Falta el permiso de subida de YouTube: reconecta Google desde Conectar Cuentas y acepta "Subir videos de YouTube".'),
        ('invalid_grant', 'El permiso expiró o fue revocado: reconecta la cuenta desde Conectar Cuentas.'),
        # [Resto de las pistas por red omitidas por confidencialidad.]
    )

    lineas = []
    for red, error in fallos:
        error = (error or '').strip()
        pista = next((sugerencia for marca, sugerencia in PISTAS if marca in error), '')
        lineas.append(f'❌ {red}: {pista or error[:300]}')
        if pista:
            lineas.append(f'   Detalle técnico: {error[:300]}')
    return '\n'.join(lineas)[:5000]


# --- TAREA DE PROPAGACIÓN ---
@shared_task
def propagate_publication(publication_id):
    """Publica en cada red destino, con el protocolo que cada una exige.

    Un fallo en una red NO cancela las demás: se acumula en `fallos` y al final
    se decide el estado. Si al menos una aceptó el video, el estado es PUBLISHED
    y el detalle de lo que falló se guarda en la fila para mostrarlo en la UI.
    """
    logger.info(f"🚀 PROPAGACIÓN iniciada para ID: {publication_id}")
    publication = None
    video_path = f'/tmp/final_video_{publication_id}.mp4' # Define path centrally for cleanup
    try:
        publication = Publication.objects.get(id=publication_id)
        target_accounts = publication.target_accounts.all()
        if not target_accounts and not publication.publish_to_instagram:
            raise Exception("No se seleccionaron cuentas de destino.")

        published_successfully_count = 0
        # Fallos por red. Se guardan en la publicación aunque alguna otra red
        # funcione: antes se marcaba PUBLISHED y los errores morían en los logs
        # del worker, así que el usuario creía que había salido todo bien.
        fallos = []

        for account in target_accounts:
            entrada = PUBLICADORES.get(account.provider)
            if entrada is None:
                logger.warning(f"Proveedor sin publicador: {account.provider}. Se omite.")
                continue

            etiqueta, publicar = entrada
            logger.info(f"📡 Procesando cuenta {account.id} ({account.provider})")

            social_token = account.socialtoken_set.first()
            if not social_token:
                logger.error(f"❌ Sin SocialToken para la cuenta {account.id}")
                fallos.append((etiqueta, 'La cuenta no tiene token guardado: reconéctala desde Conectar Cuentas.'))
                continue

            try:
                publication.set_step(Publication.PUBLISHING_PROVIDER_STEPS[account.provider][0])
                # El publicador persiste el ID y la URL de SU red antes de retornar.
                # Ver el contrato en publishers.py.
                publicar(publication, account, social_token, video_path)
                published_successfully_count += 1
            except Exception as e:
                # Deliberadamente ancho: una red que revienta de forma inesperada
                # no puede impedir que las otras cuatro salgan al aire.
                logger.error(f"💥 Falló la publicación en {etiqueta}: {e}", exc_info=True)
                fallos.append((etiqueta, str(e)))

        # --- INSTAGRAM ---
        # Fuera del bucle porque no es una cuenta de allauth: no hay login de
        # Instagram desde que murió Basic Display API (2024-12-04). Se publica
        # sobre la conexión de Facebook, y por eso lo dispara una bandera de la
        # publicación y no la presencia de una SocialAccount.
        if publication.publish_to_instagram:
            try:
                publication.set_step(Publication.INSTAGRAM_STEP[0])
                fb_account = publication.user.socialaccount_set.filter(provider='facebook').first()
                if not fb_account:
                    raise Exception(
                        "Instagram requiere una cuenta de Facebook conectada "
                        "(la cuenta IG profesional vinculada a tu página)."
                    )
                fb_token = fb_account.socialtoken_set.first()
                if not fb_token:
                    raise Exception("La cuenta de Facebook no tiene token OAuth. Reconéctala desde el dashboard.")

                publicar_instagram_reels(publication, fb_account, fb_token, video_path)
                published_successfully_count += 1
            except Exception as e:
                logger.error(f"💥 Falló la publicación en Instagram: {e}", exc_info=True)
                fallos.append(('Instagram', str(e)))

        if published_successfully_count > 0:
            publication.status = 'PUBLISHED'
            publication.processing_step = ''
            # Éxito parcial: se publicó en algunas redes pero no en todas. El estado
            # queda PUBLISHED (algo salió), pero el detalle de lo que falló tiene que
            # llegar al usuario en vez de quedar solo en los logs del worker.
            publication.error_message = _resumir_fallos(fallos)
            publication.save()
            if fallos:
                redes = ', '.join(red for red, _ in fallos)
                logger.warning(f"⚠️ PROPAGACIÓN PARCIAL para ID: {publication_id} — falló: {redes}")
                return f"Propagación parcial para {publication_id}: falló {redes}"
            logger.info(f"🎉 PROPAGACIÓN EXITOSA para ID: {publication_id}")
            return f"Propagación exitosa para {publication_id}"
        else:
            detalle = _resumir_fallos(fallos)
            raise Exception(f"Fallaron todos los intentos de publicación.\n\n{detalle}" if detalle
                            else "Fallaron todos los intentos de publicación")

    except Exception as e:
        error_msg = f"💥 FALLO propagación ID: {publication_id}: {e}"
        logger.error(error_msg, exc_info=True)
        if publication:
            try:
                publication.status = 'FAILED'
                publication.processing_step = ''
                publication.error_message = f"Error Propagación: {str(e)}\n\n{traceback.format_exc()}"[:5000]
                publication.save()
            except Exception as db_err:
                logger.error(f"No se pudo guardar error en DB: {db_err}")
        return f"Error en propagación {publication_id}"

    finally:
        # --- LIMPIEZA DE RESIDUOS ---
        if os.path.exists(video_path):
            try:
                os.remove(video_path)
                logger.info(f"🗑️ Archivo temporal eliminado: {video_path}")
            except Exception as e:
                logger.warning(f"⚠️ No se pudo eliminar archivo temporal {video_path}: {e}")