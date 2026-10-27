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


class MixTimingFeedback(models.Model):
    """Cuando el DJ pidio mezclar antes de lo que el Auto-DJ habia planeado: de ahi aprende cuando mezclar."""

    from_track = models.ForeignKey(Track, on_delete=models.CASCADE, related_name='+')
    to_track = models.ForeignKey(Track, on_delete=models.CASCADE, related_name='+')
    planned_mix_out = models.FloatField(validators=[MinValueValidator(0)], help_text="Segundo de A en que el plan mezclaba.")
    actual_mix_out = models.FloatField(validators=[MinValueValidator(0)], help_text="Segundo de A en que el DJ pidio mezclar.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f"{self.from_track_id} -> {self.to_track_id}: plan {self.planned_mix_out:.0f} s, DJ {self.actual_mix_out:.0f} s"


class LearnedWeights(models.Model):
    """Pesos de la puntuacion aprendidos de las valoraciones. Cada reentrenamiento guarda una version nueva; las
    anteriores se conservan (las ultimas) para poder volver a ellas, y solo una esta vigente (`active`)."""

    tempo = models.FloatField(validators=_UNIT)
    harmonic = models.FloatField(validators=_UNIT)
    energy = models.FloatField(validators=_UNIT)
    samples = models.PositiveIntegerField(help_text="Valoraciones con las que se entreno.")
    version = models.PositiveIntegerField(default=1, help_text="Cuantas veces se han reentrenado los pesos.")
    active = models.BooleanField(default=True, help_text="La version vigente; las demas son historial para volver atras.")
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


class MixRecording(models.Model):
    """Una transicion tal como la hizo un DJ: cuando sale la pista A, cuando entra la B, cuanto solapan y como
    movio el crossfader, el EQ y el volumen. Es el material con el que despues se aprende su estilo de mezcla.

    Las dos pistas se guardan como foto de sus datos en ese momento (`snapshot_a` y `snapshot_b`): si luego se corrige
    su rejilla o se borra la pista, la grabacion sigue siendo la misma.
    """

    SOURCE_CHOICES = [('manual', 'mezcla a mano'), ('autodj', 'Auto-DJ')]
    QUALITY_CHOICES = [('unreviewed', 'sin revisar'), ('good', 'buena'), ('discard', 'descartada')]

    from_track = models.ForeignKey(Track, null=True, on_delete=models.SET_NULL, related_name='+')
    to_track = models.ForeignKey(Track, null=True, on_delete=models.SET_NULL, related_name='+')
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default='manual')
    dj = models.CharField(max_length=60, default='dj', help_text="Alias de quien mezclo (nunca su nombre real).")
    mix_out_at = models.FloatField(validators=[MinValueValidator(0)], help_text="Segundo de A en que entra B.")
    mix_in_at = models.FloatField(validators=[MinValueValidator(0)], help_text="Segundo de B desde el que suena.")
    overlap_seconds = models.FloatField(validators=[MinValueValidator(0)], help_text="Segundos que suenan las dos.")
    pitch_a = models.FloatField(help_text="Factor de velocidad de A cuando entra B (1 = normal).")
    pitch_b = models.FloatField(help_text="Factor de velocidad de B cuando entra.")
    curves = models.JSONField(
        default=dict, blank=True,
        help_text="Curvas [segundo, valor 0-1] relativas a la entrada de B: crossfader y, por deck, volume/low/mid/high.",
    )
    snapshot_a = models.JSONField(help_text="Datos de la pista A cuando se grabo (bpm, Camelot, rejilla, voz...).")
    snapshot_b = models.JSONField(help_text="Datos de la pista B cuando se grabo.")
    genre_a = models.CharField(max_length=40, blank=True)
    genre_b = models.CharField(max_length=40, blank=True)
    quality = models.CharField(
        max_length=10, choices=QUALITY_CHOICES, default='unreviewed',
        help_text="Revision del DJ: solo las buenas deberian usarse para entrenar.",
    )
    notes = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f"{self.dj}: {self.from_track_id} -> {self.to_track_id} ({self.overlap_seconds:.0f} s)"


class StyleModelSetting(models.Model):
    """El interruptor del modelo del estilo del DJ (una sola fila). Apagado, el plan usa solo las reglas."""

    enabled = models.BooleanField(default=False, help_text="Usar lo aprendido del DJ donde el modelo gane a las reglas.")
    updated_at = models.DateTimeField(auto_now=True)


class AutoDjChoice(models.Model):
    """Lo que el DJ eligio como siguiente pista y lo que la IA habria propuesto: de ahi aprende que pista sigue.

    Los rasgos de la transicion se guardan aqui (no se leen de las pistas despues) porque el DJ borra pistas al terminar
    una sesion y las elecciones deben conservarse. `rejected_features` es null cuando el DJ acepto la propuesta.
    """

    from_track = models.ForeignKey(Track, null=True, on_delete=models.SET_NULL, related_name='+')
    chosen_track = models.ForeignKey(Track, null=True, on_delete=models.SET_NULL, related_name='+')
    recommended_track = models.ForeignKey(Track, null=True, on_delete=models.SET_NULL, related_name='+')
    chosen_features = models.JSONField(help_text="Rasgos de la transicion elegida (ver next_track_model.FEATURES).")
    rejected_features = models.JSONField(null=True, blank=True, help_text="Rasgos de la propuesta que el DJ descarto.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
