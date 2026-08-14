from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.sites.models import Site
from django.shortcuts import redirect
from django.utils.html import format_html
from unfold.admin import ModelAdmin
from unfold.decorators import action
from unfold.widgets import UnfoldAdminPasswordToggleWidget
from .forms import CustomUserCreationForm, CustomUserChangeForm
from .models import User

@admin.register(User)
class CustomUserAdmin(UserAdmin, ModelAdmin):
    # Usa nuestros formularios personalizados
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    model = User

    # Campos a mostrar en la lista de usuarios
    list_display = ('username', 'email', 'is_staff', 'is_active',)
    list_filter = ('is_staff', 'is_active', 'groups')

    # Campos que se mostrarán al editar un usuario existente
    fieldsets = (
        (None, {'fields': ('username', 'email', 'password')}),
        ('Permissions', {'fields': ('is_staff', 'is_active', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )

    # Campos que se mostrarán al AÑADIR un nuevo usuario
    # AHORA COINCIDEN CON LOS CAMPOS DEL FORMULARIO
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            # CORREGIDO: password1 y password2 (no "password" y "password2")
            'fields': ('username', 'email', 'password1', 'password2'),
        }),
    )

    # Campos de búsqueda
    search_fields = ('username', 'email',)
    ordering = ('username',)


# =====================================================================
# APPS SOCIALES (django-allauth) — admin mejorado con unfold
# =====================================================================

def _mask(value):
    """Enmascara un secreto mostrando solo los últimos 4 caracteres."""
    if not value:
        return '(vacío)'
    return f'••••{value[-4:]}'


# Guía por provider: qué credenciales pegar y dónde se consiguen.
PROVIDER_HINTS = {
    'twitter': (
        'X (Twitter) usa OAuth 1.0a: pegar las "Consumer Keys" (API Key de 25 chars y '
        'API Secret de 50) desde Keys and tokens en developer.x.com. '
        'NO usar el "OAuth 2.0 Client ID and Client Secret" — no autentican.'
    ),
    'google': 'Client ID y Client Secret desde Google Cloud Console → Credentials (tipo "Web application").',
    'facebook': 'App ID y App Secret desde Meta for Developers → Configuración → Básica.',
    'instagram': 'App ID y App Secret de la app de Meta con el producto Instagram habilitado.',
    'tiktok': 'Client Key y Client Secret desde TikTok for Developers → Manage apps.',
}


class SocialAppForm(forms.ModelForm):
    """Form con secret write-only enmascarado y guía por provider."""

    # Widget de unfold, no el PasswordInput de Django: sin las clases de unfold el
    # input se renderiza sin estilo y en el tema oscuro queda invisible. El toggle
    # además deja ver lo que se pega, que es lo que uno quiere al rotar una key.
    secret = forms.CharField(
        required=False,
        widget=UnfoldAdminPasswordToggleWidget(attrs={'autocomplete': 'new-password'}),
        label='Secret',
        help_text='Dejar vacío para conservar el secret actual.',
    )

    class Meta:
        model = SocialApp
        fields = ['provider', 'name', 'client_id', 'secret', 'key', 'sites']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Dropdown con los IDs exactos de providers instalados (allauth exige
        # minúsculas: 'Facebook' a mano rompe login y test sin error visible)
        from allauth.socialaccount.providers import registry
        provider_ids = sorted(cls.id for cls in registry.get_class_list())
        self.fields['provider'] = forms.ChoiceField(
            choices=[(p, p) for p in provider_ids],
            label='Provider',
        )
        self.fields['key'].help_text = 'Solo lo usan algunos providers (dejar vacío normalmente).'
        self.fields['sites'].help_text = (
            'Sin el Site correcto asociado, allauth NO muestra el botón de login (sin error visible). '
            'Si se deja vacío, se asocia el Site actual automáticamente al guardar.'
        )
        if self.instance and self.instance.pk:
            hint = PROVIDER_HINTS.get(self.instance.provider, '')
            self.fields['client_id'].help_text = hint
            self.fields['secret'].help_text = (
                f'Secret actual: {_mask(self.instance.secret)}. '
                'Dejar vacío para conservarlo; escribir uno nuevo para rotarlo.'
            )

    def clean_secret(self):
        # Vacío = conservar el secret existente (write-only real)
        new_secret = self.cleaned_data.get('secret', '').strip()
        if not new_secret and self.instance and self.instance.pk:
            return self.instance.secret
        return new_secret


admin.site.unregister(SocialApp)
admin.site.unregister(SocialAccount)
admin.site.unregister(SocialToken)
admin.site.unregister(Site)


class SiteForm(forms.ModelForm):
    """Valida el dominio: allauth arma URLs a partir de él."""

    class Meta:
        model = Site
        fields = ['domain', 'name']

    def clean_domain(self):
        domain = (self.cleaned_data.get('domain') or '').strip()
        if '://' in domain:
            raise forms.ValidationError(
                'El dominio va sin esquema: escribí "propaga.lat", no "https://propaga.lat".'
            )
        if '/' in domain:
            raise forms.ValidationError('El dominio va sin rutas ni barras: solo el host.')
        return domain


@admin.register(Site)
class SiteAdmin(ModelAdmin):
    """
    Registrado con unfold porque el admin por defecto de django.contrib.sites se
    renderiza sin los estilos del tema (la barra de acciones queda sin botón para
    ejecutar y borrar se vuelve adivinanza).
    """

    form = SiteForm
    list_display = ('domain', 'name', 'estado')
    search_fields = ('domain', 'name')

    @admin.display(description='Estado')
    def estado(self, obj):
        if obj.pk == settings.SITE_ID:
            return f'✅ Site activo (SITE_ID={settings.SITE_ID}) — es el que usa allauth'
        return '⚪ Sin uso — allauth lo ignora'

    def has_delete_permission(self, request, obj=None):
        # Borrar el Site activo deja el login social muerto y sin mensaje de error
        if obj is not None and obj.pk == settings.SITE_ID:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(SocialApp)
class SocialAppAdmin(ModelAdmin):
    """Gestión de credenciales OAuth de cada red social."""

    form = SocialAppForm
    list_display = ('provider_label', 'name', 'client_id_display', 'secret_display', 'sites_display', 'accounts_count')
    actions_detail = ('probar_credenciales',)

    fieldsets = (
        ('Credenciales', {'fields': ('provider', 'name', 'client_id', 'secret', 'key')}),
        ('Sitio', {
            'fields': ('sites', 'callback_urls'),
            'description': 'La callback URL debe estar registrada EXACTAMENTE igual en el panel del provider.',
        }),
    )
    readonly_fields = ('callback_urls',)
    filter_horizontal = ('sites',)

    @admin.display(description='Proveedor')
    def provider_label(self, obj):
        return obj.provider

    @admin.display(description='Client ID')
    def client_id_display(self, obj):
        return _mask(obj.client_id)

    @admin.display(description='Secret')
    def secret_display(self, obj):
        return _mask(obj.secret)

    @admin.display(description='Sites')
    def sites_display(self, obj):
        """
        allauth solo muestra las apps asociadas al Site de SITE_ID: una app colgada
        de otro Site desaparece del login sin dar ningún error. Se avisa acá porque
        el síntoma (provider invisible) no apunta a la causa.
        """
        domains = list(obj.sites.values_list('domain', flat=True))
        if not domains:
            return '⚠️ SIN SITE — login invisible'

        listado = ', '.join(domains)
        if not obj.sites.filter(pk=settings.SITE_ID).exists():
            return f'⚠️ {listado} — no es el Site activo (id={settings.SITE_ID}): login invisible'
        if any('://' in d for d in domains):
            return f'⚠️ {listado} — el dominio del Site no debe llevar esquema (http://, https://)'
        return f'✅ {listado}'

    @admin.display(description='Cuentas conectadas')
    def accounts_count(self, obj):
        return SocialAccount.objects.filter(provider=obj.provider).count()

    @admin.display(description='Callback URL')
    def callback_urls(self, obj):
        if not obj.pk:
            return '(disponible al guardar)'
        domains = list(obj.sites.values_list('domain', flat=True)) or [Site.objects.get_current().domain]
        urls = [f'https://{d}/accounts/{obj.provider}/login/callback/' for d in domains]
        return format_html('<br>'.join('<code>{}</code>' for _ in urls), *urls)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        # Trampa clásica de allauth: SocialApp sin Site = provider invisible
        if not form.instance.sites.exists():
            form.instance.sites.add(Site.objects.get_current())
            messages.info(request, f'Site "{Site.objects.get_current().domain}" asociado automáticamente.')

    @action(description='🔌 Probar credenciales')
    def probar_credenciales(self, request, object_id):
        app = SocialApp.objects.get(pk=object_id)
        if app.provider == 'twitter':
            from requests_oauthlib import OAuth1Session
            domain = Site.objects.get_current().domain
            session = OAuth1Session(
                app.client_id, client_secret=app.secret,
                callback_uri=f'https://{domain}/accounts/twitter/login/callback/',
            )
            try:
                session.fetch_request_token('https://api.twitter.com/oauth/request_token')
                messages.success(request, '✅ X (Twitter): Consumer Keys válidas (request_token OK).')
            except Exception as e:
                messages.error(request, f'❌ X (Twitter): keys rechazadas — {str(e)[:200]}')
        elif app.provider == 'facebook':
            import requests
            resp = requests.get(
                'https://graph.facebook.com/oauth/access_token',
                params={'client_id': app.client_id, 'client_secret': app.secret,
                        'grant_type': 'client_credentials'},
                timeout=15,
            )
            if resp.ok:
                messages.success(request, '✅ Facebook: App ID y Secret válidos.')
            else:
                detail = resp.json().get('error', {}).get('message', resp.text[:200])
                messages.error(request, f'❌ Facebook: {detail}')
        elif app.provider == 'google':
            import requests
            resp = requests.post(
                'https://oauth2.googleapis.com/token',
                data={'client_id': app.client_id, 'client_secret': app.secret,
                      'grant_type': 'authorization_code', 'code': 'test',
                      'redirect_uri': 'https://localhost/'},
                timeout=15,
            )
            error = resp.json().get('error', '')
            if error == 'invalid_grant':
                # Google rechazó el code falso pero aceptó las credenciales
                messages.success(request, '✅ Google: Client ID y Secret válidos.')
            else:
                messages.error(request, f'❌ Google: credenciales rechazadas ({error or resp.status_code}).')
        else:
            messages.info(request, f'ℹ️ Sin test automático para "{app.provider}". Verificar conectando la cuenta desde el dashboard.')
        return redirect(request.META.get('HTTP_REFERER', '../'))


@admin.register(SocialAccount)
class SocialAccountAdmin(ModelAdmin):
    """Cuentas sociales conectadas por los usuarios."""
    list_display = ('user', 'provider', 'uid', 'date_joined', 'last_login')
    list_filter = ('provider',)
    search_fields = ('user__username', 'user__email', 'uid')
    raw_id_fields = ('user',)


@admin.register(SocialToken)
class SocialTokenAdmin(ModelAdmin):
    """Tokens OAuth de las cuentas conectadas."""
    list_display = ('account', 'app', 'token_display', 'expires_at')
    list_filter = ('account__provider',)
    search_fields = ('account__user__username',)
    raw_id_fields = ('app', 'account')
    readonly_fields = ('token_display', 'token_secret_display')
    exclude = ('token', 'token_secret')

    def has_add_permission(self, request):
        # Los tokens los crea allauth en el flujo OAuth, nunca a mano
        return False

    @admin.display(description='Token')
    def token_display(self, obj):
        return _mask(obj.token)

    @admin.display(description='Token secret')
    def token_secret_display(self, obj):
        return _mask(obj.token_secret)