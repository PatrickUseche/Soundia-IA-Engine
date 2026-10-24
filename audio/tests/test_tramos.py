"""El analisis por tramos (para gastar poca memoria) debe dar lo mismo que calcularlo de una vez."""
import librosa
import numpy as np
from django.test import SimpleTestCase

from audio import analysis, beatgrid
from audio.tests.signals import SR
from audio.tests.test_services import cancion_de_prueba


class EnvolventeDeAtaquesTests(SimpleTestCase):
    def test_por_tramos_coincide_con_calcularla_entera(self):
        y = cancion_de_prueba(bpm=124, seconds=200)  # mas de dos tramos de 4096 frames

        por_tramos = analysis._onset_envelope(y, SR)
        entera = librosa.onset.onset_strength(y=y, sr=SR, hop_length=analysis.ANALYSIS_HOP)

        self.assertEqual(len(por_tramos), len(entera))
        self.assertLess(np.max(np.abs(por_tramos - entera)) / np.max(entera), 0.05)


class TonalidadPorTramosTests(SimpleTestCase):
    def test_el_cromagrama_medio_por_tramos_coincide_con_el_entero(self):
        y = cancion_de_prueba(bpm=120, seconds=100)  # mas de dos tramos de 1280 frames

        partes = analysis._chunked_frames(
            y, analysis.CHROMA_CHUNK_FRAMES, analysis.CHROMA_MARGIN_FRAMES,
            lambda tramo: librosa.feature.chroma_cqt(y=tramo, sr=SR, hop_length=analysis.ANALYSIS_HOP))
        por_tramos = np.concatenate(partes, axis=1)
        entero = librosa.feature.chroma_cqt(y=y, sr=SR, hop_length=analysis.ANALYSIS_HOP)

        self.assertEqual(por_tramos.shape, entero.shape)
        self.assertLess(np.max(np.abs(por_tramos.mean(axis=1) - entero.mean(axis=1))), 0.02)

    def test_detecta_la_tonalidad_de_una_pista_larga(self):
        self.assertEqual(analysis.detect_key(cancion_de_prueba(bpm=120, seconds=100), SR).name, 'C major')


class TramoMasRitmicoTests(SimpleTestCase):
    def test_una_envolvente_corta_se_devuelve_entera(self):
        envolvente = np.arange(10, dtype=float)

        self.assertIs(analysis._most_rhythmic_excerpt(envolvente, 20), envolvente)

    def test_elige_el_tramo_con_mas_ataques(self):
        envolvente = np.zeros(100)
        envolvente[60:70] = 1.0

        tramo = analysis._most_rhythmic_excerpt(envolvente, 20)

        self.assertEqual(len(tramo), 20)
        self.assertEqual(tramo.sum(), 10.0)

    def test_el_tempo_de_una_pista_larga_sale_del_tramo_mas_ritmico(self):
        y = cancion_de_prueba(bpm=124, seconds=200)

        self.assertAlmostEqual(analysis.detect_bpm(y, SR), 124, delta=1.5)


class RejillaConTramosTests(SimpleTestCase):
    def test_la_correccion_de_ataque_usa_un_tramo_central_y_da_lo_mismo(self):
        y = cancion_de_prueba(bpm=120, seconds=300)
        pulsos = np.arange(1, 290, 0.5)

        correccion = beatgrid._attack_correction(y, SR, pulsos)
        limite = beatgrid.MAX_ATTACK_CORRECTION_SECONDS

        self.assertLessEqual(abs(correccion), limite)
