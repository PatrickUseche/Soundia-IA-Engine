from unittest import mock

import librosa
import numpy as np
from django.test import SimpleTestCase

from audio.analysis import _first_onset_time
from audio.tests.signals import SR, click_track


def _primer_ataque_sobre_la_pista_entera(y, sr):
    """Lo que hacia el motor antes: la deteccion sobre toda la senal de una vez (gasta cientos de MB en pistas largas)."""
    padding = 2048
    onsets = librosa.onset.onset_detect(y=np.concatenate([np.zeros(padding), y]), sr=sr, units='time')
    return 0.0 if len(onsets) == 0 else max(float(onsets[0]) - padding / sr, 0.0)


class FirstOnsetTimeTests(SimpleTestCase):
    """Buscar el primer ataque con una STFT de la pista entera sumaba ~480 MB de pico en una pista de 8 minutos sin
    ritmo claro y mataba al motor en los 512 MB de Render con una sola cancion. Ahora usa la envolvente de ataques
    calculada por tramos (memoria acotada) y da el mismo resultado que antes."""

    def test_encuentra_el_primer_ataque_de_una_pista_normal(self):
        y = click_track(120, seconds=10, first_beat=0.5)

        self.assertAlmostEqual(_first_onset_time(y, SR), 0.5, delta=0.1)

    def test_encuentra_el_primer_ataque_despues_de_mucho_silencio(self):
        y = np.concatenate([np.zeros(70 * SR), click_track(120, seconds=10, first_beat=0.3)])

        self.assertAlmostEqual(_first_onset_time(y, SR), 70.3, delta=0.2)

    def test_una_pista_sin_ataques_da_cero(self):
        self.assertEqual(_first_onset_time(np.zeros(SR * 10), SR), 0.0)

    def test_da_lo_mismo_que_la_deteccion_sobre_la_pista_entera(self):
        senales = {
            'clic normal': click_track(120, seconds=15, first_beat=0.5),
            'clic con silencio': np.concatenate([np.zeros(5 * SR), click_track(100, seconds=10, first_beat=0.2)]),
            # Intro muy suave y luego sonido fuerte: el primer ataque "musical" es el fuerte, como antes.
            'intro suave y luego fuerte': np.concatenate(
                [click_track(90, seconds=10, amplitude=0.02), click_track(90, seconds=10, amplitude=0.9)]),
        }

        for nombre, y in senales.items():
            with self.subTest(senal=nombre):
                self.assertAlmostEqual(
                    _first_onset_time(y, SR), _primer_ataque_sobre_la_pista_entera(y, SR), delta=0.03)

    def test_no_calcula_la_stft_de_la_pista_entera(self):
        y = click_track(120, seconds=200, first_beat=0.4)

        with mock.patch('audio.analysis.librosa.onset.onset_detect', wraps=librosa.onset.onset_detect) as espia:
            _first_onset_time(y, SR)

        # onset_detect recibe la envolvente ya calculada por tramos, no la senal (con la senal haria la STFT entera).
        self.assertEqual(espia.call_count, 1)
        self.assertNotIn('y', espia.call_args.kwargs)
        self.assertIn('onset_envelope', espia.call_args.kwargs)
