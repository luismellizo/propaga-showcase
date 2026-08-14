# =============================================================================
# PROPAGA - Dockerfile Ligero (Sin PyTorch/Whisper)
# =============================================================================
# Usa APIs cloud (Groq) para transcripción en lugar de Whisper local.
# Imagen final ~500MB vs ~5GB con PyTorch.
# =============================================================================

# -----------------------------------------------------------------------------
# STAGE 0: Tailwind Builder - Compila CSS de utilidades (sin CDN en runtime)
# -----------------------------------------------------------------------------
FROM alpine:3.20 AS tailwind-builder

RUN apk add --no-cache curl

RUN curl -sLo /usr/local/bin/tailwindcss \
    https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.19/tailwindcss-linux-x64 \
    && chmod +x /usr/local/bin/tailwindcss

WORKDIR /build
COPY tailwind.config.js .
COPY static/css/tailwind-input.css static/css/tailwind-input.css
COPY templates templates
COPY apps apps

RUN tailwindcss -c tailwind.config.js -i static/css/tailwind-input.css -o static/css/tailwind-built.css --minify

# -----------------------------------------------------------------------------
# STAGE 1: Builder - Compilación de dependencias
# -----------------------------------------------------------------------------
FROM python:3.11-slim as builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Instalar dependencias del sistema para compilación
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# Crear virtualenv
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Actualizar pip
RUN pip install --upgrade pip wheel setuptools

# Copiar e instalar requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# -----------------------------------------------------------------------------
# STAGE 2: Runtime - Imagen final optimizada
# -----------------------------------------------------------------------------
FROM python:3.11-slim as runtime

LABEL org.opencontainers.image.source="https://github.com/luismellizo/propaga-showcase"
LABEL org.opencontainers.image.description="PROPAGA - Automatización de publicaciones"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_HOME=/app \
    PATH="/opt/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings

WORKDIR $APP_HOME

# Instalar dependencias del sistema para runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 propaga \
    && useradd --uid 1000 --gid propaga --shell /bin/bash --create-home propaga

# Copiar virtualenv desde builder
COPY --from=builder /opt/venv /opt/venv

# Copiar código de la aplicación
COPY --chown=propaga:propaga . .

# CSS de Tailwind ya compilado (pisa cualquier copia local del build anterior)
COPY --from=tailwind-builder --chown=propaga:propaga /build/static/css/tailwind-built.css static/css/tailwind-built.css

# Crear directorios necesarios
RUN mkdir -p staticfiles media logs \
    && chown -R propaga:propaga staticfiles media logs

# Configurar entrypoint
COPY --chown=propaga:propaga scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Usuario no-root
USER propaga

EXPOSE 8000

# El healthcheck depende del rol: el worker de Celery no escucha ningun puerto,
# asi que un curl al endpoint HTTP lo marcaria unhealthy siempre y Coolify
# abortaria el deploy. Para el worker se pregunta al propio Celery via broker.
HEALTHCHECK --interval=30s --timeout=15s --start-period=90s --retries=3 \
    CMD sh -c 'case "$PROPAGA_ROLE" in \
        celery-worker) celery -A config inspect ping -t 10 >/dev/null 2>&1 || exit 1 ;; \
        "") curl -f http://localhost:8000/health/ || exit 1 ;; \
        *) exit 0 ;; \
    esac'

ENTRYPOINT ["/entrypoint.sh"]

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "--worker-class", "gthread", "--timeout", "120", "config.wsgi:application"]
