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


def audio_path_name(storage, file_name):
    campo = type('Campo', (), {'storage': storage})()
    return FieldFile(_Instancia(), campo, file_name)


class LocalAudioPathTests(SimpleTestCase):
    def test_con_disco_da_la_ruta_real_sin_copiar(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            storage = FileSystemStorage(location=folder)
            file_name = storage.save('tracks/a.wav', ContentFile(b'RIFF'))

            with local_audio_path(audio_path_name(storage, file_name)) as file_path:
                self.assertEqual(os.path.normcase(file_path), os.path.normcase(os.path.join(folder, file_name)))

    def test_sin_ruta_descarga_a_un_temporal_con_la_misma_extension(self):
        with local_audio_path(audio_path_name(SoloLecturaStorage(b'datos de audio'), 'tracks/a.mp3')) as file_path:
            self.assertTrue(file_path.endswith('.mp3'))
            with open(file_path, 'rb') as backup_data:
                self.assertEqual(backup_data.read(), b'datos de audio')

    def test_el_temporal_se_borra_al_salir(self):
        with local_audio_path(audio_path_name(SoloLecturaStorage(b'x'), 'a.wav')) as file_path:
            pass
        self.assertFalse(os.path.exists(file_path))

    def test_el_temporal_se_borra_aunque_falle_quien_lo_usa(self):
        with self.assertRaises(RuntimeError):
            with local_audio_path(audio_path_name(SoloLecturaStorage(b'x'), 'a.wav')) as file_path:
                raise RuntimeError('fallo del analisis')
        self.assertFalse(os.path.exists(file_path))
