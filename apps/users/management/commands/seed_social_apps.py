"""
Carga en la DB las SocialApp de allauth a partir de las credenciales del .env.

Idempotente: si la SocialApp ya existe, actualiza client_id/secret y se asegura
de que el Site de `SITE_ID` esté asociado (sin Site asociado allauth NO muestra
el proveedor en el login y no lanza ningún error visible).

Los providers sin credenciales en el entorno se omiten — nunca se borra nada.

    python manage.py seed_social_apps
    python manage.py seed_social_apps --provider google
"""
from allauth.socialaccount.models import SocialApp
from django.conf import settings
from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand


def mask(value):
    return f"…{value[-6:]}" if value and len(value) > 6 else '(vacío)'


class Command(BaseCommand):
    help = 'Crea o actualiza las SocialApp de allauth con las credenciales OAuth del .env.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--provider',
            help='Procesar solo este proveedor (google, facebook, twitter, tiktok).',
        )

    def handle(self, *args, **options):
        try:
            site = Site.objects.get(pk=settings.SITE_ID)
        except Site.DoesNotExist:
            self.stderr.write(self.style.ERROR(
                f'No existe el Site con pk={settings.SITE_ID}. Creálo en el admin antes de seguir.'
            ))
            return

        self.stdout.write(f'Site activo: {site.domain} (pk={site.pk})')

        credenciales = settings.SOCIAL_OAUTH_CREDENTIALS
        solo = options.get('provider')
        if solo:
            if solo not in credenciales:
                self.stderr.write(self.style.ERROR(
                    f"Proveedor '{solo}' desconocido. Opciones: {', '.join(credenciales)}"
                ))
                return
            credenciales = {solo: credenciales[solo]}

        for provider, meta in credenciales.items():
            client_id = (meta.get('client_id') or '').strip()
            secret = (meta.get('secret') or '').strip()

            if not client_id:
                self.stdout.write(self.style.WARNING(
                    f'{provider}: sin credenciales en el entorno — se omite.'
                ))
                continue

            app = SocialApp.objects.filter(provider=provider).first()
            if app is None:
                app = SocialApp(provider=provider, name=meta['name'])
                accion = 'creada'
            else:
                accion = 'actualizada'

            app.name = app.name or meta['name']
            app.client_id = client_id
            app.secret = secret
            app.save()

            if not app.sites.filter(pk=site.pk).exists():
                app.sites.add(site)
                self.stdout.write(f'  → Site {site.domain} asociado.')

            self.stdout.write(self.style.SUCCESS(
                f'{provider}: SocialApp {accion} (client_id {mask(client_id)}, secret {mask(secret)}).'
            ))
            self.stdout.write(
                f'  Redirect URI: https://{site.domain}/accounts/{provider}/login/callback/'
            )
