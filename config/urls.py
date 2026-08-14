from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse

# Importamos la nueva vista de bienvenida
from apps.publications.views import WelcomeView


# Vista simple para health check (usado por Docker y load balancers)
def health_check(request):
    return JsonResponse({'status': 'healthy', 'service': 'propaga'})


urlpatterns = [
    # Health check endpoint (para Docker y load balancers)
    path('health/', health_check, name='health_check'),
    
    # 1. La nueva página de bienvenida es ahora la raíz del sitio
    path('', WelcomeView.as_view(), name='welcome'),

    # 2. El resto de las rutas
    path('admin/', admin.site.urls),
    path('dashboard/', include('apps.publications.urls')),
    path('accounts/', include('allauth.urls')),
]

# Esto es importante para que las miniaturas (thumbnails) se muestren en el modo de desarrollo
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    from django.views.static import serve
    from django.urls import re_path
    
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
        re_path(r'^static/(?P<path>.*)$', serve, {'document_root': settings.STATIC_ROOT}),
    ]
