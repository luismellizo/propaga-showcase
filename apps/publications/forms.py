# Formularios del editor de publicaciones y de la configuracion de IA.
from django import forms
from .models import Publication, AIConfiguration
from allauth.socialaccount.models import SocialAccount

# Widget personalizado que AHORA SÍ funciona
class ProviderCheckboxSelectMultiple(forms.CheckboxSelectMultiple):
    # Definimos un atributo para recibir el queryset
    queryset = None

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        
        # Solo procedemos si el widget ha recibido el queryset y la opción tiene un valor
        if value and self.queryset is not None:
            try:
                # Buscamos la cuenta social en el queryset que nos pasaron
                social_account = self.queryset.get(pk=value.value)
                # Incrustamos la "baliza" de datos
                option['attrs']['data-provider'] = social_account.provider
            except SocialAccount.DoesNotExist:
                # Si por alguna razón no se encuentra, no hacemos nada.
                pass
        return option

# Campo de formulario personalizado que controla la etiqueta
class SocialAccountChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        provider_name = obj.get_provider().name.capitalize()
        account_name = obj.extra_data.get('name', obj.user.username)
        return f"{provider_name} ({account_name})"

class PublicationEditForm(forms.ModelForm):
    target_accounts = SocialAccountChoiceField(
        queryset=None,
        widget=ProviderCheckboxSelectMultiple, # Usamos nuestro widget ahora funcional
        required=False,
        label="Seleccionar Cuentas para Propagar"
    )
    
    # 🚨 AQUÍ ESTÁ LA REPARACIÓN CRÍTICA 🚨
    # Añadimos el campo para las coordenadas del objetivo Facebook
    facebook_page_id = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),  # Campo oculto que será llenado por JavaScript
        label="ID de Página de Facebook"
    )

    class Meta:
        model = Publication
        # 🔥 IMPORTANTE: Añadir facebook_page_id a los campos del formulario
        fields = ['title', 'description', 'hashtags', 'thumbnail', 'target_accounts', 'facebook_page_id', 'publish_to_instagram']
        # Las clases salen del sistema de diseño (static/css/design-system.css).
        # NO poner colores aquí: el file input traía una tira de utilidades de
        # color de Tailwind (paleta esmeralda, con su variante dark:) escrita
        # dentro de Python — fuera de los tokens y sin forma de retematizarla.
        # Lo vigila apps/publications/tests_design_system.py.
        widgets = {
            'title': forms.TextInput(attrs={'class': 'input'}),
            'description': forms.Textarea(attrs={'rows': 5, 'class': 'input'}),
            'hashtags': forms.TextInput(attrs={'class': 'input'}),
            'thumbnail': forms.ClearableFileInput(attrs={'class': 'file-input'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user:
            queryset = SocialAccount.objects.filter(user=user)
            self.fields['target_accounts'].queryset = queryset
            
            # ¡AQUÍ ESTÁ LA LÍNEA CLAVE!
            # Le pasamos la "lista de reclutamiento" (el queryset) a nuestro widget
            # para que pueda hacer su trabajo de etiquetado.
            self.fields['target_accounts'].widget.queryset = queryset
            
            # 🎯 Inicializar el campo facebook_page_id con el valor actual si existe
            if self.instance and self.instance.facebook_page_id:
                self.fields['facebook_page_id'].initial = self.instance.facebook_page_id


class AIConfigurationForm(forms.ModelForm):
    class Meta:
        model = AIConfiguration
        fields = ['personality', 'custom_instructions', 'default_hashtags', 'hashtags_count', 'use_emojis']
        widgets = {
            'personality': forms.Select(attrs={'class': 'input'}),
            'custom_instructions': forms.Textarea(attrs={
                'class': 'input', 'rows': 6,
                'placeholder': 'Ej: Mi nicho es fitness para mayores de 40. Habla siempre de "tú". Nunca uses la palabra "secreto". Termina la descripción invitando a seguir la cuenta.'
            }),
            'default_hashtags': forms.TextInput(attrs={'class': 'input', 'placeholder': '#miMarca #prosite'}),
            'hashtags_count': forms.NumberInput(attrs={'class': 'input', 'min': 1, 'max': 10}),
            'use_emojis': forms.CheckboxInput(attrs={'class': 'switch'}),
        }