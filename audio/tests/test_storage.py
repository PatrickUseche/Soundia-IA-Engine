import os

from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage, Storage
from django.db.models.fields.files import FieldFile
from django.test import SimpleTestCase

from audio.storage import local_audio_path


class SoloLecturaStorage(Storage):
    """Un almacenamiento sin ruta de disco, como S3: solo sabe abrir por nombre."""

    def __init__(self, contenido):
        self.contenido = contenido

    def _open(self, name, mode='rb'):
        return ContentFile(self.contenido, name=name)

    def path(self, name):
        raise NotImplementedError('Este almacenamiento no tiene rutas de disco.')


class _Instancia:
    pass


def archivo(storage, nombre):
    campo = type('Campo', (), {'storage': storage})()
    return FieldFile(_Instancia(), campo, nombre)


class LocalAudioPathTests(SimpleTestCase):
    def test_con_disco_da_la_ruta_real_sin_copiar(self):
        import tempfile
        with tempfile.TemporaryDirectory() as carpeta:
            storage = FileSystemStorage(location=carpeta)
            nombre = storage.save('tracks/a.wav', ContentFile(b'RIFF'))

            with local_audio_path(archivo(storage, nombre)) as ruta:
                self.assertEqual(os.path.normcase(ruta), os.path.normcase(os.path.join(carpeta, nombre)))

    def test_sin_ruta_descarga_a_un_temporal_con_la_misma_extension(self):
        with local_audio_path(archivo(SoloLecturaStorage(b'datos de audio'), 'tracks/a.mp3')) as ruta:
            self.assertTrue(ruta.endswith('.mp3'))
            with open(ruta, 'rb') as copia:
                self.assertEqual(copia.read(), b'datos de audio')

    def test_el_temporal_se_borra_al_salir(self):
        with local_audio_path(archivo(SoloLecturaStorage(b'x'), 'a.wav')) as ruta:
            pass
        self.assertFalse(os.path.exists(ruta))

    def test_el_temporal_se_borra_aunque_falle_quien_lo_usa(self):
        with self.assertRaises(RuntimeError):
            with local_audio_path(archivo(SoloLecturaStorage(b'x'), 'a.wav')) as ruta:
                raise RuntimeError('fallo del analisis')
        self.assertFalse(os.path.exists(ruta))
