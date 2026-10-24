from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from soundia_ai.dburl import database_from_url


class DatabaseFromUrlTests(SimpleTestCase):
    def test_lee_servidor_base_usuario_y_clave(self):
        db = database_from_url('postgresql://dj:secreta@ep-algo.neon.tech:5432/soundia')
        self.assertEqual(db['ENGINE'], 'django.db.backends.postgresql')
        self.assertEqual(
            (db['HOST'], db['PORT'], db['NAME'], db['USER'], db['PASSWORD']),
            ('ep-algo.neon.tech', '5432', 'soundia', 'dj', 'secreta'))

    def test_acepta_el_esquema_postgres(self):
        self.assertEqual(database_from_url('postgres://u:p@h/b')['NAME'], 'b')

    def test_decodifica_caracteres_especiales_de_la_clave(self):
        self.assertEqual(database_from_url('postgresql://u:a%40b%2Fc@h/b')['PASSWORD'], 'a@b/c')

    def test_pasa_las_opciones_de_la_consulta(self):
        db = database_from_url('postgresql://u:p@h/b?sslmode=require')
        self.assertEqual(db['OPTIONS'], {'sslmode': 'require'})

    def test_sin_opciones_no_agrega_options(self):
        self.assertNotIn('OPTIONS', database_from_url('postgresql://u:p@h/b'))

    def test_sin_puerto_deja_el_puerto_vacio(self):
        self.assertEqual(database_from_url('postgresql://u:p@h/b')['PORT'], '')

    def test_rechaza_otro_esquema(self):
        with self.assertRaises(ImproperlyConfigured):
            database_from_url('mysql://u:p@h/b')

    def test_rechaza_una_url_sin_base(self):
        with self.assertRaises(ImproperlyConfigured):
            database_from_url('postgresql://u:p@h')
