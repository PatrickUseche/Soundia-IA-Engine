from django.test import SimpleTestCase

from audio.camelot import (
    are_compatible,
    camelot_code,
    compatible_codes,
    harmonic_distance,
    key_name,
)


class CamelotCodeTests(SimpleTestCase):
    def test_tonalidades_conocidas(self):
        # Referencias de la rueda de Camelot estandar.
        casos = {
            (0, 'major'): '8B',   # C mayor
            (9, 'minor'): '8A',   # A menor (relativa de C mayor)
            (7, 'major'): '9B',   # G mayor
            (4, 'minor'): '9A',   # E menor
            (2, 'major'): '10B',  # D mayor
            (11, 'major'): '1B',  # B mayor
            (8, 'minor'): '1A',   # G# menor
            (6, 'major'): '2B',   # F# mayor
            (1, 'minor'): '12A',  # C# menor
        }
        for (pitch, mode), esperado in casos.items():
            with self.subTest(pitch=pitch, mode=mode):
                self.assertEqual(camelot_code(pitch, mode), esperado)

    def test_las_doce_tonalidades_de_cada_modo_son_distintas(self):
        mayores = {camelot_code(p, 'major') for p in range(12)}
        menores = {camelot_code(p, 'minor') for p in range(12)}

        self.assertEqual(len(mayores), 12)
        self.assertEqual(len(menores), 12)
        self.assertTrue(all(c.endswith('B') for c in mayores))
        self.assertTrue(all(c.endswith('A') for c in menores))

    def test_la_tonalidad_relativa_comparte_numero(self):
        # La relativa menor de cada mayor esta 3 semitonos por debajo.
        for pitch in range(12):
            with self.subTest(pitch=pitch):
                mayor = camelot_code(pitch, 'major')
                relativa_menor = camelot_code((pitch + 9) % 12, 'minor')
                self.assertEqual(mayor[:-1], relativa_menor[:-1])

    def test_nombre_legible(self):
        self.assertEqual(key_name(0, 'major'), 'C major')
        self.assertEqual(key_name(9, 'minor'), 'A minor')
        self.assertEqual(key_name(6, 'minor'), 'F# minor')

    def test_entradas_invalidas(self):
        with self.assertRaises(ValueError):
            camelot_code(12, 'major')
        with self.assertRaises(ValueError):
            camelot_code(-1, 'minor')
        with self.assertRaises(ValueError):
            camelot_code(0, 'dorian')


class CompatibilityTests(SimpleTestCase):
    def test_compatibles_de_8B(self):
        self.assertEqual(compatible_codes('8B'), ['8B', '7B', '9B', '8A'])

    def test_la_rueda_es_circular_al_pasar_de_12_a_1(self):
        self.assertEqual(compatible_codes('12A'), ['12A', '11A', '1A', '12B'])
        self.assertEqual(compatible_codes('1B'), ['1B', '12B', '2B', '1A'])

    def test_compatibilidad_es_simetrica(self):
        codigos = [f"{n}{letra}" for n in range(1, 13) for letra in 'AB']
        for a in codigos:
            for b in codigos:
                with self.subTest(a=a, b=b):
                    self.assertEqual(are_compatible(a, b), are_compatible(b, a))

    def test_cada_codigo_tiene_exactamente_cuatro_compatibles(self):
        for n in range(1, 13):
            for letra in 'AB':
                self.assertEqual(len(set(compatible_codes(f"{n}{letra}"))), 4)

    def test_dos_pasos_no_son_compatibles(self):
        self.assertFalse(are_compatible('8B', '10B'))
        self.assertFalse(are_compatible('8B', '9A'))

    def test_distancia_armonica(self):
        self.assertEqual(harmonic_distance('8B', '8B'), 0)
        self.assertEqual(harmonic_distance('8B', '9B'), 1)
        self.assertEqual(harmonic_distance('8B', '8A'), 1)
        self.assertEqual(harmonic_distance('12A', '1A'), 1)
        self.assertEqual(harmonic_distance('1A', '7A'), 6)
        self.assertEqual(harmonic_distance('8B', '10A'), 3)

    def test_codigo_invalido(self):
        for invalido in ['', '13A', '0B', '8C', 'AB', '8', None]:
            with self.subTest(codigo=invalido):
                with self.assertRaises(ValueError):
                    compatible_codes(invalido)
