/** @type {import('tailwindcss').Config} */

/* Los valores NO viven aquí: viven en static/css/tokens.css. Este archivo solo
   expone esos roles como utilidades para poder escribir `bg-surface-container`
   o `text-on-surface-variant` en los templates y no volver a un `style="..."`.

   Ojo con los nombres de forma: se usa el prefijo `shape-` (`rounded-shape-lg`)
   a propósito. Pisar `rounded-lg`/`rounded-xl` de Tailwind habría reformado en
   silencio el landing, que está fuera de alcance. */

module.exports = {
    content: [
        './templates/**/*.html',
        './apps/**/templates/**/*.html',
    ],
    darkMode: 'class',
    theme: {
        extend: {
            fontFamily: {
                sans: ['Roboto Flex', 'Roboto', 'system-ui', 'sans-serif'],
                display: ['Roboto Flex', 'Roboto', 'system-ui', 'sans-serif'],
            },

            /* Escala tipográfica corta. Tamaño + interlineado + peso van juntos:
               si el tamaño se elige de aquí, el peso ya viene decidido (400/500). */
            fontSize: {
                'display': ['var(--type-display-size)', { lineHeight: 'var(--type-display-line)', letterSpacing: '-0.02em', fontWeight: '400' }],
                'headline': ['var(--type-headline-size)', { lineHeight: 'var(--type-headline-line)', letterSpacing: '-0.01em', fontWeight: '400' }],
                'title-lg': ['var(--type-title-lg-size)', { lineHeight: 'var(--type-title-lg-line)', fontWeight: '400' }],
                'title': ['var(--type-title-size)', { lineHeight: 'var(--type-title-line)', letterSpacing: '0.009em', fontWeight: '500' }],
                'body-lg': ['var(--type-body-lg-size)', { lineHeight: 'var(--type-body-lg-line)', letterSpacing: '0.03em', fontWeight: '400' }],
                'body': ['var(--type-body-size)', { lineHeight: 'var(--type-body-line)', letterSpacing: '0.017em', fontWeight: '400' }],
                'body-sm': ['var(--type-body-sm-size)', { lineHeight: 'var(--type-body-sm-line)', letterSpacing: '0.03em', fontWeight: '400' }],
                'label-lg': ['var(--type-label-lg-size)', { lineHeight: 'var(--type-label-lg-line)', letterSpacing: '0.007em', fontWeight: '500' }],
                'label': ['var(--type-label-size)', { lineHeight: 'var(--type-label-line)', letterSpacing: '0.04em', fontWeight: '500' }],
                'label-sm': ['var(--type-label-sm-size)', { lineHeight: 'var(--type-label-sm-line)', letterSpacing: '0.04em', fontWeight: '500' }],
            },

            borderRadius: {
                'shape-none': 'var(--shape-none)',
                'shape-xs': 'var(--shape-xs)',
                'shape-sm': 'var(--shape-sm)',
                'shape-md': 'var(--shape-md)',
                'shape-lg': 'var(--shape-lg)',
                'shape-xl': 'var(--shape-xl)',
                'shape-full': 'var(--shape-full)',
            },

            colors: {
                /* Roles de M3. Se nombran igual que en la especificación para que
                   `bg-primary-container` / `text-on-primary-container` sean pares
                   obvios y nadie tenga que adivinar el color de contenido. */
                'primary': 'var(--m3-primary)',
                'on-primary': 'var(--m3-on-primary)',
                'primary-container': 'var(--m3-primary-container)',
                'on-primary-container': 'var(--m3-on-primary-container)',

                'secondary': 'var(--m3-secondary)',
                'on-secondary': 'var(--m3-on-secondary)',
                'secondary-container': 'var(--m3-secondary-container)',
                'on-secondary-container': 'var(--m3-on-secondary-container)',

                'tertiary': 'var(--m3-tertiary)',
                'on-tertiary': 'var(--m3-on-tertiary)',
                'tertiary-container': 'var(--m3-tertiary-container)',
                'on-tertiary-container': 'var(--m3-on-tertiary-container)',

                'danger': 'var(--m3-error)',
                'on-danger': 'var(--m3-on-error)',
                'danger-container': 'var(--m3-error-container)',
                'on-danger-container': 'var(--m3-on-error-container)',

                'warning': 'var(--m3-warning)',
                'on-warning': 'var(--m3-on-warning)',
                'warning-container': 'var(--m3-warning-container)',
                'on-warning-container': 'var(--m3-on-warning-container)',

                'info': 'var(--m3-info)',
                'on-info': 'var(--m3-on-info)',
                'info-container': 'var(--m3-info-container)',
                'on-info-container': 'var(--m3-on-info-container)',

                'violet': 'var(--m3-violet)',
                'on-violet': 'var(--m3-on-violet)',
                'violet-container': 'var(--m3-violet-container)',
                'on-violet-container': 'var(--m3-on-violet-container)',

                'surface': {
                    DEFAULT: 'var(--m3-surface)',
                    dim: 'var(--m3-surface-dim)',
                    bright: 'var(--m3-surface-bright)',
                    lowest: 'var(--m3-surface-container-lowest)',
                    low: 'var(--m3-surface-container-low)',
                    container: 'var(--m3-surface-container)',
                    high: 'var(--m3-surface-container-high)',
                    highest: 'var(--m3-surface-container-highest)',
                    /* alias legibles: bg-surface-container-high */
                    'container-lowest': 'var(--m3-surface-container-lowest)',
                    'container-low': 'var(--m3-surface-container-low)',
                    'container-high': 'var(--m3-surface-container-high)',
                    'container-highest': 'var(--m3-surface-container-highest)',
                },
                'on-surface': {
                    DEFAULT: 'var(--m3-on-surface)',
                    variant: 'var(--m3-on-surface-variant)',
                    muted: 'var(--m3-on-surface-muted)',
                },
                'outline': {
                    DEFAULT: 'var(--m3-outline)',
                    variant: 'var(--m3-outline-variant)',
                },
                'inverse-surface': 'var(--m3-inverse-surface)',
                'inverse-on-surface': 'var(--m3-inverse-on-surface)',
                'inverse-primary': 'var(--m3-inverse-primary)',
                'scrim': 'var(--m3-scrim)',

                /* Marca de terceros (logotipos, no interfaz) */
                'net-facebook': 'var(--brand-facebook)',
                'net-youtube': 'var(--brand-youtube)',
                'net-instagram': 'var(--brand-instagram)',
                'net-tiktok': 'var(--brand-tiktok)',

                /* El landing (fuera de alcance) sigue usando `brand-500`, etc. */
                brand: {
                    50: '#ecfdf5', 100: '#d1fae5', 200: '#a7f3d0', 300: '#6ee7b7',
                    400: '#34d399', 500: '#10b981', 600: '#059669', 700: '#047857',
                    800: '#065f46', 900: '#064e3b', 950: '#022c22',
                },
            },

            spacing: {
                'rail': 'var(--rail-width)',
                'topbar': 'var(--topbar-height)',
                'bottombar': 'var(--bottombar-height)',
            },

            maxWidth: {
                'content': 'var(--content-max)',
                'content-wide': 'var(--content-wide)',
            },

            transitionTimingFunction: {
                'standard': 'var(--ease-standard)',
                'decelerate': 'var(--ease-decelerate)',
                'accelerate': 'var(--ease-accelerate)',
                'emphasized': 'var(--ease-emphasized)',
            },

            transitionDuration: {
                'short': 'var(--dur-short)',
                'medium': 'var(--dur-medium)',
                'long': 'var(--dur-long)',
            },

            boxShadow: {
                'elev-1': 'var(--elev-1)',
                'elev-2': 'var(--elev-2)',
                'elev-3': 'var(--elev-3)',
            },
        },
    },
    plugins: [],
}
