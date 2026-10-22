from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Track(models.Model):
    """Pista analizada: lo que el motor de mezcla necesita saber de ella."""

    # Estado del analisis de voz (se hace aparte, en segundo plano: tarda minutos).
    VOCALS_NONE = 'none'  # todavia no se ha pedido
    VOCALS_PENDING = 'pending'  # en la cola
    VOCALS_RUNNING = 'running'
    VOCALS_DONE = 'done'
    VOCALS_FAILED = 'failed'
    VOCALS_UNAVAILABLE = 'unavailable'  # el modelo de separacion no esta instalado
    VOCAL_STATUS_CHOICES = [
        (VOCALS_NONE, 'sin analizar'),
        (VOCALS_PENDING, 'en cola'),
        (VOCALS_RUNNING, 'analizando'),
        (VOCALS_DONE, 'analizada'),
        (VOCALS_FAILED, 'fallo'),
        (VOCALS_UNAVAILABLE, 'no disponible'),
    ]

    title = models.CharField(max_length=255, help_text="Titulo o nombre del archivo.")
    duration = models.FloatField(help_text="Duracion en segundos.")
    bpm = models.FloatField(
        validators=[MinValueValidator(20), MaxValueValidator(300)],
        help_text="Tempo estimado en pulsos por minuto.",
    )
    key = models.CharField(max_length=16, help_text="Tonalidad, por ejemplo 'C major'.")
    camelot = models.CharField(max_length=3, help_text="Codigo de la rueda de Camelot, por ejemplo '8B'.")
    energy = models.FloatField(
        validators=[MinValueValidator(0), MaxValueValidator(1)],
        help_text="Energia media normalizada entre 0 y 1.",
    )
    cue_points = models.JSONField(
        default=list,
        blank=True,
        help_text="Puntos de mezcla en segundos, ordenados de menor a mayor.",
    )
    audio_file = models.FileField(
        upload_to='tracks/',
        blank=True,
        help_text="Archivo de audio original, para poder reproducir la pista en los decks.",
    )
    grid_offset = models.FloatField(
        null=True, blank=True,
        help_text="Segundo del primer pulso de la rejilla de tempo; vacio si la pista no tiene un ritmo claro.",
    )
    grid_downbeat = models.FloatField(
        null=True, blank=True, help_text="Segundo del primer tiempo del compas (dentro del primer compas).",
    )
    grid_confidence = models.FloatField(
        null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(1)],
        help_text="Seguridad (0-1) de que grid_downbeat sea de verdad el primer tiempo del compas.",
    )
    vocal_status = models.CharField(
        max_length=12, choices=VOCAL_STATUS_CHOICES, default=VOCALS_NONE,
        help_text="Estado del analisis de voz del final de la pista.",
    )
    vocal_last_end = models.FloatField(
        null=True, blank=True,
        help_text="Segundo en que acaba la ultima frase cantada; vacio si no se analizo o no hay voz al final.",
    )
    vocal_first_start = models.FloatField(
        null=True, blank=True,
        help_text="Segundo en que empieza la primera frase cantada (solo se mira el inicio); vacio si no se "
                  "analizo o no hay voz al principio.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # El id desempata pistas guardadas en el mismo instante, para que el orden sea determinista.
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f"{self.title} ({self.bpm:.0f} BPM, {self.camelot})"
