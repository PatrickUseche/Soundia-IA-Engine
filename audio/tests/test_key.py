import numpy as np
from django.test import SimpleTestCase

from audio.analysis import AudioTooShortError, SilentAudioError, detect_key
from audio.tests.signals import SR, chord, sine


def _triad(root, third):
    return chord([root % 12, (root + third) % 12, (root + 7) % 12], 2)


def progression_major(root):
    """I - IV - V - I en la tonalidad mayor indicada."""
    return np.concatenate([_triad(root, 4), _triad(root + 5, 4), _triad(root + 7, 4), _triad(root, 4)])


def progression_minor(root):
    """i - iv - V - i en la tonalidad menor indicada (con dominante mayor)."""
    return np.concatenate([_triad(root, 3), _triad(root + 5, 3), _triad(root + 7, 4), _triad(root, 3)])


class DetectKeyTests(SimpleTestCase):
    def test_detecta_las_doce_tonalidades_mayores(self):
        for root in range(12):
            with self.subTest(root=root):
                key = detect_key(progression_major(root), SR)

                self.assertEqual((key.pitch_class, key.mode), (root, 'major'))

    def test_detecta_las_doce_tonalidades_menores(self):
        for root in range(12):
            with self.subTest(root=root):
                key = detect_key(progression_minor(root), SR)

                self.assertEqual((key.pitch_class, key.mode), (root, 'minor'))

    def test_expone_el_nombre_y_el_codigo_camelot(self):
        key = detect_key(progression_major(0), SR)

        self.assertEqual(key.name, 'C major')
        self.assertEqual(key.camelot, '8B')

    def test_la_relativa_menor_comparte_numero_camelot(self):
        mayor = detect_key(progression_major(0), SR)   # C mayor -> 8B
        menor = detect_key(progression_minor(9), SR)   # A menor -> 8A

        self.assertEqual(mayor.camelot[:-1], menor.camelot[:-1])
        self.assertNotEqual(mayor.camelot, menor.camelot)

    def test_la_confianza_esta_entre_0_y_1_y_es_alta_con_musica_clara(self):
        key = detect_key(progression_major(7), SR)

        self.assertGreater(key.confidence, 0.8)
        self.assertLessEqual(key.confidence, 1.0)

    def test_un_audio_corto_lanza_error(self):
        with self.assertRaises(AudioTooShortError):
            detect_key(sine(440, 1.0), SR)

    def test_el_silencio_lanza_error(self):
        with self.assertRaises(SilentAudioError):
            detect_key(np.zeros(SR * 5), SR)
