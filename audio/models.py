from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Track(models.Model):
    """Pista analizada: lo que el motor de mezcla necesita saber de ella."""

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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # El id desempata pistas guardadas en el mismo instante, para que el orden sea determinista.
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f"{self.title} ({self.bpm:.0f} BPM, {self.camelot})"
