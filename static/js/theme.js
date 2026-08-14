// PROPAGA — Toggle de tema con View Transitions API.
// Círculo expansivo desde el botón pulsado (Web Animations sobre ::view-transition-new).
// Fallback: cambio instantáneo si el navegador no soporta startViewTransition.
(function () {
    'use strict';

    function switchTheme() {
        const root = document.documentElement;
        const isDark = root.classList.toggle('dark');
        try {
            localStorage.theme = isDark ? 'dark' : 'light';
        } catch (e) { /* almacenamiento no disponible */ }
    }

    function toggleTheme(event) {
        const root = document.documentElement;

        if (!document.startViewTransition) {
            switchTheme();
            return;
        }

        // Origen del círculo: centro del botón pulsado (o centro superior de la pantalla)
        let x = window.innerWidth / 2;
        let y = 0;
        const btn = event && event.currentTarget;
        if (btn && btn.getBoundingClientRect) {
            const r = btn.getBoundingClientRect();
            x = r.left + r.width / 2;
            y = r.top + r.height / 2;
        }
        const endRadius = Math.hypot(
            Math.max(x, window.innerWidth - x),
            Math.max(y, window.innerHeight - y)
        );

        // Sin transiciones de color individuales durante el snapshot
        root.classList.add('no-transitions');

        const vt = document.startViewTransition(switchTheme);

        vt.ready.then(function () {
            root.animate(
                {
                    clipPath: [
                        'circle(0px at ' + x + 'px ' + y + 'px)',
                        'circle(' + endRadius + 'px at ' + x + 'px ' + y + 'px)'
                    ]
                },
                {
                    duration: 650,
                    easing: 'cubic-bezier(0.4, 0, 0.2, 1)',
                    pseudoElement: '::view-transition-new(root)'
                }
            );
        }).catch(function () { /* transición cancelada: sin problema */ });

        vt.finished.finally(function () {
            root.classList.remove('no-transitions');
        });
    }

    function bind() {
        document.querySelectorAll('[data-theme-toggle]').forEach(function (btn) {
            if (btn.dataset.themeBound) return;
            btn.dataset.themeBound = '1';
            btn.addEventListener('click', toggleTheme);
        });
    }

    // --- Elevación al hacer scroll ---
    // En M3 la barra superior no gana sombra: sube de TONO (`.scrolled` la pasa a
    // surface-container). Cubre también la isla del landing, que usa la misma clase.
    function bindScrollElevation() {
        document.querySelectorAll('#nav-island, .app-topbar').forEach(function (bar) {
            if (bar.dataset.scrollBound) return;
            bar.dataset.scrollBound = '1';
            const onScroll = function () {
                bar.classList.toggle('scrolled', window.scrollY > 4);
            };
            window.addEventListener('scroll', onScroll, { passive: true });
            onScroll();
        });
    }

    // --- Reveal al hacer scroll ---
    let revealObserver = null;

    function bindReveals() {
        if (!('IntersectionObserver' in window)) {
            document.querySelectorAll('.reveal').forEach(function (el) {
                el.classList.add('visible');
            });
            return;
        }
        if (!revealObserver) {
            revealObserver = new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    if (entry.isIntersecting) {
                        entry.target.classList.add('visible');
                        revealObserver.unobserve(entry.target);
                    }
                });
            }, { threshold: 0.12 });
        }
        document.querySelectorAll('.reveal:not(.visible)').forEach(function (el) {
            revealObserver.observe(el);
        });
    }

    function init() {
        bind();
        bindScrollElevation();
        bindReveals();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Re-vincular tras swaps de HTMX (parciales que incluyan toggle o reveals)
    document.body && document.body.addEventListener('htmx:afterSwap', init);

    window.propagaToggleTheme = toggleTheme;
})();
