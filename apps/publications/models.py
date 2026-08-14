from django.db import models
from django.conf import settings
from allauth.socialaccount.models import SocialAccount

class Publication(models.Model):
    STATUS_CHOICES = [
        # Etiquetas visibles. Solo texto: el valor guardado no cambia.
        # Las anteriores ("Misión Fallida", "Publicado Exitosamente") sonaban a
        # videojuego y no cabían en un badge; estas son cortas y en tuteo.
        ('PENDING', 'En cola'),
        ('PROCESSING', 'Procesando'),
        ('AWAITING_APPROVAL', 'Por aprobar'),
        ('APPROVED', 'Aprobada'),
        ('PUBLISHING', 'Publicando'),
        ('PUBLISHED', 'Publicada'),
        ('FAILED', 'Falló'),
    ]

    # Sub-paso actual dentro de PROCESSING/PUBLISHING (lo escribe el worker de
    # Celery en cada fase; el frontend lo pollea para la vista de progreso).
    # (código, etiqueta amigable, ligadura de Material Symbols Outlined)
    # OJO: el icono se renderiza como texto dentro de <span class="material-symbols-outlined">.
    # Si agregas uno nuevo, súmalo también a `icon_names=` en templates/base.html
    # o saldrá el nombre literal en pantalla.
    PROCESSING_STEPS = [
        ('DOWNLOADING', 'Obteniendo el video', 'download'),
        ('EXTRACTING_AUDIO', 'Extrayendo el audio', 'graphic_eq'),
        ('TRANSCRIBING', 'Transcribiendo el audio con IA', 'mic'),
        ('GENERATING', 'Redactando título, descripción y hashtags', 'auto_awesome'),
        ('TRANSCODING', 'Optimizando el video para redes sociales', 'movie'),
    ]
    PUBLISHING_PROVIDER_STEPS = {
        'google': ('PUB_GOOGLE', 'Subiendo a YouTube', 'smart_display'),
        'facebook': ('PUB_FACEBOOK', 'Publicando en Facebook', 'groups'),
        'twitter': ('PUB_TWITTER', 'Publicando en X (Twitter)', 'chat'),
        'tiktok': ('PUB_TIKTOK', 'Enviando a TikTok', 'music_note'),
    }
    INSTAGRAM_STEP = ('PUB_INSTAGRAM', 'Publicando Reel en Instagram', 'photo_camera')

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    video_url = models.URLField(max_length=1024, blank=True, null=True)
    video_file = models.FileField(upload_to='videos/', blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='PENDING')
    processing_step = models.CharField(max_length=30, blank=True, default='')
    
    title = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    hashtags = models.CharField(max_length=512, blank=True)
    thumbnail = models.ImageField(upload_to='thumbnails/', blank=True, null=True)

    target_accounts = models.ManyToManyField('socialaccount.SocialAccount', blank=True)
    
    
    # En el modelo Publication
    facebook_video_id = models.CharField(max_length=100, blank=True, null=True)
    facebook_video_url = models.URLField(blank=True, null=True)

    # NUEVO CAMPO PARA GUARDAR EL ID DE LA PÁGINA DE FACEBOOK
    facebook_page_id = models.CharField(max_length=100, blank=True, null=True)
    
    # 🔥 NUEVOS CAMPOS PARA GUARDAR LAS COORDENADAS DE X (TWITTER) 🔥
    twitter_tweet_id = models.CharField(max_length=100, blank=True, null=True)
    twitter_tweet_url = models.URLField(blank=True, null=True)
    
    # --- AÑADE ESTOS NUEVOS CAMPOS PARA INSTAGRAM ---
    # Instagram se publica vía la conexión de Facebook (Graph API): la cuenta IG
    # profesional vinculada a la página. No existe login directo de Instagram.
    publish_to_instagram = models.BooleanField(default=False, verbose_name='Publicar en Instagram')
    instagram_media_id = models.CharField(max_length=100, blank=True, null=True)
    instagram_permalink = models.URLField(blank=True, null=True)

    
    # 🔥 YOUTUBE 🔥
    youtube_video_id = models.CharField(max_length=100, blank=True, null=True)
    youtube_video_url = models.URLField(blank=True, null=True)
    
    # 🔥 TIKTOK 🔥
    tiktok_video_id = models.CharField(max_length=100, blank=True, null=True)
    tiktok_video_url = models.URLField(blank=True, null=True)
    
    

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"ID: {self.id} | {self.title[:50]}... ({self.get_status_display()})"

    def set_step(self, step):
        """Marca el sub-paso actual del backend (llamado desde las tareas Celery)."""
        self.processing_step = step
        self.save(update_fields=['processing_step', 'updated_at'])

    def get_progress_steps(self):
        """Pasos del backend para la vista de progreso del editor.

        Devuelve [{'code', 'label', 'icon', 'state'}] donde state es
        'done' | 'active' | 'pending'. Vacío si no hay proceso en curso.
        """
        if self.status == 'PROCESSING':
            steps = list(self.PROCESSING_STEPS)
        elif self.status == 'PUBLISHING':
            steps, seen = [], set()
            # Mismo orden de iteración que propagate_publication (target_accounts.all())
            for account in self.target_accounts.all():
                entry = self.PUBLISHING_PROVIDER_STEPS.get(account.provider)
                if entry and entry[0] not in seen:
                    steps.append(entry)
                    seen.add(entry[0])
            if self.publish_to_instagram:
                steps.append(self.INSTAGRAM_STEP)
        else:
            return []

        codes = [code for code, _, _ in steps]
        # Sin paso registrado aún: el primero se muestra activo
        current = codes.index(self.processing_step) if self.processing_step in codes else 0
        return [
            {
                'code': code,
                'label': label,
                'icon': icon,
                'state': 'done' if i < current else ('active' if i == current else 'pending'),
            }
            for i, (code, label, icon) in enumerate(steps)
        ]



class AIConfiguration(models.Model):
    """Configuración por usuario de la personalidad y reglas de la IA generadora de contenido."""

    PERSONALITY_CHOICES = [
        ('VIRAL', 'Viral / Clickbait — Títulos impactantes que generan curiosidad'),
        ('PROFESIONAL', 'Profesional — Tono serio, corporativo y confiable'),
        ('CASUAL', 'Casual / Cercano — Como hablarle a un amigo'),
        ('HUMORISTICO', 'Humorístico — Divertido, con chispa y sarcasmo ligero'),
        ('EDUCATIVO', 'Educativo — Claro, didáctico y aporta valor'),
        ('INSPIRADOR', 'Inspirador — Motivacional y emotivo'),
        ('VENTAS', 'Ventas — Persuasivo, orientado a conversión'),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ai_config')
    personality = models.CharField(
        max_length=20, choices=PERSONALITY_CHOICES, default='VIRAL',
        verbose_name='Personalidad de la IA'
    )
    custom_instructions = models.TextField(
        blank=True, default='',
        verbose_name='Instrucciones personalizadas',
        help_text='Reglas adicionales para la IA: nicho, palabras prohibidas, estilo de marca, llamados a la acción, etc.'
    )
    default_hashtags = models.CharField(
        max_length=255, blank=True, default='',
        verbose_name='Hashtags fijos',
        help_text='Hashtags que SIEMPRE se incluirán, separados por espacios. Ej: #miMarca #prosite'
    )
    hashtags_count = models.PositiveSmallIntegerField(
        default=3, verbose_name='Cantidad de hashtags generados'
    )
    use_emojis = models.BooleanField(default=True, verbose_name='Usar emojis en título y descripción')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuración de IA'
        verbose_name_plural = 'Configuraciones de IA'

    def __str__(self):
        return f"Config IA de {self.user} ({self.get_personality_display()})"

    @classmethod
    def get_for_user(cls, user):
        config, _ = cls.objects.get_or_create(user=user)
        return config


class APIIntegration(models.Model):
    """Key y modelo de cada proveedor de API externa, gestionados desde el admin.

    La key se guarda cifrada (Fernet derivado de SECRET_KEY). Si no hay fila
    o la key está vacía, los consumidores hacen fallback a la variable de entorno.
    """

    PROVIDER_CHOICES = [
        ('gemini', 'Google Gemini'),
        ('groq', 'Groq (transcripción Whisper)'),
    ]
    STATUS_CHOICES = [
        ('unconfigured', 'Sin configurar'),
        ('active', 'Activa'),
        ('invalid', 'Inválida'),
    ]

    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, unique=True, verbose_name='Proveedor')
    api_key_encrypted = models.TextField(blank=True, default='', verbose_name='API key (cifrada)')
    model_name = models.CharField(max_length=100, blank=True, default='', verbose_name='Modelo')
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='unconfigured', verbose_name='Estado')
    last_tested_at = models.DateTimeField(null=True, blank=True, verbose_name='Última prueba')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Integración API'
        verbose_name_plural = 'Integraciones API'

    def __str__(self):
        return f"{self.get_provider_display()} ({self.get_status_display()})"

    @property
    def masked_key(self):
        from .integrations import decrypt_key, mask_key
        if not self.api_key_encrypted:
            return '(sin key en DB — usando entorno)'
        return mask_key(decrypt_key(self.api_key_encrypted))
