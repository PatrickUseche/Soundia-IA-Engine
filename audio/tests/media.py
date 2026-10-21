"""Ayuda para las pruebas que guardan archivos: usan una carpeta temporal en lugar de la real."""
import shutil
import tempfile

from django.test import override_settings


class TempMediaMixin:
    """Mezclar con un TestCase: todo lo que se guarde en MEDIA_ROOT va a una carpeta que se borra al terminar."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media_dir = tempfile.mkdtemp(prefix='soundia-media-')
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_dir)
        cls._media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._media_override.disable()
        shutil.rmtree(cls._media_dir, ignore_errors=True)
        super().tearDownClass()
