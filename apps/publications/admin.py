# Archivo: apps/publications/admin.py

from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect
from django.utils import timezone
from unfold.admin import ModelAdmin
from unfold.decorators import action
from unfold.widgets import UnfoldAdminPasswordToggleWidget
from .models import Publication, AIConfiguration, APIIntegration
from .integrations import (
    PROVIDERS, encrypt_key, decrypt_key, get_provider_config,
    fetch_available_models, test_connection,
)

@admin.register(Publication)
class PublicationAdmin(ModelAdmin):
    """
    Personalización del panel de administración para el modelo Publication.
    """
    # Esta es la orden clave para mejorar la selección de "muchos a muchos".
    # Transforma la caja de selección en una interfaz de doble filtro.
    filter_horizontal = ('target_accounts',)

    # Mejoras adicionales para el Cuartel General:
    # Qué columnas mostrar en la lista de publicaciones
    list_display = ('id', 'title', 'user', 'status', 'created_at')
    # Añade filtros en la barra lateral derecha
    list_filter = ('status', 'user')
    # Añade una barra de búsqueda
    search_fields = ('title', 'description')


@admin.register(AIConfiguration)
class AIConfigurationAdmin(ModelAdmin):
    """Configuración de IA por usuario."""
    list_display = ('user', 'personality', 'hashtags_count', 'use_emojis', 'updated_at')
    list_filter = ('personality', 'use_emojis')
    search_fields = ('user__username', 'custom_instructions')


class APIIntegrationForm(forms.ModelForm):
    """Form con key write-only y selector de modelo dinámico."""

    # Widget de unfold: el PasswordInput de Django se renderiza sin las clases del
    # tema y el campo queda invisible en modo oscuro (hay que encontrarlo al tacto).
    api_key = forms.CharField(
        required=False,
        widget=UnfoldAdminPasswordToggleWidget(attrs={'autocomplete': 'new-password'}),
        label='API Key',
        help_text='Dejar vacío para conservar la key actual. La key nunca se muestra completa.',
    )
    model_name = forms.ChoiceField(required=False, label='Modelo')

    class Meta:
        model = APIIntegration
        fields = ['provider', 'model_name']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        provider = self.instance.provider if self.instance and self.instance.pk else None
        if provider:
            self.fields['provider'].disabled = True
            # Key vigente (DB o entorno) para consultar la lista de modelos
            current_key, current_model = get_provider_config(provider)
            available = fetch_available_models(provider, current_key)
            if current_model and current_model not in available:
                available.insert(0, current_model)
            stored_model = self.instance.model_name
            if stored_model and stored_model not in available:
                available.insert(0, stored_model)
            self.fields['model_name'].choices = [(m, m) for m in available]
            self.fields['api_key'].help_text = (
                f'Key actual: {self.instance.masked_key}. '
                'Dejar vacío para conservarla; escribir una nueva para rotarla.'
            )
        else:
            # Creación: choices estáticas de todos los proveedores (se refina al editar)
            all_models = [m for meta in PROVIDERS.values() for m in meta['static_models']]
            self.fields['model_name'].choices = [(m, m) for m in all_models]

    def save(self, commit=True):
        instance = super().save(commit=False)
        new_key = self.cleaned_data.get('api_key', '').strip()
        if new_key:
            instance.api_key_encrypted = encrypt_key(new_key)
            instance.status = 'unconfigured'  # pendiente de "Probar conexión"
        if commit:
            instance.save()
        return instance


@admin.register(APIIntegration)
class APIIntegrationAdmin(ModelAdmin):
    """Gestión centralizada de keys y modelos de APIs externas."""

    form = APIIntegrationForm
    list_display = ('provider_label', 'key_display', 'model_display', 'status_badge', 'last_tested_at')
    readonly_fields = ('status', 'last_tested_at', 'updated_at')
    actions_detail = ('probar_conexion',)

    @admin.display(description='Proveedor')
    def provider_label(self, obj):
        return obj.get_provider_display()

    @admin.display(description='API Key')
    def key_display(self, obj):
        return obj.masked_key

    @admin.display(description='Modelo')
    def model_display(self, obj):
        return obj.model_name or f"(default: {PROVIDERS[obj.provider]['default_model']})"

    @admin.display(description='Estado')
    def status_badge(self, obj):
        icons = {'active': '🟢', 'invalid': '🔴', 'unconfigured': '🟡'}
        return f"{icons.get(obj.status, '⚪')} {obj.get_status_display()}"

    def response_change(self, request, obj):
        """
        El botón "Probar conexión" es un enlace y no arrastra el formulario, así que
        unfold.js lo convierte en un submit con este flag: se guarda lo editado
        (modelo, key nueva) y recién entonces se prueba. Sin esto se probaría el
        modelo viejo de la DB, ignorando el que el usuario acaba de elegir.
        """
        if '_guardar_y_probar' in request.POST:
            self._probar(request, obj)
            return redirect(request.get_full_path())
        return super().response_change(request, obj)

    def _probar(self, request, integration):
        """Prueba la conexión del proveedor y deja el resultado en la integración."""
        api_key, model_name = get_provider_config(integration.provider)
        ok, detail = test_connection(integration.provider, api_key, model_name)

        integration.status = 'active' if ok else ('invalid' if integration.api_key_encrypted else 'unconfigured')
        integration.last_tested_at = timezone.now()
        integration.save(update_fields=['status', 'last_tested_at'])

        source = 'DB' if integration.api_key_encrypted else 'entorno (.env)'
        etiqueta = integration.get_provider_display()
        if ok:
            messages.success(request, f'✅ {etiqueta} ({model_name}): {detail} Key en uso: {source}.')
        else:
            messages.error(request, f'❌ {etiqueta} ({model_name}): {detail}')
        return ok

    @action(description='🔌 Probar conexión')
    def probar_conexion(self, request, object_id):
        integration = APIIntegration.objects.get(pk=object_id)
        self._probar(request, integration)
        return redirect(request.META.get('HTTP_REFERER', '../'))
