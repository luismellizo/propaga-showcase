#!/bin/bash
# =============================================================================
# PROPAGA - Entrypoint Script
# =============================================================================
# Este script se ejecuta al iniciar el contenedor.
# Maneja migraciones, archivos estáticos y diferentes modos de ejecución.
# =============================================================================

set -e

# Asegurar que el virtualenv esté en el PATH
export PATH="/opt/venv/bin:$PATH"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Sin `set -x`: el trace de bash imprimiría cada expansión de variable en los
# logs del contenedor, y por ahí pasan DB_PASSWORD y las URLs del broker.

echo -e "${GREEN}========================================${NC}"
echo "FECHA: $(date)"
echo "USUARIO: $(whoami)"
echo "PWD: $(pwd)"
echo "ARGUMENTOS: $@"
echo -e "${GREEN}  PROPAGA - Iniciando Servicio${NC}"
echo -e "${GREEN}========================================${NC}"

# -----------------------------------------------------------------------------
# Función para esperar a que la base de datos esté lista
# -----------------------------------------------------------------------------
wait_for_db() {
    echo -e "${YELLOW}Esperando a que PostgreSQL esté disponible...${NC}"
    echo -e "${YELLOW}DB_HOST: $DB_HOST | DB_PORT: $DB_PORT | DB_NAME: $DB_NAME | DB_USER: $DB_USER${NC}"
    
    # Intentar conexión por máximo 30 segundos
    for i in {1..30}; do
        CONNECTION_RESULT=$(python -c "
import psycopg2
import os
try:
    conn = psycopg2.connect(
        dbname=os.environ.get('DB_NAME'),
        user=os.environ.get('DB_USER'),
        password=os.environ.get('DB_PASSWORD'),
        host=os.environ.get('DB_HOST'),
        port=os.environ.get('DB_PORT', 5432)
    )
    conn.close()
    print('SUCCESS')
except Exception as e:
    print(f'ERROR: {e}')
" 2>&1)
        
        if [[ "$CONNECTION_RESULT" == "SUCCESS" ]]; then
            echo -e "${GREEN}PostgreSQL está listo!${NC}"
            return 0
        fi
        echo "Intento $i/30 - $CONNECTION_RESULT"
        sleep 1
    done
    
    echo -e "${RED}Error: No se pudo conectar a PostgreSQL después de 30 segundos${NC}"
    echo -e "${RED}Último error: $CONNECTION_RESULT${NC}"
    exit 1
}

# -----------------------------------------------------------------------------
# Función para esperar a que Redis esté listo
# -----------------------------------------------------------------------------
wait_for_redis() {
    echo -e "${YELLOW}Esperando a que Redis esté disponible...${NC}"
    echo -e "${YELLOW}CELERY_BROKER_URL: $CELERY_BROKER_URL${NC}"
    
    for i in {1..30}; do
        CONNECTION_RESULT=$(python -c "
import redis
import os
try:
    r = redis.from_url(os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0'))
    r.ping()
    print('SUCCESS')
except Exception as e:
    print(f'ERROR: {e}')
" 2>&1)
        
        if [[ "$CONNECTION_RESULT" == "SUCCESS" ]]; then
            echo -e "${GREEN}Redis está listo!${NC}"
            return 0
        fi
        echo "Intento $i/30 - $CONNECTION_RESULT"
        sleep 1
    done
    
    echo -e "${RED}Error: No se pudo conectar a Redis después de 30 segundos${NC}"
    echo -e "${RED}Último error: $CONNECTION_RESULT${NC}"
    exit 1
}

# -----------------------------------------------------------------------------
# Rol vía entorno: Coolify no deja sobreescribir el CMD de la imagen desde su UI
# para apps de tipo dockerfile, así que PROPAGA_ROLE permite elegir el proceso
# (celery-worker / celery-beat) con una simple variable de entorno. Sin ella se
# respeta el CMD del Dockerfile (gunicorn).
# -----------------------------------------------------------------------------
if [ -n "$PROPAGA_ROLE" ]; then
    echo -e "${YELLOW}PROPAGA_ROLE=$PROPAGA_ROLE — ignorando el CMD de la imagen${NC}"
    set -- "$PROPAGA_ROLE"
fi

# -----------------------------------------------------------------------------
# Ejecutar según el comando
# -----------------------------------------------------------------------------
case "$1" in
    # Modo Web Server (Django + Gunicorn)
    gunicorn|/opt/venv/bin/gunicorn)
        echo -e "${GREEN}Iniciando modo producción...${NC}"
        wait_for_db
        
        mkdir -p /app/staticfiles
        
        echo -e "${YELLOW}Ejecutando migraciones...${NC}"
        python manage.py migrate --noinput
        
        echo -e "${YELLOW}Recolectando archivos estáticos...${NC}"
        python manage.py collectstatic --noinput

        # Carga las credenciales OAuth del entorno a las SocialApp de allauth.
        # Idempotente y sin efecto si no hay env vars; nunca debe tumbar el deploy.
        echo -e "${YELLOW}Sincronizando apps sociales (OAuth)...${NC}"
        python manage.py seed_social_apps || echo -e "${RED}seed_social_apps falló — continuando${NC}"
        
        echo -e "${GREEN}Iniciando Gunicorn en puerto 8000...${NC}"
        shift  # Remover primer argumento para pasar el resto
        exec /opt/venv/bin/gunicorn --bind 0.0.0.0:8000 --workers 2 --threads 4 --worker-class gthread --timeout 120 config.wsgi:application
        ;;
    
    # Modo Celery Worker
    celery-worker)
        wait_for_db
        wait_for_redis
        
        echo -e "${GREEN}Iniciando Celery Worker...${NC}"
        exec celery -A config worker --loglevel=info --concurrency=2
        ;;
    
    # Modo Celery Beat (Scheduler)
    celery-beat)
        wait_for_redis
        
        echo -e "${GREEN}Iniciando Celery Beat...${NC}"
        exec celery -A config beat --loglevel=info --schedule /app/logs/celerybeat-schedule
        ;;
    
    # Cualquier otro comando
    *)
        exec "$@"
        ;;
esac
