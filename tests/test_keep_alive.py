import unittest

from keep_alive import app


class KeepAliveRoutesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = app.test_client()

    def test_health_routes_return_ok(self) -> None:
        for route in ("/health", "/healthz", "/ping"):
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
                self.assertIsInstance(payload, dict)
                self.assertEqual(payload.get("status"), "ok")
                self.assertEqual(payload.get("bot"), "Axiom")


if __name__ == "__main__":
    unittest.main()
