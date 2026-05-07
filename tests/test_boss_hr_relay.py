import unittest

from fastapi.testclient import TestClient

from python import boss_hr_relay_service
from python.boss_hr_relay_connector import build_ws_url, handle_message


class BossHrRelayTests(unittest.TestCase):
    def setUp(self):
        boss_hr_relay_service.RELAY_TOKEN = "test-token"
        boss_hr_relay_service.sessions.clear()

    def test_build_ws_url_from_https_relay(self):
        url = build_ws_url("https://relay.example.com/base", "user-1", "secret token")

        self.assertEqual(url, "wss://relay.example.com/base/v1/connect/user-1?token=secret+token")

    def test_relay_status_requires_token(self):
        client = TestClient(boss_hr_relay_service.app)
        response = client.get("/v1/sessions/user-1/status")

        self.assertEqual(response.status_code, 401)

    def test_relay_status_reports_missing_session(self):
        client = TestClient(boss_hr_relay_service.app)
        response = client.get("/v1/sessions/user-1/status", headers={"x-boss-relay-token": "test-token"})

        self.assertEqual(response.status_code, 404)
        self.assertIn("session not connected", response.text)

    def test_connector_response_preserves_request_id(self):
        import python.boss_hr_relay_connector as connector

        original = connector.perform_local_request
        try:
            message = {"id": "abc", "method": "GET", "path": "/health"}

            def fake_request(local_base_url, method, path, json_body=None):
                return {"status_code": 200, "body": {"ok": True}, "text": ""}

            connector.perform_local_request = fake_request
            response = handle_message(message, "http://127.0.0.1:8790")
        finally:
            connector.perform_local_request = original

        self.assertEqual(response["id"], "abc")
        self.assertEqual(response["response"]["body"], {"ok": True})


if __name__ == "__main__":
    unittest.main()
