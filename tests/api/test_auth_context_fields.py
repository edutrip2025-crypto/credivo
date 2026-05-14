import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import get_settings

os.environ.setdefault("DATABASE_URL", "sqlite:///./certora.db")
get_settings.cache_clear()

from app.main import app  # noqa: E402


class AuthContextFieldsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    @patch("app.api.routes.auth._safe_sync_claims")
    @patch("app.api.routes.auth.verify_firebase_token")
    def test_me_context_returns_phone_number_and_full_name(self, mock_verify, _mock_sync) -> None:
        mock_verify.return_value = {
            "uid": "ctx-user-001",
            "email": "ctx.user.001@example.com",
            "phone_number": "+919876543210",
            "name": "Context User",
            "role": "student",
            "approval_status": "approved",
        }
        res = self.client.get(
            "/auth/me/context",
            headers={"Authorization": "Bearer fake-id-token"},
        )
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        self.assertIn("full_name", payload)
        self.assertIn("phone_number", payload)
        self.assertEqual(payload.get("full_name"), "Context User")
        self.assertEqual(payload.get("phone_number"), "+919876543210")


if __name__ == "__main__":
    unittest.main()
