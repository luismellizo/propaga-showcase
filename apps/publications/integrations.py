"""
Gestión centralizada de integraciones con APIs externas (Gemini, Groq).

Las keys se guardan cifradas en DB (modelo APIIntegration) y se leen con
fallback a las variables de entorno actuales: si no hay key en DB, se usa
la de settings — así la transición no rompe nada.
"""
import base64
import hashlib
import logging

import requests
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# --- Cifrado en reposo (Fernet con clave derivada de SECRET_KEY) ---
# Nota: si SECRET_KEY rota, las keys guardadas dejan de poder descifrarse
# y hay que re-ingresarlas desde el admin.


def _fernet():
    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_key(plain_key: str) -> str:
    return _fernet().encrypt(plain_key.encode()).decode()


def decrypt_key(encrypted_key: str) -> str:
    try:
        return _fernet().decrypt(encrypted_key.encode()).decode()
    except (InvalidToken, ValueError):
        logger.error("No se pudo descifrar una API key almacenada (¿rotó SECRET_KEY?). Se usará el fallback de entorno.")
        return ''


def mask_key(plain_key: str) -> str:
    """Representación segura para UI/logs: solo últimos 4 caracteres."""
    if not plain_key:
        return '(vacía)'
    return f"••••{plain_key[-4:]}"


# --- Registro de proveedores ---
# env_setting: atributo de settings usado como fallback.
# default_model: el modelo hardcodeado histórico, fallback si no hay fila en DB.

PROVIDERS = {
    'gemini': {
        'label': 'Google Gemini',
        'env_setting': 'GEMINI_API_KEY',
        'default_model': 'gemini-3.1-flash-lite',
        'static_models': [
            'gemini-3.1-flash-lite', 'gemini-3-flash-preview', 'gemini-2.5-flash',
            'gemini-2.5-flash-lite', 'gemini-2.5-pro', 'gemini-flash-latest',
        ],
    },
    'groq': {
        'label': 'Groq (transcripción Whisper)',
        'env_setting': 'GROQ_API_KEY',
        'default_model': 'whisper-large-v3-turbo',
        'static_models': ['whisper-large-v3-turbo', 'whisper-large-v3'],
    },
}


def get_provider_config(provider: str):
    """
    Devuelve (api_key, model_name) para un proveedor.
    Prioridad key: DB (descifrada) → settings/env. Prioridad modelo: DB → default.
    """
    from .models import APIIntegration

    meta = PROVIDERS[provider]
    api_key = ''
    model_name = meta['default_model']

    try:
        integration = APIIntegration.objects.filter(provider=provider).first()
    except Exception:
        # DB no disponible (p. ej. durante migraciones): fallback total a entorno
        integration = None

    if integration:
        if integration.api_key_encrypted:
            api_key = decrypt_key(integration.api_key_encrypted)
        if integration.model_name:
            model_name = integration.model_name

    if not api_key:
        api_key = getattr(settings, meta['env_setting'], '') or ''

    return api_key, model_name


# --- Listado dinámico de modelos (para el selector del admin) ---

def fetch_available_models(provider: str, api_key: str) -> list:
    """Lista de modelos desde la API del proveedor; fallback a lista estática. Caché 10 min."""
    meta = PROVIDERS[provider]
    if not api_key:
        return meta['static_models']

    cache_key = f'api_models_{provider}'
    cached = cache.get(cache_key)
    if cached:
        return cached

    models = []
    try:
        if provider == 'gemini':
            r = requests.get(
                'https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000',
                headers={'x-goog-api-key': api_key}, timeout=5,
            )
            r.raise_for_status()
            models = sorted(
                m['name'].removeprefix('models/')
                for m in r.json().get('models', [])
                if 'generateContent' in m.get('supportedGenerationMethods', [])
                and 'gemini' in m['name']
            )
        elif provider == 'groq':
            r = requests.get(
                'https://api.groq.com/openai/v1/models',
                headers={'Authorization': f'Bearer {api_key}'}, timeout=5,
            )
            r.raise_for_status()
            models = sorted(m['id'] for m in r.json().get('data', []) if 'whisper' in m['id'])
    except Exception as e:
        logger.warning(f"No se pudo obtener lista dinámica de modelos de {provider}: {e}")

    if not models:
        return meta['static_models']

    cache.set(cache_key, models, 600)
    return models


# --- Prueba de conexión ---

def test_connection(provider: str, api_key: str, model_name: str):
    """
    Valida la key con un request mínimo real.
    Devuelve (ok: bool, detalle: str). Nunca incluye la key en el detalle.
    """
    if not api_key:
        return False, 'Sin API key configurada (ni en DB ni en entorno).'

    try:
        if provider == 'gemini':
            r = requests.post(
                f'https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent',
                headers={'Content-Type': 'application/json', 'x-goog-api-key': api_key},
                json={'contents': [{'parts': [{'text': 'ping'}]}],
                      'generationConfig': {'maxOutputTokens': 1}},
                timeout=15,
            )
        elif provider == 'groq':
            # Whisper no acepta ping barato: validamos autenticación contra /models
            r = requests.get(
                'https://api.groq.com/openai/v1/models',
                headers={'Authorization': f'Bearer {api_key}'}, timeout=15,
            )
        else:
            return False, f'Proveedor desconocido: {provider}'

        if r.status_code == 200:
            return True, f'Conexión OK (modelo: {model_name}).'
        detail = r.json().get('error', {}).get('message', r.text[:200]) if r.text else ''
        return False, f'HTTP {r.status_code}: {detail[:200]}'
    except requests.RequestException as e:
        return False, f'Error de red: {e.__class__.__name__}'
