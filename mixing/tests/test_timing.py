from django.test import SimpleTestCase, TestCase

from audio.models import Track
from mixing.compatibility import TrackInfo
from mixing.models import MixTimingFeedback
from mixing.timing import (
    MAX_ADVANCE_SECONDS,
    MIN_TIMING_SAMPLES,
    advance_from,
    learned_advance,
    record_mix_timing,
    timing_count,
)
from mixing.transition import plan_transition


class AdvanceFromTests(SimpleTestCase):
    def test_sin_suficientes_casos_no_adelanta_nada(self):
        self.assertEqual(advance_from([]), 0.0)
        self.assertEqual(advance_from([30.0] * (MIN_TIMING_SAMPLES - 1)), 0.0)

    def test_con_los_casos_minimos_adelanta_la_mediana(self):
        self.assertEqual(advance_from([10.0, 20.0, 30.0]), 20.0)

    def test_la_mediana_ignora_un_caso_extremo(self):
        self.assertEqual(advance_from([10.0, 12.0, 11.0, 200.0]), 11.5)

    def test_un_caso_en_que_pidio_mezclar_despues_cuenta_como_cero(self):
        self.assertEqual(advance_from([-5.0, 0.0, 0.0, 10.0]), 0.0)

    def test_no_adelanta_mas_del_maximo(self):
        self.assertEqual(advance_from([500.0] * 5), MAX_ADVANCE_SECONDS)


class TimingStorageTests(TestCase):
    def setUp(self):
        self.a = Track.objects.create(title='a', duration=300, bpm=128, key='C major', camelot='8B', energy=0.5,
                                      cue_points=[0.0, 270.0])
        self.b = Track.objects.create(title='b', duration=300, bpm=128, key='C major', camelot='8B', energy=0.5,
                                      cue_points=[0.0])

    def test_sin_registros_no_hay_adelanto(self):
        self.assertEqual(learned_advance(), 0.0)
        self.assertEqual(timing_count(), 0)

    def test_registrar_guarda_el_caso_y_devuelve_el_adelanto_vigente(self):
        self.assertEqual(record_mix_timing(self.a, self.b, planned=270.0, actual=250.0), 0.0)
        self.assertEqual(record_mix_timing(self.a, self.b, planned=270.0, actual=240.0), 0.0)
        self.assertEqual(record_mix_timing(self.a, self.b, planned=270.0, actual=230.0), 30.0)

        self.assertEqual(timing_count(), 3)
        self.assertEqual(MixTimingFeedback.objects.count(), 3)
        self.assertEqual(learned_advance(), 30.0)

    def test_solo_cuentan_los_casos_mas_recientes(self):
        for _ in range(30):
            record_mix_timing(self.a, self.b, planned=270.0, actual=260.0)
        for _ in range(20):
            record_mix_timing(self.a, self.b, planned=270.0, actual=200.0)

        self.assertEqual(learned_advance(), 70.0)


class PlanWithAdvanceTests(SimpleTestCase):
    def info(self, id, bpm, cues):
        return TrackInfo(id=id, title=str(id), bpm=bpm, camelot='8B', energy=0.5, duration=300.0, cue_points=cues)

    def test_un_fundido_sale_antes_en_los_segundos_aprendidos(self):
        a, b = self.info(1, 128, [0.0, 270.0]), self.info(2, 174, [0.0])
        base = plan_transition(a, b)
        adelantado = plan_transition(a, b, advance=40.0)

        self.assertEqual(adelantado.mix_out_at, round(base.mix_out_at - 40.0, 3))
        self.assertEqual(adelantado.mix_out_advance, 40.0)
        self.assertEqual(base.mix_out_advance, 0.0)

    def test_una_mezcla_igualada_salta_al_cue_que_cabe_con_el_adelanto(self):
        a, b = self.info(1, 128, [0.0, 60.0, 200.0, 270.0]), self.info(2, 128, [0.0])

        self.assertEqual(plan_transition(a, b).mix_out_at, 270.0)
        self.assertEqual(plan_transition(a, b, advance=40.0).mix_out_at, 200.0)

    def test_el_adelanto_nunca_deja_la_salida_antes_del_inicio(self):
        a, b = self.info(1, 128, [0.0]), self.info(2, 174, [0.0])

        self.assertEqual(plan_transition(a, b, advance=500.0).mix_out_at, 0.0)
