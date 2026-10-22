from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from audio.models import Track

_UNIT = [MinValueValidator(0), MaxValueValidator(1)]


class TransitionFeedback(models.Model):
    """Valoracion del DJ de una transicion: que puntuaciones tenia y si le gusto."""

    from_track = models.ForeignKey(Track, on_delete=models.CASCADE, related_name='+')
    to_track = models.ForeignKey(Track, on_delete=models.CASCADE, related_name='+')
    # Puntuaciones que tenia la transicion cuando se valoro (0-1): son los datos de entrenamiento.
    tempo = models.FloatField(validators=_UNIT)
    harmonic = models.FloatField(validators=_UNIT)
    energy = models.FloatField(validators=_UNIT)
    liked = models.BooleanField(help_text="True si le gusto la transicion; False si no.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f"{self.from_track_id} -> {self.to_track_id}: {'me gusto' if self.liked else 'no me gusto'}"


class LearnedWeights(models.Model):
    """Pesos de la puntuacion aprendidos de las valoraciones. Solo existe una fila (la mas reciente)."""

    tempo = models.FloatField(validators=_UNIT)
    harmonic = models.FloatField(validators=_UNIT)
    energy = models.FloatField(validators=_UNIT)
    samples = models.PositiveIntegerField(help_text="Valoraciones con las que se entreno.")
    version = models.PositiveIntegerField(default=1, help_text="Cuantas veces se han reentrenado los pesos.")
    accuracy = models.FloatField(
        null=True, blank=True, validators=_UNIT,
        help_text="Acierto con valoraciones apartadas del entrenamiento (validacion cruzada); vacio si no se pudo medir.",
    )
    default_accuracy = models.FloatField(
        null=True, blank=True, validators=_UNIT,
        help_text="Acierto de los pesos por defecto con esas mismas valoraciones, para comparar.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"tempo={self.tempo:.2f} armonia={self.harmonic:.2f} energia={self.energy:.2f} ({self.samples} valoraciones)"
