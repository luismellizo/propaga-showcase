# apps/publications/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.cache import cache
from .models import Publication
from .tasks import process_publication
import logging

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Publication)
def launch_publication_processing(sender, instance, created, **kwargs):
    """
    Versión mejorada que evita disparos duplicados
    """
    if created:
        # 🔒 Lock para evitar que se dispare múltiples veces
        lock_key = f'signal_lock_{instance.id}'
        
        # Si ya existe el lock, no hacer nada
        if cache.get(lock_key):
            logger.warning(f"Señal ya procesada para ID: {instance.id}")
            return
        
        # Establecer lock por 30 segundos
        cache.set(lock_key, True, timeout=30)
        
        logger.info(f"🚀 SEÑAL ACTIVADA para ID: {instance.id}. Lanzando a Celery...")
        process_publication.delay(instance.id)