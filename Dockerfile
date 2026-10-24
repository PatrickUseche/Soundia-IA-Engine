# syntax=docker/dockerfile:1
#
# Motor de IA de SoundIA (Django). Sirve con gunicorn y guarda la base SQLite y los audios en /data (un volumen).
#
# NOTA: este Dockerfile no se pudo construir al escribirlo (la maquina de desarrollo no tiene Docker).
# Si falla al construirlo, revisar primero la imagen base y la instalacion de librosa (numba/llvmlite).

FROM python:3.12-slim

# MALLOC_ARENA_MAX limita a 2 las zonas de memoria de glibc (una por hilo, por defecto): con varios hilos retienen mucha
# memoria libre que no se devuelve al sistema.
ENV MALLOC_ARENA_MAX=2 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    # librosa usa numba, que compila en el primer uso: la cache va a un sitio con permiso de escritura.
    NUMBA_CACHE_DIR=/tmp/numba

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# No se ejecuta como root. /data guarda lo que debe sobrevivir al contenedor: la base y los audios subidos.
RUN useradd --system --uid 1001 --no-create-home soundia \
    && mkdir -p /data/media \
    && chown -R soundia /data
USER soundia

ENV SQLITE_PATH=/data/db.sqlite3 \
    MEDIA_ROOT=/data/media
VOLUME ["/data"]

EXPOSE 8000

# --access-logfile - registra cada peticion (metodo, ruta y codigo) en el log, util para ver que llega al motor.
# DJANGO_DEBUG=False exige DJANGO_SECRET_KEY. El timeout es largo porque analizar una pista tarda segundos.
# Escucha en $PORT (lo fija Render) o en 8000. WEB_CONCURRENCY son los procesos (2 por defecto; 1 en 512 MB de RAM) y
# con 1 proceso se usan 4 hilos para atender varias peticiones a la vez.
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn soundia_ai.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --threads ${GUNICORN_THREADS:-1} --timeout 180 --access-logfile -"]
