from unittest import mock

from django.test import SimpleTestCase

from audio import separator


class SeparatorAvailabilityTests(SimpleTestCase):
    def test_sin_demucs_instalado_no_esta_disponible(self):
        with mock.patch.object(separator.importlib.util, 'find_spec', return_value=None):
            self.assertFalse(separator.is_available())

    def test_con_demucs_y_torch_instalados_esta_disponible(self):
        with mock.patch.object(separator.importlib.util, 'find_spec', return_value=object()):
            self.assertTrue(separator.is_available())

    def test_separar_sin_el_modelo_instalado_lo_explica(self):
        with mock.patch.object(separator, 'is_available', return_value=False):
            with self.assertRaises(separator.VocalSeparationUnavailable):
                separator.separate_vocals(mock.Mock())
