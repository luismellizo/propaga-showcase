"""Vistas del dashboard: HTMX del lado del servidor, sin SPA.

Cada acción del usuario devuelve un fragmento HTML renderizado, no JSON: el
estado de una publicación vive en la base de datos y en Redis, y el navegador
solo pinta lo que el backend ya decidió. La consecuencia práctica es que el
progreso de un video que se está procesando en un worker de Celery se ve igual
en cualquier pestaña, sin sincronizar estado en el cliente.
"""

import json, facebook, logging
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin 
from django.views.generic import TemplateView
from django.db import connection

from .models import Publication, AIConfiguration
from .forms import PublicationEditForm, AIConfigurationForm
from .social_permissions import puede_publicar_en_youtube
from .tasks import regenerate_ai_content, propagate_publication, process_publication
from allauth.socialaccount.models import SocialAccount, SocialApp

from django.views.decorators.http import require_GET
from django.core.cache import cache

# Configurar logging
logger = logging.getLogger(__name__)

class DashboardView(LoginRequiredMixin, View):
    login_url = '/accounts/login/'
    ITEMS_PER_PAGE = 12
    
    def get(self, request, *args, **kwargs):
        from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
        
        # Base queryset
        publications = Publication.objects.filter(user=request.user).order_by('-created_at')
        
        # Filtro por estado
        status_filter = request.GET.get('status', '')
        if status_filter and status_filter != 'ALL':
            publications = publications.filter(status=status_filter)
        
        # Búsqueda por título
        search_query = request.GET.get('q', '').strip()
        if search_query:
            publications = publications.filter(title__icontains=search_query)
        
        # Contadores por estado (para los tabs)
        all_user_pubs = Publication.objects.filter(user=request.user)
        status_counts = {
            'ALL': all_user_pubs.count(),
            'PENDING': all_user_pubs.filter(status='PENDING').count(),
            'PROCESSING': all_user_pubs.filter(status='PROCESSING').count(),
            'AWAITING_APPROVAL': all_user_pubs.filter(status='AWAITING_APPROVAL').count(),
            'PUBLISHED': all_user_pubs.filter(status='PUBLISHED').count(),
            'FAILED': all_user_pubs.filter(status='FAILED').count(),
        }
        
        # Paginación
        paginator = Paginator(publications, self.ITEMS_PER_PAGE)
        page = request.GET.get('page', 1)
        
        try:
            publications_page = paginator.page(page)
        except PageNotAnInteger:
            publications_page = paginator.page(1)
        except EmptyPage:
            publications_page = paginator.page(paginator.num_pages)
        
        context = {
            'publications': publications_page,
            'status_filter': status_filter,
            'search_query': search_query,
            'status_counts': status_counts,
            'total_count': publications.count(),
            # Providers con cuenta conectada (para el marcador visual de "Conectar Cuentas")
            'connected_providers': list(
                SocialAccount.objects.filter(user=request.user).values_list('provider', flat=True)
            ),
            # Tener cuenta de Google NO implica poder subir a YouTube: ese permiso se
            # otorga aparte. Sin esta distinción la tarjeta decía "Conectada" y la
            # publicación fallaba después con 403 en el worker.
            'youtube_autorizado': puede_publicar_en_youtube(request.user),
            # TikTok simbólico hasta configurar su SocialApp (app en review de TikTok)
            'tiktok_available': SocialApp.objects.filter(provider='tiktok').exists(),
        }
        return render(request, 'publications/dashboard.html', context)
    def post(self, request, *args, **kwargs):
        video_url = request.POST.get('video_url')
        video_file = request.FILES.get('video_file')
        
        if video_url or video_file:
            pub = Publication(user=request.user)
            
            if video_url:
                pub.video_url = video_url
            
            if video_file:
                pub.video_file = video_file
                
            pub.save()
            process_publication.delay(pub.id)
            messages.success(request, '¡Misión recibida! El contenido se está procesando.')
        else:
            messages.error(request, 'Debes proporcionar una URL o subir un archivo.')
            
        return redirect('publications:dashboard')

@login_required
def publication_edit_view(request, pk):
    publication = get_object_or_404(Publication, pk=pk, user=request.user)
    
    if request.method == 'POST':
        form = PublicationEditForm(request.POST, request.FILES, instance=publication, user=request.user)
        if form.is_valid():
            instance = form.save() # .save() ya maneja el campo facebook_page_id
            
            trigger_event = 'changesSaved' # Evento por defecto
            
            if 'approve' in request.POST:
                instance.status = 'PUBLISHING'
                instance.save()
                # 🚀 Iniciar la tarea de publicación en Celery
                propagate_publication.delay(instance.id)
                trigger_event = 'missionApproved' # Evento específico para la aprobación
            
            # Preparamos el contexto para re-renderizar el parcial
            all_user_accounts = SocialAccount.objects.filter(user=request.user)
            selected_account_ids = instance.target_accounts.values_list('id', flat=True)
            context = {
                'form': PublicationEditForm(instance=instance, user=request.user),
                'publication': instance,
                'all_user_accounts': all_user_accounts,
                'has_facebook': all_user_accounts.filter(provider='facebook').exists(),
                'has_google': all_user_accounts.filter(provider='google').exists(),
                'youtube_autorizado': puede_publicar_en_youtube(request.user),
                'selected_account_ids': selected_account_ids,
            }
            response = render(request, 'publications/partials/_edit_form.html', context)
            
            # Cabecera HTMX que dispara un evento en el frontend: el template
            # escucha `missionApproved` para abrir la vista de progreso.
            response['HX-Trigger'] = trigger_event
            
            return response
        else:
            logger.error(f"❌ Errores en el formulario para misión {pk}: {form.errors}")
    
    # Lógica para la carga inicial (GET)
    all_user_accounts = SocialAccount.objects.filter(user=request.user)
    selected_account_ids = publication.target_accounts.values_list('id', flat=True)
    form = PublicationEditForm(instance=publication, user=request.user)
    context = {
        'form': form,
        'publication': publication,
        'all_user_accounts': all_user_accounts,
        'has_facebook': all_user_accounts.filter(provider='facebook').exists(),
        'has_google': all_user_accounts.filter(provider='google').exists(),
        'youtube_autorizado': puede_publicar_en_youtube(request.user),
        'selected_account_ids': selected_account_ids
    }
    return render(request, 'publications/publication_edit.html', context)




@login_required
def ai_config_view(request):
    """Configuración de la IA por usuario: personalidad y reglas predeterminadas."""
    config = AIConfiguration.get_for_user(request.user)

    if request.method == 'POST':
        form = AIConfigurationForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            messages.success(request, '✅ Configuración de IA guardada. Se aplicará a las próximas generaciones.')
            return redirect('publications:ai_config')
    else:
        form = AIConfigurationForm(instance=config)

    return render(request, 'publications/ai_config.html', {'form': form, 'config': config})


@login_required
def regenerate_content_view(request, pk):
    publication = get_object_or_404(Publication, pk=pk, user=request.user)
    publication.status = 'PROCESSING'
    publication.processing_step = 'GENERATING'
    publication.save()
    regenerate_ai_content.delay(publication.id)
    
    # Mismo contexto completo que la vista principal: el parcial se re-renderiza
    # entero, y sin las cuentas conectadas los checkboxes desaparecían del DOM.
    all_user_accounts = SocialAccount.objects.filter(user=request.user)
    selected_account_ids = publication.target_accounts.values_list('id', flat=True)
    form = PublicationEditForm(instance=publication, user=request.user)
    
    context = {
        'form': form, 
        'publication': publication,
        'all_user_accounts': all_user_accounts,
        'has_facebook': all_user_accounts.filter(provider='facebook').exists(),
        'has_google': all_user_accounts.filter(provider='google').exists(),
        'youtube_autorizado': puede_publicar_en_youtube(request.user),
        'selected_account_ids': selected_account_ids
    }
    return render(request, 'publications/partials/_edit_form.html', context)


@login_required
def publish_publication_view(request, pk):
    publication = get_object_or_404(Publication, pk=pk, user=request.user)
    if publication.status == 'APPROVED':
        logger.info(f"🚀 Iniciando publicación para misión {pk}. Facebook Page ID: '{publication.facebook_page_id}'")
        
        publication.status = 'PUBLISHING'
        publication.save()
        propagate_publication.delay(publication.id)
    
    # Contexto completo: sin él, el swap del parcial borra las cuentas de la UI.
    all_user_accounts = SocialAccount.objects.filter(user=request.user)
    selected_account_ids = publication.target_accounts.values_list('id', flat=True)
    form = PublicationEditForm(instance=publication, user=request.user)
    
    context = {
        'form': form, 
        'publication': publication,
        'all_user_accounts': all_user_accounts,
        'has_facebook': all_user_accounts.filter(provider='facebook').exists(),
        'has_google': all_user_accounts.filter(provider='google').exists(),
        'youtube_autorizado': puede_publicar_en_youtube(request.user),
        'selected_account_ids': selected_account_ids
    }
    return render(request, 'publications/partials/_edit_form.html', context)

@login_required
def get_edit_form_view(request, pk):
    publication = get_object_or_404(Publication, pk=pk, user=request.user)
    publication.refresh_from_db()  # ← Fuerza lectura desde la base de datos
    
    form = PublicationEditForm(instance=publication, user=request.user)
    all_user_accounts = SocialAccount.objects.filter(user=request.user)
    context = {
        'form': form,
        'publication': publication,
        'all_user_accounts': all_user_accounts,
        'selected_account_ids': publication.target_accounts.values_list('id', flat=True),
        'has_facebook': all_user_accounts.filter(provider='facebook').exists(),
        'has_google': all_user_accounts.filter(provider='google').exists(),
        'youtube_autorizado': puede_publicar_en_youtube(request.user),
    }
    return render(request, 'publications/partials/_edit_form.html', context)

# --- Vista para el estado actualizado en tiempo real ---
@login_required
def get_publication_status_view(request, pk):
    from django.db import transaction

    with transaction.atomic():
        publication = get_object_or_404(Publication, pk=pk, user=request.user)
        publication.refresh_from_db()

        is_htmx = request.headers.get('HX-Request') == 'true'
        hx_target = request.headers.get('HX-Target', '')

        logger.debug(f"[HTMX] pub={pk} status={publication.status} target={hx_target}")

        context = {'pub': publication}
        
        # Si viene del Monitor de Estado en la página de edición (target=main-status)
        # usamos el template inline que solo devuelve el texto del estado
        if hx_target == 'main-status':
            return render(request, 'publications/partials/_status_inline.html', context)
        
        # Para el dashboard y otras vistas, devolvemos el card completo
        if is_htmx:
            response = render(request, 'publications/partials/_publication_card.html', context)
            response['HX-Trigger-After-Swap'] = f'statusUpdated-{pk}'
            return response
        else:
            return render(request, 'publications/partials/_publication_card.html', context)

# --- Vista para el detalle de pasos del backend (vista de progreso embellecida) ---
@login_required
def get_processing_steps_view(request, pk):
    publication = get_object_or_404(Publication, pk=pk, user=request.user)
    return render(request, 'publications/partials/_processing_steps.html', {
        'publication': publication,
        'steps': publication.get_progress_steps(),
    })


@login_required
def get_facebook_pages_view(request):
    """
    Vista reforzada para obtener las páginas de Facebook de un usuario.
    Incluye logging detallado para diagnóstico.
    """
    logger.info(f"📡 Solicitud de páginas de Facebook del usuario pk={request.user.pk}")
    try:
        # Buscamos la cuenta social de Facebook para el usuario activo
        social_account = SocialAccount.objects.get(user=request.user, provider='facebook')
        logger.info(f"✅ Cuenta de Facebook encontrada (SocialAccount pk={social_account.pk}).")

        # Obtenemos el token de acceso
        social_token = social_account.socialtoken_set.first()
        if not social_token or not social_token.token:
            logger.error(f"❌ SocialToken inválido o ausente (SocialAccount pk={social_account.pk})")
            return JsonResponse({'status': 'error', 'message': 'Token de acceso no encontrado o inválido.'}, status=500)
        
        logger.info("🔑 Token de acceso encontrado. Iniciando comunicación con la API Graph de Facebook...")
        
        # Iniciamos la conexión con la API
        graph = facebook.GraphAPI(access_token=social_token.token)
        
        # Solicitamos las páginas asociadas a la cuenta
        pages_data = graph.get_connections(id='me', connection_name='accounts', fields='id,name,access_token')
        
        pages = [{'id': page['id'], 'name': page['name']} for page in pages_data.get('data', [])]
        
        if not pages:
            logger.warning(f"⚠️ Facebook no devolvió páginas para el usuario pk={request.user.pk}.")
        else:
            logger.info(f"📋 Se encontraron {len(pages)} páginas para el usuario. Enviando al frontend.")

        return JsonResponse({'status': 'success', 'pages': pages})

    except SocialAccount.DoesNotExist:
        logger.warning(f"⚠️ Usuario pk={request.user.pk} buscó páginas sin cuenta de Facebook conectada.")
        return JsonResponse({'status': 'error', 'message': 'No se encontró una cuenta de Facebook conectada.'}, status=404)
    except facebook.GraphAPIError as e:
        logger.error(f"💥 Error de la API de Facebook (usuario pk={request.user.pk}): {e}")
        return JsonResponse({'status': 'error', 'message': f'Error de Facebook: {str(e)}'}, status=500)
    except Exception as e:
        logger.error(f"💥 Error inesperado buscando páginas de Facebook (usuario pk={request.user.pk}): {e}", exc_info=True)
        return JsonResponse({'status': 'error', 'message': f'Error interno del servidor: {str(e)}'}, status=500)

class PrivacyPolicyView(TemplateView):
    template_name = 'publications/privacy_policy.html'

class DataDeletionView(TemplateView):
    template_name = 'publications/data_deletion.html'
    
class TermsOfServiceView(TemplateView):
    template_name = 'publications/terms_of_service.html'
    
class WelcomeView(TemplateView):
    template_name = 'pages/welcome.html'    
    
@require_GET
@login_required
def publication_status_poll_view(request, pk):
    """
    Este es el puesto de vigilancia. Revisa si hay una 'bengala' en la caché
    para una publicación específica.
    """
    key = f'publication_updated_{pk}'
    updated = cache.get(key, False)
    
    if updated:
        cache.delete(key)  # Apaga la bengala para no disparar de nuevo
        return JsonResponse({'updated': True})
    
    return JsonResponse({'updated': False})
def dashboard_callback(request, context):
    """
    Callback para el dashboard de Unfold.
    Permite inyectar contexto adicional en el dashboard principal.
    """
    context.update({
        "custom_variable": "value",
    })
    return context
