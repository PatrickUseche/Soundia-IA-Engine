import json

from django.test import TestCase

URL = "/api/mix/calculate"


class CalculateMixViewTests(TestCase):
    def post(self, payload, raw=False):
        body = payload if raw else json.dumps(payload)
        return self.client.post(URL, data=body, content_type="application/json")

    def test_evento_valido_devuelve_decision(self):
        response = self.post({"controlId": 14, "value": 127})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")

    def test_acepta_la_llave_control_id_en_snake_case(self):
        response = self.post({"control_id": 14, "value": 10})

        self.assertEqual(response.status_code, 200)

    def test_valor_cero_es_valido(self):
        response = self.post({"controlId": 14, "value": 0})

        self.assertEqual(response.status_code, 200)

    def test_cuerpo_vacio_devuelve_400(self):
        response = self.post("", raw=True)

        self.assertEqual(response.status_code, 400)

    def test_json_invalido_devuelve_400(self):
        response = self.post("{no es json", raw=True)

        self.assertEqual(response.status_code, 400)

    def test_faltan_llaves_devuelve_400_con_el_payload_leido(self):
        response = self.post({"value": 10})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["payload_leido"], {"value": 10})

    def test_valor_fuera_de_rango_devuelve_400(self):
        response = self.post({"controlId": 14, "value": 200})

        self.assertEqual(response.status_code, 400)

    def test_valor_no_numerico_devuelve_400(self):
        response = self.post({"controlId": 14, "value": "abc"})

        self.assertEqual(response.status_code, 400)

    def test_metodo_get_devuelve_405(self):
        response = self.client.get(URL)

        self.assertEqual(response.status_code, 405)

    def test_json_que_no_es_objeto_devuelve_400(self):
        response = self.post([1, 2, 3])

        self.assertEqual(response.status_code, 400)
