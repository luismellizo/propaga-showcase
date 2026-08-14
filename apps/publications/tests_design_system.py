"""Guardias del sistema de diseño.

No prueban comportamiento: prueban que el rediseño a Material 3 no se erosione.
Cada uno de estos tests existe porque el fallo que vigila YA ocurrió en este
repositorio (ver APP/design-audit.md).

    python manage.py test apps.publications.tests_design_system
"""
from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.template import TemplateSyntaxError
from django.template.loader import get_template
from django.test import SimpleTestCase

APP_DIR = Path(settings.BASE_DIR)

# Raíces de plantillas del proyecto.
TEMPLATE_ROOTS = [
    APP_DIR / "templates",
    APP_DIR / "apps" / "publications" / "templates",
]

# El landing tiene identidad propia y conserva Phosphor + los efectos de
# marketing; está fuera del alcance del rediseño (ver design-audit.md).
OUT_OF_SCOPE = {"pages/welcome.html"}


def iter_templates():
    """(nombre relativo para el loader, Path) de cada plantilla del proyecto."""
    for root in TEMPLATE_ROOTS:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.html")):
            yield path.relative_to(root).as_posix(), path


def panel_templates():
    return [(name, path) for name, path in iter_templates() if name not in OUT_OF_SCOPE]


class TemplatesCompilanTest(SimpleTestCase):
    def test_todas_las_plantillas_compilan(self):
        """`_publication_status.html` llevaba un {% if %} partido en dos líneas y
        no compilaba; nadie se enteró porque ninguna vista lo renderizaba."""
        errores = []
        for name, _ in iter_templates():
            try:
                get_template(name)
            except TemplateSyntaxError as exc:
                errores.append(f"{name}: {exc}")
        self.assertEqual(errores, [], "Plantillas que no compilan:\n" + "\n".join(errores))


class ComentariosDePlantillaTest(SimpleTestCase):
    def test_ningun_comentario_abarca_varias_lineas(self):
        """{# … #} de Django NO puede abarcar varias líneas: el lexer no lo
        reconoce y lo escupe tal cual en el HTML. Llegó a producción seis veces.
        Para varias líneas va {% comment %}."""
        malos = []
        for name, path in iter_templates():
            src = path.read_text(encoding="utf-8")
            for match in re.finditer(r"\{#", src):
                fin = src.find("#}", match.start())
                cuerpo = src[match.start(): fin] if fin != -1 else src[match.start():]
                if "\n" in cuerpo:
                    linea = src[: match.start()].count("\n") + 1
                    malos.append(f"{name}:{linea}")
        self.assertEqual(
            malos, [],
            "Comentarios {# #} multilínea (se imprimen en el HTML): " + ", ".join(malos),
        )


class ColoresFueraDeTokensTest(SimpleTestCase):
    # Hex crudo en un atributo class o style. Se permite dentro de <svg> porque
    # los logotipos de terceros son marca, no interfaz (WCAG los exime).
    HEX = re.compile(r'(?:class|style)="[^"]*#[0-9a-fA-F]{3,8}\b')

    # Paletas crudas de Tailwind: el color debe salir de un rol de tokens.css.
    PALETA = re.compile(
        r"\b(?:!?(?:bg|text|border|ring|from|via|to|accent|fill|stroke|decoration)-"
        r"(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|"
        r"teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3})\b"
    )

    def test_el_panel_no_escribe_hex_en_class_ni_style(self):
        malos = []
        for name, path in panel_templates():
            for linea_n, linea in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if self.HEX.search(linea):
                    malos.append(f"{name}:{linea_n}")
        self.assertEqual(
            malos, [],
            "Hex fuera de tokens.css (usa un rol de M3): " + ", ".join(malos),
        )

    def test_el_panel_no_usa_paletas_crudas_de_tailwind(self):
        malos = []
        for name, path in panel_templates():
            for linea_n, linea in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                encontrado = self.PALETA.search(linea)
                if encontrado:
                    malos.append(f"{name}:{linea_n} ({encontrado.group(0)})")
        self.assertEqual(
            malos, [],
            "Colores crudos de Tailwind (usa bg-primary-container, text-danger…): "
            + ", ".join(malos),
        )

    def test_los_widgets_de_forms_no_traen_color(self):
        """El file input llevaba `file:bg-emerald-100 dark:file:bg-emerald-900/40`
        dentro de Python: imposible de retematizar y fuera de los tokens."""
        src = (APP_DIR / "apps" / "publications" / "forms.py").read_text(encoding="utf-8")
        encontrado = self.PALETA.search(src)
        self.assertIsNone(
            encontrado,
            f"forms.py define color crudo: {encontrado.group(0) if encontrado else ''}",
        )


class TipografiaTest(SimpleTestCase):
    PESOS = re.compile(r"\bfont-(?:bold|semibold|extrabold|black)\b")

    def test_el_panel_no_usa_pesos_mayores_a_500(self):
        """La jerarquía la dan el tamaño y el color. El panel corre en 400 y 500."""
        malos = []
        for name, path in panel_templates():
            for linea_n, linea in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if self.PESOS.search(linea):
                    malos.append(f"{name}:{linea_n}")
        self.assertEqual(
            malos, [],
            "font-bold/semibold/extrabold/black en el panel: " + ", ".join(malos),
        )


class IconografiaTest(SimpleTestCase):
    PHOSPHOR = re.compile(r'class="[^"]*\bph(?:-bold|-fill)?\s+ph-')

    def test_el_panel_usa_un_solo_set_de_iconos(self):
        malos = []
        for name, path in panel_templates():
            if self.PHOSPHOR.search(path.read_text(encoding="utf-8")):
                malos.append(name)
        self.assertEqual(
            malos, [],
            "Phosphor en el panel (usa Material Symbols): " + ", ".join(malos),
        )

    def test_los_iconos_usados_estan_en_el_subconjunto_de_la_fuente(self):
        """Material Symbols se carga subseteado con `icon_names`. Un icono que no
        esté en esa lista no se descarga y se renderiza como TEXTO literal."""
        base = (APP_DIR / "templates" / "base.html").read_text(encoding="utf-8")
        match = re.search(r"icon_names=([a-z_,0-9]+)", base)
        self.assertIsNotNone(match, "base.html ya no declara icon_names")
        declarados = set(match.group(1).split(","))

        usados: set[str] = set()
        patron = re.compile(
            r'<span class="material-symbols-outlined[^"]*"[^>]*>\s*([a-z_0-9]+)\s*</span>'
        )
        for _, path in panel_templates():
            usados.update(patron.findall(path.read_text(encoding="utf-8")))

        # Los iconos de los pasos del worker viven en el modelo.
        from .models import Publication
        usados.update(icono for _, _, icono in Publication.PROCESSING_STEPS)
        usados.update(paso[2] for paso in Publication.PUBLISHING_PROVIDER_STEPS.values())
        usados.add(Publication.INSTAGRAM_STEP[2])

        faltantes = sorted(usados - declarados)
        self.assertEqual(
            faltantes, [],
            "Iconos usados que no están en icon_names de base.html: " + ", ".join(faltantes),
        )
