import asyncio
import json
import os
import unittest

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

os.environ.setdefault("DISCORD_TOKEN", "test-token")

from main import health_check  # noqa: E402


class RenderHealthEndpointTest(unittest.TestCase):
    def test_health_check_returns_render_safe_ok_response(self) -> None:
        response = asyncio.run(health_check(make_mocked_request("GET", "/")))

        self.assertIsInstance(response, web.Response)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, "application/json")

        payload = json.loads(response.text)
        self.assertEqual(payload["service"], "axiom-bot-python")
        self.assertEqual(payload["status"], "ok")


if __name__ == "__main__":
    unittest.main()
