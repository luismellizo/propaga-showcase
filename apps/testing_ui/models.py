from django.db import models
from django.utils import timezone

class TestResult(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pendiente'),
        ('RUNNING', 'Ejecutando...'),
        ('PASSED', 'Pasó Exitosamente'),
        ('FAILED', 'Falló'),
    ]

    name = models.CharField(max_length=255, verbose_name="Nombre del Test")
    script_path = models.CharField(max_length=512, verbose_name="Ruta del Script", help_text="Ruta relativa desde la raíz del proyecto, ej: testing/test_01_auth.py")
    description = models.TextField(blank=True, verbose_name="Descripción")
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='PENDING', verbose_name="Estado")
    output_log = models.TextField(blank=True, verbose_name="Logs de Ejecución")
    executed_at = models.DateTimeField(null=True, blank=True, verbose_name="Última Ejecución")
    duration = models.FloatField(default=0.0, verbose_name="Duración (s)")

    class Meta:
        verbose_name = "Prueba del Sistema"
        verbose_name_plural = "Pruebas del Sistema"
        ordering = ['name']

    def __str__(self):
        return f"{self.name} - {self.get_status_display()}"

class TestExecution(models.Model):
    test_result = models.ForeignKey(TestResult, on_delete=models.CASCADE, related_name='executions', verbose_name="Test Relacionado")
    status = models.CharField(max_length=50, choices=TestResult.STATUS_CHOICES, verbose_name="Estado")
    output_log = models.TextField(blank=True, verbose_name="Logs de Ejecución")
    executed_at = models.DateTimeField(default=timezone.now, verbose_name="Fecha de Ejecución")
    duration = models.FloatField(default=0.0, verbose_name="Duración (s)")

    class Meta:
        verbose_name = "Ejecución Histórica"
        verbose_name_plural = "Historial de Ejecuciones"
        ordering = ['-executed_at']

    def __str__(self):
        return f"{self.test_result.name} @ {self.executed_at.strftime('%Y-%m-%d %H:%M:%S')}"
