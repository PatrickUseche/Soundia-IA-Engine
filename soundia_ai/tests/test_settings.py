"""La configuracion depende de variables de entorno: cada caso carga los ajustes en un proceso nuevo con el
entorno indicado, para no contaminar la configuracion del proceso de pruebas."""
import json
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

PROYECTO = Path(__file__).resolve().parents[2]

# Lee los ajustes en un proceso aparte y los devuelve como JSON.
_PROGRAMA = (
    "import json, django.conf as c; s = c.settings; "
    "print(json.dumps({'DEBUG': s.DEBUG, 'SECRET_KEY': s.SECRET_KEY, 'ALLOWED_HOSTS': s.ALLOWED_HOSTS, "
    "'SQLITE': str(s.DATABASES['default']['NAME']), 'MEDIA_ROOT': str(s.MEDIA_ROOT), "
    "'MAX_UPLOAD': s.AUDIO_MAX_UPLOAD_BYTES}))"
)


def cargar(**entorno):
    """Carga los ajustes con SOLO estas variables de entorno (mas lo imprescindible para ejecutar Python)."""
    base = {k: v for k, v in os.environ.items() if k in ('SYSTEMROOT', 'PATH', 'PYTHONPATH', 'TEMP', 'TMP')}
    base['DJANGO_SETTINGS_MODULE'] = 'soundia_ai.settings'
    base.update(entorno)
    resultado = subprocess.run(
        [sys.executable, '-I', '-c', "import sys; sys.path.insert(0, %r); %s" % (str(PROYECTO), _PROGRAMA)],
        capture_output=True, text=True, env=base, cwd=str(PROYECTO),
    )
    return resultado


def ajustes(**entorno):
    resultado = cargar(**entorno)
    assert resultado.returncode == 0, resultado.stderr
    return json.loads(resultado.stdout.strip().splitlines()[-1])


class DebugYClaveTests(SimpleTestCase):
    def test_por_defecto_es_un_entorno_de_desarrollo(self):
        a = ajustes()

        self.assertTrue(a['DEBUG'])
        self.assertIn('desarrollo', a['SECRET_KEY'])

    def test_debug_se_puede_apagar_con_la_variable(self):
        for valor in ('False', 'false', '0', 'no'):
            with self.subTest(valor=valor):
                self.assertFalse(ajustes(DJANGO_DEBUG=valor, DJANGO_SECRET_KEY='x')['DEBUG'])

    def test_debug_acepta_varias_formas_de_verdadero(self):
        for valor in ('True', 'true', '1', 'yes'):
            with self.subTest(valor=valor):
                self.assertTrue(ajustes(DJANGO_DEBUG=valor)['DEBUG'])

    def test_la_clave_secreta_sale_del_entorno(self):
        self.assertEqual(ajustes(DJANGO_SECRET_KEY='clave-de-prueba')['SECRET_KEY'], 'clave-de-prueba')

    def test_sin_debug_la_clave_secreta_es_obligatoria(self):
        resultado = cargar(DJANGO_DEBUG='False')

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn('DJANGO_SECRET_KEY', resultado.stderr)

    def test_con_debug_apagado_y_clave_arranca(self):
        a = ajustes(DJANGO_DEBUG='False', DJANGO_SECRET_KEY='secreta')

        self.assertFalse(a['DEBUG'])
        self.assertEqual(a['SECRET_KEY'], 'secreta')


class HostsTests(SimpleTestCase):
    def test_por_defecto_solo_localhost(self):
        self.assertEqual(ajustes()['ALLOWED_HOSTS'], ['localhost', '127.0.0.1'])

    def test_se_pueden_indicar_varios_hosts_con_espacios(self):
        a = ajustes(DJANGO_ALLOWED_HOSTS='ia-engine, localhost ,midominio.com')

        self.assertEqual(a['ALLOWED_HOSTS'], ['ia-engine', 'localhost', 'midominio.com'])

    def test_ignora_elementos_vacios(self):
        self.assertEqual(ajustes(DJANGO_ALLOWED_HOSTS='a.com,,b.com,')['ALLOWED_HOSTS'], ['a.com', 'b.com'])


class RutasYLimitesTests(SimpleTestCase):
    def test_por_defecto_la_base_sqlite_esta_en_la_raiz_del_proyecto(self):
        self.assertEqual(Path(ajustes()['SQLITE']), PROYECTO / 'db.sqlite3')

    def test_la_ruta_de_sqlite_se_puede_mover_a_un_volumen(self):
        self.assertEqual(Path(ajustes(SQLITE_PATH='/data/db.sqlite3')['SQLITE']), Path('/data/db.sqlite3'))

    def test_por_defecto_el_audio_se_guarda_en_media_dentro_del_proyecto(self):
        self.assertEqual(Path(ajustes()['MEDIA_ROOT']), PROYECTO / 'media')

    def test_la_carpeta_de_audio_se_puede_mover_a_un_volumen(self):
        self.assertEqual(Path(ajustes(MEDIA_ROOT='/data/media')['MEDIA_ROOT']), Path('/data/media'))

    def test_el_limite_de_subida_por_defecto_es_50_mb(self):
        self.assertEqual(ajustes()['MAX_UPLOAD'], 50 * 1024 * 1024)

    def test_el_limite_de_subida_se_puede_cambiar(self):
        self.assertEqual(ajustes(AUDIO_MAX_UPLOAD_BYTES='1000')['MAX_UPLOAD'], 1000)
