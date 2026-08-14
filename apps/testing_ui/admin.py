"""
Panel de tests dentro del admin.

⚠️  Este módulo ejecuta procesos en el servidor. Todo lo que hay aquí está
construido alrededor de esa única frase.

El diseño ingenuo —tomar `TestResult.script_path` y pasárselo a `python`— le
regala ejecución de código a cualquier cuenta con permiso de staff sobre este
modelo: basta con apuntar el campo a otro archivo. Y si el disparo va por GET,
además es accionable con un enlace.

Las tres barreras, en orden:

  1. `script_path` NO es editable desde el formulario. Se siembra con el
     comando `init_tests` y el admin solo lo muestra.
  2. `_ruta_permitida()` resuelve la ruta y verifica que caiga dentro de
     `testing/` y termine en `.py`. Resolver primero es lo que ataja
     `../../etc/…`: comparar cadenas sin resolver no sirve de nada.
  3. La ejecución exige POST. El botón "Correr test" es un formulario con
     token CSRF, no un `<a href>`.

Ninguna de las tres alcanza sola.
"""
import os
import subprocess
import sys
import time

from django.contrib import admin, messages
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import action

from .models import TestResult, TestExecution

# Único directorio desde el que se puede ejecutar algo.
RAIZ_PROYECTO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIRECTORIO_TESTS = os.path.join(RAIZ_PROYECTO, 'testing')


def _ruta_permitida(script_path):
    """Devuelve la ruta absoluta si está dentro de `testing/` y es .py; si no, None.

    `os.path.realpath` resuelve `..` y los symlinks ANTES de comparar. Sin ese
    paso, un `testing/../../../etc/x.py` pasaría un `startswith` sobre la cadena
    cruda. El `os.sep` final evita que un directorio hermano llamado
    `testing_malicioso/` cuele por prefijo.
    """
    if not script_path or not script_path.endswith('.py'):
        return None

    candidato = os.path.realpath(os.path.join(RAIZ_PROYECTO, script_path))
    raiz = os.path.realpath(DIRECTORIO_TESTS)

    if not candidato.startswith(raiz + os.sep):
        return None
    if not os.path.isfile(candidato):
        return None
    return candidato

class TestExecutionInline(TabularInline):
    model = TestExecution
    extra = 0
    readonly_fields = ['status', 'executed_at', 'duration', 'output_log_formatted_inline']
    exclude = ['output_log']
    can_delete = False
    
    def output_log_formatted_inline(self, obj):
        if not obj.output_log: return "Sin logs"
        # Truncate for inline view
        preview = obj.output_log[:200] + "..." if len(obj.output_log) > 200 else obj.output_log
        return format_html(
             '<div title="{}">{} <br/ ><span class="text-xs text-gray-500">(Ver detalle en objeto)</span></div>',
             obj.output_log, preview
        )
    output_log_formatted_inline.short_description = "Log Preview"


@admin.register(TestResult)
class TestResultAdmin(ModelAdmin):
    list_display = ['name', 'display_status', 'last_run_formatted', 'actions_display']
    list_filter = ['status']
    search_fields = ['name', 'description']
    actions = ['run_selected_tests']
    # `script_path` es de solo lectura a propósito: es lo que se le pasa a un
    # intérprete. Se siembra con `manage.py init_tests`, no se escribe por web.
    readonly_fields = ['output_log_formatted', 'executed_at', 'duration', 'script_path']
    inlines = [TestExecutionInline]

    fieldsets = (
        (None, {
            'fields': ('name', 'description', 'script_path')
        }),
        ('Estado de Ejecución', {
            'fields': ('status', 'executed_at', 'duration'),
            'classes': ('collapse', 'open')
        }),
        ('Logs', {
            'fields': ('output_log_formatted',),
            'classes': ('collapse', 'open')
        }),
    )

    def display_status(self, obj):
        colors = {
            'PENDING': 'gray',
            'RUNNING': 'yellow',
            'PASSED': 'green',
            'FAILED': 'red',
        }
        color = colors.get(obj.status, 'gray')
        
        # Unfold badges compatibility implies usually returning a dictionary or specialized HTML
        # For simplicity and robust visual, we use standard HTML with Tailwind classes if strictly supported inside Unfold specific calls, 
        # or Unfold's badge format if available via display decoration.
        # Unfold usually supports:
        return format_html(
            '<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-{}-100 text-{}-800">{}</span>',
            color, color, obj.get_status_display()
        )
    display_status.short_description = "Estado"
    
    # Use Unfold's badge support if preferred over custom HTML, but Custom HTML is more flexible for "Bombillos".
    # Let's try to mimic a "Light Bulb" effect.
    def display_status(self, obj):
        color_map = {
            'PASSED': 'bg-green-500',
            'FAILED': 'bg-red-500',
            'RUNNING': 'bg-yellow-500 animate-pulse',
            'PENDING': 'bg-gray-300'
        }
        c = color_map.get(obj.status, 'bg-gray-300')
        return format_html(
            '<div class="flex items-center space-x-2">'
            '<div class="w-4 h-4 rounded-full shadow-md {} border border-white"></div>'
            '<span class="font-medium">{}</span>'
            '</div>',
            c, obj.get_status_display()
        )
    display_status.short_description = "Estado Visual"

    def last_run_formatted(self, obj):
        if not obj.executed_at:
            return "-"
        return obj.executed_at.strftime("%Y-%m-%d %H:%M:%S")
    last_run_formatted.short_description = "Última Ejecución"

    def output_log_formatted(self, obj):
        if not obj.output_log:
            return "Sin logs"
        # Render logs in a code block
        return format_html(
            '<pre class="bg-gray-900 text-green-400 p-4 rounded-lg overflow-x-auto text-xs font-mono">{}</pre>',
            obj.output_log
        )
    output_log_formatted.short_description = "Terminal Output"

    # Botón "Correr test" en la página de detalle. Es un submit dentro del
    # formulario del admin, así que hereda el {% csrf_token %} de Django.
    change_form_template = 'admin/testing_ui/testresult/change_form.html'

    def actions_display(self, obj):
        """Enlace a la página del test. NO ejecuta nada.

        Antes era `<a href="?run_test=1">` y `change_view` lo obedecía: bastaba
        con que un staff abriera esa URL —desde un correo, desde otra pestaña—
        para lanzar un proceso en el servidor. Un GET no puede tener efectos
        secundarios; la ejecución vive en el POST del detalle y en la acción
        masiva, que Django ya protege con CSRF.
        """
        return format_html(
            '<a class="button px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 transition" '
            'href="{}">Abrir</a>',
            reverse('admin:testing_ui_testresult_change', args=[obj.pk]),
        )
    actions_display.short_description = "Acciones"

    @action(description="Ejecutar Tests Seleccionados")
    def run_selected_tests(self, request, queryset):
        """Acción del admin: ya llega por POST y con CSRF validado por Django."""
        for test in queryset:
            self._execute_test(test)
        self.message_user(request, "Tests ejecutados. Revisa los resultados.", messages.SUCCESS)

    def change_view(self, request, object_id, form_url='', extra_context=None):
        # Solo POST. Antes esto miraba request.GET.
        if request.method == 'POST' and request.POST.get('_run_test') == '1':
            obj = self.get_object(request, object_id)
            if obj:
                self._execute_test(obj)
                self.message_user(request, f"Test '{obj.name}' ejecutado.", messages.SUCCESS)
            from django.http import HttpResponseRedirect
            return HttpResponseRedirect(request.path)
        return super().change_view(request, object_id, form_url, extra_context)

    def _execute_test(self, test_obj):
        test_obj.status = 'RUNNING'
        test_obj.save()
        
        start_time = time.time()

        # La validación va acá y no solo en el formulario: este método lo llaman
        # la acción masiva, el botón individual y cualquier código futuro. La
        # barrera tiene que estar en el punto de ejecución, no en la entrada.
        script_path = _ruta_permitida(test_obj.script_path)
        if script_path is None:
            test_obj.status = 'FAILED'
            test_obj.output_log = (
                f"Ruta rechazada: '{test_obj.script_path}'. Solo se ejecutan "
                f"archivos .py existentes dentro de testing/."
            )
            test_obj.executed_at = timezone.now()
            test_obj.save()
            return

        try:
            # CWD en la raíz: los scripts hacen `from utils import ...` y esperan
            # ser invocados como `python testing/script.py` desde el proyecto.
            env = os.environ.copy()
            env['PYTHONPATH'] = RAIZ_PROYECTO + os.pathsep + env.get('PYTHONPATH', '')

            result = subprocess.run(
                [sys.executable, script_path],
                cwd=RAIZ_PROYECTO,
                capture_output=True,
                text=True,
                # Un test colgado no puede dejar un proceso vivo para siempre en
                # el contenedor, ocupando memoria sin que nadie lo mire.
                timeout=600,
            )

            duration = time.time() - start_time
            test_obj.duration = round(duration, 2)
            
            # Capture combined output
            full_log = f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"
            test_obj.output_log = full_log
            
            if result.returncode == 0:
                test_obj.status = 'PASSED'
            else:
                test_obj.status = 'FAILED'
                
        except subprocess.TimeoutExpired:
            test_obj.status = 'FAILED'
            test_obj.duration = round(time.time() - start_time, 2)
            test_obj.output_log = "El test superó el límite de 600s y fue abortado."

        except Exception as e:
            test_obj.status = 'FAILED'
            test_obj.output_log = f"Exception running script: {str(e)}"

        test_obj.executed_at = timezone.now()
        test_obj.save()
        
        # Save historical execution
        TestExecution.objects.create(
            test_result=test_obj,
            status=test_obj.status,
            output_log=test_obj.output_log,
            executed_at=test_obj.executed_at,
            duration=test_obj.duration
        )
