# Archivo Completo y Correcto: apps/publications/urls.py

from django.urls import path
from .views import (
    DashboardView,
    publication_edit_view,
    regenerate_content_view,
    publish_publication_view,
    get_publication_status_view,
    get_edit_form_view,
    get_processing_steps_view,
    # --- Vistas estáticas que faltaban ---
    PrivacyPolicyView,
    DataDeletionView,
    TermsOfServiceView,
    get_facebook_pages_view,
    publication_status_poll_view,
    ai_config_view,
)

app_name = 'publications'

urlpatterns = [
    # Rutas existentes
    path('', DashboardView.as_view(), name='dashboard'),
    path('config-ia/', ai_config_view, name='ai_config'),
    path('<int:pk>/edit/', publication_edit_view, name='publication_edit'),
    path('<int:pk>/regenerate/', regenerate_content_view, name='regenerate_content'),
    path('<int:pk>/publish/', publish_publication_view, name='publish_publication'),
    
    # Rutas para la actualización dinámica de estado y formulario (HTMX)
    path('status/<int:pk>/', get_publication_status_view, name='get_publication_status'),
    path('form/<int:pk>/', get_edit_form_view, name='get_edit_form'),
    path('steps/<int:pk>/', get_processing_steps_view, name='get_processing_steps'),

    # --- NUEVAS RUTAS REQUERIDAS POR FACEBOOK ---
    # La URL que estaba causando el error 404
    path('data-deletion/', DataDeletionView.as_view(), name='data_deletion'),
    
    # Añadimos las otras por si las necesita en el futuro
    path('privacy-policy/', PrivacyPolicyView.as_view(), name='privacy_policy'),
    path('terms-of-service/', TermsOfServiceView.as_view(), name='terms_of_service'),
    # ¡NUEVA RUTA PARA OBTENER LAS PÁGINAS!
    path('ajax/get-facebook-pages/', get_facebook_pages_view, name='get_facebook_pages'),
    
    # ¡NUEVA RUTA PARA EL PUESTO DE VIGILANCIA!
    path('status-poll/<int:pk>/', publication_status_poll_view, name='publication_status_poll'),
]