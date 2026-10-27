import math

from django.test import SimpleTestCase

from mixing.compatibility import TrackInfo
from mixing.tempo import match_tempo
from mixing.transition import (
    BARS_NORMAL,
    BARS_FADE,
    BARS_QUICK,
    BARS_SMOOTH,
    STYLE_BLEND,
    STYLE_FADE,
    FADE_END_MARGIN_SECONDS,
    fit_bars_to_intro,
    VOCAL_TAIL_GAP_SECONDS,
    choose_fade_out,
    choose_mix_out,
    choose_style_and_bars,
    eq_automation,
    plan_transition,
)


def track(id=1, bpm=128.0, camelot='8B', energy=0.6, duration=300.0, cues=None, vocal_last_end=None,
          vocal_first_start=None):
    return TrackInfo(id=id, title=f'pista {id}', bpm=bpm, camelot=camelot, energy=energy,
                     duration=duration, cue_points=[0.0, 60.0, 270.0] if cues is None else cues,
                     vocal_last_end=vocal_last_end, vocal_first_start=vocal_first_start)


class EqAutomationTests(SimpleTestCase):
    def test_tiene_un_punto_mas_que_pasos_y_cubre_de_0_a_1(self):
        puntos = eq_automation(16)

        self.assertEqual(len(puntos), 17)
        self.assertEqual(puntos[0].position, 0.0)
        self.assertEqual(puntos[-1].position, 1.0)

    def test_al_inicio_solo_suena_la_pista_a(self):
        inicio = eq_automation(16)[0]

        self.assertEqual((inicio.gain_a, inicio.gain_b), (1.0, 0.0))
        self.assertEqual((inicio.low_a, inicio.low_b), (1.0, 0.0))

    def test_al_final_solo_suena_la_pista_b(self):
        final = eq_automation(16)[-1]

        self.assertAlmostEqual(final.gain_a, 0.0, places=3)
        self.assertEqual(final.gain_b, 1.0)
        self.assertEqual((final.low_a, final.low_b), (0.0, 1.0))

    def test_el_crossfader_es_de_potencia_constante(self):
        for punto in eq_automation(32):
            with self.subTest(position=punto.position):
                self.assertAlmostEqual(punto.gain_a ** 2 + punto.gain_b ** 2, 1.0, places=3)

    def test_nunca_suenan_los_graves_de_las_dos_pistas_a_la_vez(self):
        for punto in eq_automation(32):
            with self.subTest(position=punto.position):
                self.assertEqual(punto.low_a + punto.low_b, 1.0)

    def test_el_intercambio_de_graves_ocurre_a_mitad(self):
        puntos = eq_automation(16)

        antes = [p for p in puntos if p.position < 0.5]
        despues = [p for p in puntos if p.position >= 0.5]
        self.assertTrue(all(p.low_a == 1.0 and p.low_b == 0.0 for p in antes))
        self.assertTrue(all(p.low_a == 0.0 and p.low_b == 1.0 for p in despues))

    def test_la_pista_b_entra_de_forma_creciente_y_la_a_sale_de_forma_decreciente(self):
        puntos = eq_automation(16)

        for anterior, siguiente in zip(puntos, puntos[1:]):
            self.assertGreaterEqual(siguiente.gain_b, anterior.gain_b)
            self.assertLessEqual(siguiente.gain_a, anterior.gain_a)
            self.assertGreaterEqual(siguiente.high_b, anterior.high_b)
            self.assertLessEqual(siguiente.mid_a, anterior.mid_a)

    def test_todos_los_valores_estan_entre_0_y_1(self):
        for punto in eq_automation(24):
            for valor in (punto.gain_a, punto.gain_b, punto.low_a, punto.low_b,
                          punto.mid_a, punto.mid_b, punto.high_a, punto.high_b):
                self.assertGreaterEqual(valor, 0.0)
                self.assertLessEqual(valor, 1.0)

    def test_un_paso_invalido_lanza_error(self):
        with self.assertRaises(ValueError):
            eq_automation(0)


class ChooseStyleTests(SimpleTestCase):
    def test_tempo_casi_igual_y_tonalidades_vecinas_es_mezcla_larga(self):
        self.assertEqual(choose_style_and_bars(match_tempo(128, 127), 1), (STYLE_BLEND, BARS_SMOOTH))

    def test_misma_tonalidad_y_mismo_tempo_es_mezcla_larga(self):
        self.assertEqual(choose_style_and_bars(match_tempo(128, 128), 0), (STYLE_BLEND, BARS_SMOOTH))

    def test_bastante_ajuste_de_pitch_acorta_la_mezcla(self):
        # 128 -> 123 pide +4.1 %, por encima del 4 %.
        self.assertEqual(choose_style_and_bars(match_tempo(128, 123), 0), (STYLE_BLEND, BARS_NORMAL))

    def test_tonalidades_a_dos_o_tres_pasos_dan_mezcla_normal(self):
        self.assertEqual(choose_style_and_bars(match_tempo(128, 128), 2), (STYLE_BLEND, BARS_NORMAL))
        self.assertEqual(choose_style_and_bars(match_tempo(128, 128), 3), (STYLE_BLEND, BARS_NORMAL))

    def test_tonalidades_que_chocan_dan_mezcla_rapida(self):
        self.assertEqual(choose_style_and_bars(match_tempo(128, 128), 4), (STYLE_BLEND, BARS_QUICK))
        self.assertEqual(choose_style_and_bars(match_tempo(128, 128), 6), (STYLE_BLEND, BARS_QUICK))

    def test_tempos_imposibles_de_igualar_dan_fundido(self):
        self.assertEqual(choose_style_and_bars(match_tempo(128, 174), 0), (STYLE_FADE, BARS_FADE))

    def test_el_fundido_manda_aunque_las_tonalidades_sean_perfectas(self):
        self.assertEqual(choose_style_and_bars(match_tempo(100, 140), 0), (STYLE_FADE, BARS_FADE))


class ChooseFadeOutTests(SimpleTestCase):
    def test_deja_un_margen_antes_del_final_para_que_el_fundido_no_se_pase(self):
        self.assertEqual(choose_fade_out(track(duration=200), 5.0), 200 - 5.0 - FADE_END_MARGIN_SECONDS)

    def test_una_pista_mas_corta_que_el_fundido_empieza_en_cero(self):
        self.assertEqual(choose_fade_out(track(duration=4), 5.0), 0.0)

    def test_si_la_voz_acaba_antes_del_final_el_fundido_empieza_justo_despues_de_la_ultima_frase(self):
        pista = track(duration=300, vocal_last_end=280.0)

        self.assertEqual(choose_fade_out(pista, 5.0), 280.0 + VOCAL_TAIL_GAP_SECONDS)

    def test_si_la_voz_llega_hasta_el_final_no_hay_cola_instrumental_y_se_va_al_final(self):
        pista = track(duration=300, vocal_last_end=298.0)

        self.assertEqual(choose_fade_out(pista, 5.0), 300 - 5.0 - FADE_END_MARGIN_SECONDS)

    def test_nunca_empieza_despues_del_ultimo_punto_en_que_cabe_el_fundido(self):
        pista = track(duration=300, vocal_last_end=293.0)  # el fundido empezaria en 294, pero el ultimo punto que cabe es 293

        self.assertEqual(choose_fade_out(pista, 5.0), 300 - 5.0 - FADE_END_MARGIN_SECONDS)

    def test_el_adelanto_aprendido_se_resta_del_punto_elegido(self):
        pista = track(duration=300, vocal_last_end=280.0)

        self.assertEqual(choose_fade_out(pista, 5.0, advance=10.0), 281.0 - 10.0)
        self.assertEqual(choose_fade_out(track(duration=200), 5.0, advance=10.0), 200 - 5.0 - FADE_END_MARGIN_SECONDS - 10.0)

    def test_un_adelanto_enorme_no_deja_el_punto_antes_del_inicio(self):
        self.assertEqual(choose_fade_out(track(duration=100), 5.0, advance=500.0), 0.0)


class ChooseMixOutTests(SimpleTestCase):
    def test_elige_el_ultimo_cue_en_el_que_cabe_la_transicion(self):
        pista = track(duration=300, cues=[0.0, 60.0, 270.0])

        self.assertEqual(choose_mix_out(pista, 30.0), 270.0)

    def test_descarta_un_cue_demasiado_cerca_del_final(self):
        pista = track(duration=300, cues=[0.0, 60.0, 285.0])  # 285 + 30 > 300

        self.assertEqual(choose_mix_out(pista, 30.0), 60.0)

    def test_sin_cues_aptos_usa_el_final_menos_la_duracion(self):
        pista = track(duration=300, cues=[])

        self.assertEqual(choose_mix_out(pista, 30.0), 270.0)

    def test_tolera_unos_milisegundos_de_exceso(self):
        pista = track(duration=300, cues=[0.0, 270.4])

        self.assertEqual(choose_mix_out(pista, 30.0), 270.4)

    def test_una_pista_mas_corta_que_la_transicion_empieza_en_cero(self):
        pista = track(duration=20, cues=[])

        self.assertEqual(choose_mix_out(pista, 30.0), 0.0)


class PlanTransitionTests(SimpleTestCase):
    def test_pareja_ideal_da_una_mezcla_larga_de_16_compases(self):
        plan = plan_transition(track(1, bpm=128), track(2, bpm=128))

        self.assertEqual(plan.style, STYLE_BLEND)
        self.assertEqual(plan.bars, 16)
        # 16 compases de 4 pulsos a 128 BPM = 64 * 60 / 128 = 30 s.
        self.assertEqual(plan.seconds, 30.0)

    def test_la_mezcla_empieza_en_el_ultimo_cue_que_deja_espacio(self):
        plan = plan_transition(track(1, duration=300, cues=[0.0, 60.0, 270.0]), track(2))

        self.assertEqual(plan.mix_out_at, 270.0)
        self.assertLessEqual(plan.mix_out_at + plan.seconds, 300.0 + 0.5)

    def test_la_pista_b_entra_desde_su_primer_cue(self):
        plan = plan_transition(track(1), track(2, cues=[4.0, 32.0]))

        self.assertEqual(plan.mix_in_at, 4.0)

    def test_si_b_no_tiene_cues_entra_desde_el_principio(self):
        plan = plan_transition(track(1), track(2, cues=[]))

        self.assertEqual(plan.mix_in_at, 0.0)

    def test_tempos_imposibles_dan_un_fundido_corto_con_automatizacion(self):
        plan = plan_transition(track(1, bpm=128), track(2, bpm=174))

        self.assertEqual(plan.style, STYLE_FADE)
        self.assertEqual(plan.bars, BARS_FADE)
        self.assertEqual(plan.seconds, 3.75)  # 2 compases a 128 BPM
        self.assertEqual(len(plan.automation), BARS_FADE * 4 + 1)
        self.assertEqual(plan.automation[0].gain_a, 1.0)
        self.assertEqual(plan.automation[-1].gain_b, 1.0)

    def test_el_fundido_termina_con_la_cancion_en_vez_de_saltar_al_ultimo_cue(self):
        # Cue de salida a 285 s: si el fundido empezara ahi, la pista A se apagaria 4 s despues y se perderia
        # el resto de la cancion (con su letra).
        plan = plan_transition(track(1, bpm=128, duration=300, cues=[0.0, 285.0]), track(2, bpm=174))

        self.assertEqual(plan.mix_out_at, round(300 - plan.seconds - FADE_END_MARGIN_SECONDS, 3))
        self.assertGreater(plan.mix_out_at, 285.0)

    def test_el_fundido_aprovecha_la_cola_instrumental_cuando_se_conoce_donde_acaba_la_voz(self):
        plan = plan_transition(track(1, bpm=128, duration=300, vocal_last_end=270.0), track(2, bpm=174))

        self.assertEqual(plan.style, STYLE_FADE)
        self.assertEqual(plan.mix_out_at, 271.0)

    def test_una_mezcla_con_tempos_igualados_sigue_saliendo_en_un_cue(self):
        plan = plan_transition(track(1, bpm=128, duration=300, cues=[0.0, 60.0, 270.0]), track(2, bpm=128))

        self.assertEqual(plan.style, STYLE_BLEND)
        self.assertIn(plan.mix_out_at, [0.0, 60.0, 270.0])

    def test_la_automatizacion_tiene_un_punto_por_pulso(self):
        plan = plan_transition(track(1), track(2))

        self.assertEqual(len(plan.automation), 16 * 4 + 1)

    def test_incluye_el_ajuste_de_tempo_para_igualar_las_pistas(self):
        plan = plan_transition(track(1, bpm=128), track(2, bpm=126))

        self.assertTrue(plan.tempo_match.feasible)
        self.assertAlmostEqual(126 * plan.tempo_match.ratio, 128)

    def test_incluye_la_puntuacion_de_compatibilidad(self):
        plan = plan_transition(track(1), track(2))

        self.assertEqual(plan.compatibility.score, 1.0)

    def test_la_duracion_depende_del_tempo_de_la_pista_actual(self):
        lenta = plan_transition(track(1, bpm=100), track(2, bpm=100))
        rapida = plan_transition(track(1, bpm=140), track(2, bpm=140))

        self.assertGreater(lenta.seconds, rapida.seconds)
        self.assertTrue(math.isclose(lenta.seconds, 16 * 4 * 60 / 100, rel_tol=1e-3))


class FitBarsToIntroTests(SimpleTestCase):
    # A 120 BPM un compas dura 2 s: 16 compases = 32 s, 8 = 16 s, 4 = 8 s.
    BAR = 2.0

    def test_si_no_se_sabe_donde_empieza_la_voz_no_cambia_nada(self):
        self.assertEqual(fit_bars_to_intro(track(), BARS_SMOOTH, self.BAR, 0.0), BARS_SMOOTH)

    def test_si_la_intro_es_larga_se_conserva_la_mezcla_pedida(self):
        entrante = track(vocal_first_start=40.0)

        self.assertEqual(fit_bars_to_intro(entrante, BARS_SMOOTH, self.BAR, 0.0), BARS_SMOOTH)

    def test_si_la_voz_entra_antes_de_que_acabe_el_solape_se_acorta_a_lo_que_cabe(self):
        entrante = track(vocal_first_start=20.0)  # caben 16 s: 8 compases

        self.assertEqual(fit_bars_to_intro(entrante, BARS_SMOOTH, self.BAR, 0.0), BARS_NORMAL)

    def test_se_cuenta_desde_el_punto_de_entrada(self):
        entrante = track(vocal_first_start=20.0)

        # Entrando en el segundo 10 solo quedan 10 s hasta la voz: 4 compases (8 s).
        self.assertEqual(fit_bars_to_intro(entrante, BARS_SMOOTH, self.BAR, 10.0), BARS_QUICK)

    def test_si_ni_la_mezcla_mas_corta_cabe_se_queda_con_la_mas_corta(self):
        entrante = track(vocal_first_start=3.0)

        self.assertEqual(fit_bars_to_intro(entrante, BARS_SMOOTH, self.BAR, 0.0), BARS_QUICK)

    def test_una_voz_que_ya_suena_en_el_punto_de_entrada_deja_la_mas_corta(self):
        entrante = track(vocal_first_start=0.0)

        self.assertEqual(fit_bars_to_intro(entrante, BARS_NORMAL, self.BAR, 0.4), BARS_QUICK)

    def test_nunca_alarga_la_mezcla_pedida(self):
        entrante = track(vocal_first_start=200.0)

        self.assertEqual(fit_bars_to_intro(entrante, BARS_QUICK, self.BAR, 0.0), BARS_QUICK)
        self.assertEqual(fit_bars_to_intro(entrante, BARS_NORMAL, self.BAR, 0.0), BARS_NORMAL)


class PlanTransitionConVozDelInicioTests(SimpleTestCase):
    def test_la_mezcla_larga_se_acorta_para_no_pisar_la_voz_de_la_pista_que_entra(self):
        saliente = track(1, bpm=120.0, camelot='8B')
        con_voz_pronto = track(2, bpm=120.0, camelot='8B', cues=[0.0, 60.0], vocal_first_start=20.0)
        sin_dato = track(3, bpm=120.0, camelot='8B', cues=[0.0, 60.0])

        acortada = plan_transition(saliente, con_voz_pronto)
        original = plan_transition(saliente, sin_dato)

        self.assertEqual(original.bars, BARS_SMOOTH)
        self.assertEqual(acortada.bars, BARS_NORMAL)
        self.assertEqual(acortada.seconds, 16.0)
        self.assertEqual(len(acortada.automation), BARS_NORMAL * 4 + 1)  # una automatizacion por pulso

    def test_un_fundido_no_se_toca(self):
        saliente = track(1, bpm=120.0, camelot='8B')
        entrante = track(2, bpm=170.0, camelot='8B', cues=[0.0, 60.0], vocal_first_start=1.0)

        plan = plan_transition(saliente, entrante)

        self.assertEqual(plan.style, STYLE_FADE)
        self.assertEqual(plan.bars, BARS_FADE)


class VariableTempoTests(SimpleTestCase):
    def test_con_una_pista_de_tempo_variable_el_plan_es_un_fundido_aunque_el_pitch_alcance(self):
        a = track(bpm=128)
        b = TrackInfo(id=2, title='en vivo', bpm=128.0, camelot='8B', energy=0.6, duration=300.0,
                      cue_points=[0.0, 60.0, 270.0], tempo_variable=True)

        plan = plan_transition(a, b)

        self.assertTrue(plan.tempo_match.feasible)
        self.assertEqual(plan.style, STYLE_FADE)
        self.assertEqual(plan.bars, BARS_FADE)
        self.assertTrue(plan.variable_tempo)

    def test_tambien_si_la_variable_es_la_que_sale(self):
        a = TrackInfo(id=1, title='en vivo', bpm=128.0, camelot='8B', energy=0.6, duration=300.0,
                      cue_points=[0.0, 60.0, 270.0], tempo_variable=True)

        self.assertEqual(plan_transition(a, track(id=2, bpm=128)).style, STYLE_FADE)

    def test_con_tempos_fijos_nada_cambia(self):
        plan = plan_transition(track(bpm=128), track(id=2, bpm=128))

        self.assertEqual(plan.style, STYLE_BLEND)
        self.assertFalse(plan.variable_tempo)


class LearnedStyleTests(SimpleTestCase):
    def test_los_compases_aprendidos_reemplazan_a_los_de_la_regla(self):
        plan = plan_transition(track(bpm=128), track(id=2, bpm=128), bars_override=BARS_QUICK)

        self.assertEqual(plan.style, STYLE_BLEND)
        self.assertEqual(plan.bars, BARS_QUICK)

    def test_un_fundido_no_se_toca(self):
        # 100 y 128 BPM no se igualan con el pitch: es un fundido corto.
        plan = plan_transition(track(bpm=100), track(id=2, bpm=128), bars_override=BARS_SMOOTH)

        self.assertEqual(plan.style, STYLE_FADE)
        self.assertEqual(plan.bars, BARS_FADE)

    def test_el_cambio_de_graves_se_hace_donde_indica_el_dj(self):
        puntos = eq_automation(16, bass_swap_at=0.25)

        primer_corte = next(p.position for p in puntos if p.low_a == 0.0)
        self.assertEqual(primer_corte, 0.25)

    def test_por_defecto_los_graves_cambian_a_mitad(self):
        puntos = eq_automation(16)

        self.assertEqual(next(p.position for p in puntos if p.low_a == 0.0), 0.5)
