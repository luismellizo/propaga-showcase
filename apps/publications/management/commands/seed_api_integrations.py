"""
Migra las API keys actuales (variables de entorno) al modelo APIIntegration.

Idempotente: no sobreescribe keys ya guardadas en DB. Las env vars siguen
funcionando como fallback — este seed solo copia su valor a la DB cifrado.
"""
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.publications.integrations import PROVIDERS, encrypt_key, mask_key, test_connection
from apps.publications.models import APIIntegration


class Command(BaseCommand):
    help = 'Copia las API keys de las variables de entorno a la DB (cifradas) y prueba la conexión.'

    def handle(self, *args, **options):
        for provider, meta in PROVIDERS.items():
            env_key = getattr(settings, meta['env_setting'], '') or ''
            integration, created = APIIntegration.objects.get_or_create(
                provider=provider,
                defaults={'model_name': meta['default_model']},
            )

            if integration.api_key_encrypted:
                self.stdout.write(f"{meta['label']}: ya tiene key en DB ({integration.masked_key}) — no se toca.")
            elif env_key:
                integration.api_key_encrypted = encrypt_key(env_key)
                self.stdout.write(f"{meta['label']}: key de entorno copiada a DB ({mask_key(env_key)}).")
            else:
                self.stdout.write(self.style.WARNING(f"{meta['label']}: sin key en entorno ni DB."))

            if not integration.model_name:
                integration.model_name = meta['default_model']

            # Prueba de conexión con la key efectiva
            from apps.publications.integrations import get_provider_config
            integration.save()
            api_key, model_name = get_provider_config(provider)
            ok, detail = test_connection(provider, api_key, model_name)
            integration.status = 'active' if ok else ('invalid' if integration.api_key_encrypted else 'unconfigured')
            integration.last_tested_at = timezone.now()
            integration.save()

            style = self.style.SUCCESS if ok else self.style.ERROR
            self.stdout.write(style(f"  → Test: {detail}"))
