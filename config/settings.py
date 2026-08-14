"""
Settings de PROPAGA.

Toda la configuración sensible entra por entorno (`python-decouple`).
`SECRET_KEY` y `GEMINI_API_KEY` no tienen default a propósito: si faltan, el
proceso no arranca. Un servidor que levanta con una SECRET_KEY de ejemplo es
peor que uno que no levanta.
"""

from pathlib import Path
from decouple import config
from django.templatetags.static import static
from django.urls import reverse_lazy


# --- CONFIGURACIÓN BÁSICA ---
BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = config('SECRET_KEY')
GEMINI_API_KEY = config('GEMINI_API_KEY')
GROQ_API_KEY = config('GROQ_API_KEY', default='')
DEBUG = config('DEBUG', default=False, cast=bool)
ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- SEGURIDAD Y RED ---
# Lee hosts adicionales desde variable de entorno (separados por comas)
_extra_hosts = config('ALLOWED_HOSTS', default='').split(',') if config('ALLOWED_HOSTS', default='') else []
_extra_origins = config('CSRF_TRUSTED_ORIGINS', default='').split(',') if config('CSRF_TRUSTED_ORIGINS', default='') else []

ALLOWED_HOSTS = _extra_hosts
CSRF_TRUSTED_ORIGINS = _extra_origins

# Los túneles de desarrollo (ngrok/cloudflared) son obligatorios para probar
# OAuth: Meta, Google y TikTok exigen un callback HTTPS público, así que el
# `localhost:8000` del runserver no sirve para conectar cuentas. Se habilitan
# SOLO con DEBUG: un comodín de host en producción es superficie de ataque
# gratuita, y aquí no compra nada.
if DEBUG:
    ALLOWED_HOSTS += ['.ngrok-free.app', '.trycloudflare.com', 'localhost', '127.0.0.1']
    CSRF_TRUSTED_ORIGINS += [
        'https://*.ngrok-free.app',
        'https://*.trycloudflare.com',
        'http://localhost:8000',
        'http://127.0.0.1:8000',
        'https://localhost:8000',
    ]
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# --- CONFIGURACIÓN CSRF CORREGIDA PARA DESARROLLO ---
if DEBUG:
    # En desarrollo, desactivamos las configuraciones HTTPS
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    CSRF_COOKIE_HTTPONLY = False
    CSRF_USE_SESSIONS = False
    CSRF_COOKIE_SAMESITE = 'Lax'
else:
    # En producción, activamos las configuraciones de seguridad
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    CSRF_COOKIE_HTTPONLY = True
    CSRF_COOKIE_SAMESITE = 'Strict'

# --- APLICACIONES INSTALADAS ---
INSTALLED_APPS = [
    'unfold',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Activa el framework de "sitios" de Django, requerido por allauth.
    'django.contrib.sites',
    'django_extensions',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.facebook',
    'allauth.socialaccount.providers.google',
    'allauth.socialaccount.providers.tiktok',
    # instagram: eliminado — usaba Basic Display API (muerta desde 2024-12-04).
    # Instagram se publica vía la conexión de Facebook (Graph API).
    'apps.users',
    'apps.publications',
    'apps.testing_ui',
    'allauth.socialaccount.providers.twitter',
]

# --- MIDDLEWARE (ORDEN CORREGIDO) ---
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',  # DEBE ir ANTES de AuthenticationMiddleware
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'allauth.account.middleware.AccountMiddleware',  # DEBE ir DESPUÉS de AuthenticationMiddleware
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# --- RUTAS Y TEMPLATES ---
ROOT_URLCONF = 'config.urls'
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'], # Directorio de templates principal
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.publications.context_processors.site_meta',
            ],
        },
    },
]

# --- BASE DE DATOS ---
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME'),
        'USER': config('DB_USER'),
        'PASSWORD': config('DB_PASSWORD'),
        'HOST': config('DB_HOST'),
        'PORT': config('DB_PORT', cast=int),
    }
}

# --- AUTENTICACIÓN Y USUARIOS ---
AUTH_USER_MODEL = 'users.User'
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# --- INTERNACIONALIZACIÓN Y ARCHIVOS ESTÁTICOS Y DE MEDIOS ---
# Español: allauth y Django traen sus traducciones, y toda la UI del proyecto
# está en español (con 'en-us' los mensajes de allauth salían en inglés).
LANGUAGE_CODE = 'es-co'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Rutas para archivos subidos por el usuario (ej. miniaturas)
MEDIA_ROOT = BASE_DIR / 'media'
MEDIA_URL = '/media/'

# Rutas para archivos estáticos del proyecto (CSS, JS, logos)
STATIC_URL = 'static/'
# Directorio donde 'collectstatic' reunirá los archivos para producción.
STATIC_ROOT = BASE_DIR / 'staticfiles'
# Lista de directorios donde Django buscará archivos estáticos.
STATICFILES_DIRS = [
    BASE_DIR / 'static',
]

# --- CONFIGURACIÓN DE EMAIL (PARA DESARROLLO) ---
if DEBUG:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# --- CONFIGURACIÓN DE CELERY ---
# En Docker, Redis está en el servicio 'redis'. En local, usa localhost.
CELERY_BROKER_URL = config('CELERY_BROKER_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = config('CELERY_RESULT_BACKEND', default='redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'

# Sin límite de tiempo una tarea colgada (descarga o subida trabada) ocupa un slot
# del worker para siempre. Soft = 25 min (lanza excepción, deja marcar FAILED),
# hard = 30 min (mata el proceso).
CELERY_TASK_SOFT_TIME_LIMIT = config('CELERY_TASK_SOFT_TIME_LIMIT', default=1500, cast=int)
CELERY_TASK_TIME_LIMIT = config('CELERY_TASK_TIME_LIMIT', default=1800, cast=int)

# Token de Google Search Console (verificación de propiedad del dominio, necesaria
# para la verificación de marca de la pantalla de consentimiento OAuth). Vacío =
# no se renderiza el meta tag. Alternativa sin deploy: registro TXT en el DNS.
GOOGLE_SITE_VERIFICATION = config('GOOGLE_SITE_VERIFICATION', default='')

# --- CONFIGURACIÓN DE ALLAUTH ---
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]
SITE_ID = 1  # Por defecto en nuevas instalaciones

# --- Redirecciones y Comportamiento ---
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/'
ACCOUNT_LOGOUT_ON_GET = True
ACCOUNT_ALLOW_REGISTRATION = False # Los usuarios solo se crean desde el admin.

# --- Estrategia de autenticación: username ---
ACCOUNT_LOGIN_METHODS = {'username'}
ACCOUNT_SIGNUP_FIELDS = ['email*', 'username*', 'password1*', 'password2*']
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_EMAIL_VERIFICATION = 'none'

# --- Configuración adicional para evitar problemas CSRF ---
ACCOUNT_FORMS = {}  # Usa formularios por defecto de allauth
ACCOUNT_LOGIN_TEMPLATE = 'account/login.html'
ACCOUNT_LOGOUT_TEMPLATE = 'account/logout.html'

# --- Sesión persistente: recordar al usuario logueado ---
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30  # 30 días
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
ACCOUNT_SESSION_REMEMBER = True  # allauth: no expirar al cerrar el navegador

SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_ADAPTER = 'apps.users.adapter.CustomSocialAccountAdapter'
# Sin esto los inputs de /accounts/3rdparty/signup/ salen sin la clase .input
SOCIALACCOUNT_FORMS = {'signup': 'apps.users.forms.CustomSocialSignupForm'}

# Credenciales OAuth por red. La fuente de verdad en runtime son las SocialApp
# de la DB (editables en el admin); estas env vars solo alimentan el comando
# `manage.py seed_social_apps`, que las carga/actualiza en la DB. Así un deploy
# nuevo (Coolify) queda operativo sin entrar al admin a pegar keys a mano.
SOCIAL_OAUTH_CREDENTIALS = {
    'google': {
        'name': 'Google',
        'client_id': config('GOOGLE_CLIENT_ID', default=''),
        'secret': config('GOOGLE_CLIENT_SECRET', default=''),
    },
    'facebook': {
        'name': 'Meta (Facebook + Instagram)',
        'client_id': config('FACEBOOK_CLIENT_ID', default=''),
        'secret': config('FACEBOOK_CLIENT_SECRET', default=''),
    },
    'twitter': {
        'name': 'X (Twitter)',
        'client_id': config('TWITTER_CLIENT_ID', default=''),
        'secret': config('TWITTER_CLIENT_SECRET', default=''),
    },
    'tiktok': {
        'name': 'TikTok',
        'client_id': config('TIKTOK_CLIENT_ID', default=''),
        'secret': config('TIKTOK_CLIENT_SECRET', default=''),
    },
}

SOCIALACCOUNT_PROVIDERS = {
    'google': {
        # Login liviano: solo identidad. El scope de YouTube se pide de forma
        # incremental al CONECTAR la cuenta para publicar (ver templates con
        # scope/auth_params dinámicos en provider_login_url).
        'SCOPE': ['profile', 'email'],
    },
    'facebook': {
        'METHOD': 'oauth2',
        'SCOPE': [
            'public_profile', 
            'email',
            'pages_show_list',
            'pages_read_engagement',
            'pages_manage_posts',
            'instagram_basic',
            'instagram_content_publish',
            'instagram_manage_comments',
            'instagram_manage_insights',
        ],
        'AUTH_PARAMS': {'auth_type': 'reauthenticate'},
        'EXCHANGE_TOKEN': True,
        'VERIFIED_EMAIL': False,
        'VERSION': 'v18.0',
    },
    # No hay entrada para 'instagram': su Basic Display API murió el 2024-12-04.
    # Instagram se publica a través de la conexión de Facebook (Graph API), sobre
    # la cuenta IG profesional vinculada a una página. Ver `publicar_instagram_reels`.
    'tiktok': {
        'SCOPE': [
            'user.info.basic',
            'video.upload',
            'video.publish'
        ],
        'VERSION': 'v2',
    }
}

# --- LOGGING PARA DEBUG (OPCIONAL - SOLO PARA DESARROLLO) ---
if DEBUG:
    LOGGING = {
        'version': 1,
        'disable_existing_loggers': False,
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
            },
        },
        'loggers': {
            'django.security.csrf': {
                'handlers': ['console'],
                'level': 'DEBUG',
                'propagate': True,
            },
        },
    }
    
# --- CONFIGURACIÓN DE CACHÉ UNIFICADA ---
# Usa la misma URL de Redis que Celery, pero en DB 1
_redis_url = config('CELERY_BROKER_URL', default='redis://localhost:6379/0')
_cache_url = _redis_url.replace('/0', '/1')  # Usa DB 1 para caché
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": _cache_url,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        }
    }
}    



# --- CONFIGURACIÓN DE DJANGO UNFOLD ---
UNFOLD = {
    "SITE_TITLE": "Propaga Admin",
    "SITE_HEADER": "PROPAGA",
    "SITE_URL": "/",
    "SITE_ICON": {
        "light": lambda request: static("publications/logo.png"),
        "dark": lambda request: static("publications/logo.png"),
    },
    "DASHBOARD_CALLBACK": "apps.publications.views.dashboard_callback",
    "THEME": "dark",
    "STYLES": [
        lambda request: static("css/unfold.css"),
    ],
    "SCRIPTS": [
        # ?v= igual que en base.html: sin él Cloudflare/navegador sirven la copia vieja
        lambda request: static("js/unfold.js") + "?v=20260803a",
    ],
    "LOGIN": {
        "image": lambda request: static("publications/login_cover.svg"),
    },
    # Paleta esmeralda — misma marca que el frontend (design-system.css)
    "COLORS": {
        "primary": {
            "50": "236 253 245",
            "100": "209 250 229",
            "200": "167 243 208",
            "300": "110 231 183",
            "400": "52 211 153",
            "500": "16 185 129",
            "600": "5 150 105",
            "700": "4 120 87",
            "800": "6 95 70",
            "900": "6 78 59",
            "950": "2 44 34",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": "Navegación",
                "separator": True,
                "items": [
                    {
                        "title": "Dashboard",
                        "icon": "dashboard",
                        "link": reverse_lazy("admin:index"),
                    },
                    {
                        "title": "Usuarios",
                        "icon": "people",
                        "link": reverse_lazy("admin:users_user_changelist"),
                    },
                    {
                        "title": "Publicaciones",
                        "icon": "article",
                        "link": reverse_lazy("admin:publications_publication_changelist"),
                    },
                    {
                        "title": "Configuraciones de IA",
                        "icon": "smart_toy",
                        "link": reverse_lazy("admin:publications_aiconfiguration_changelist"),
                    },
                ],
            },
            {
                "title": "Autenticación",
                "separator": True,
                "items": [
                    {
                        "title": "Grupos",
                        "icon": "lock",
                        "link": reverse_lazy("admin:auth_group_changelist"),
                    },
                    {
                        "title": "Cuentas Sociales",
                        "icon": "share",
                        "link": reverse_lazy("admin:socialaccount_socialaccount_changelist"),
                    },
                    {
                        "title": "Apps Sociales (OAuth)",
                        "icon": "vpn_key",
                        "link": reverse_lazy("admin:socialaccount_socialapp_changelist"),
                    },
                ],
            },
            {
                "title": "Sistema & Calidad",
                "separator": True,
                "items": [
                    {
                        "title": "Integraciones API",
                        "icon": "key",
                        "link": reverse_lazy("admin:publications_apiintegration_changelist"),
                    },
                    {
                        "title": "Centro de Testing",
                        "icon": "science",
                        "link": reverse_lazy("admin:testing_ui_testresult_changelist"),
                    },
                ],
            },
        ],
    },
}