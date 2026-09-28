import base64
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class LicenseClientStatusTest(unittest.TestCase):
    def test_active_user_count_uses_enabled_practitioners(self):
        from license_client import active_user_count

        session = Mock()
        session.query.return_value.filter_by.return_value.count.return_value = 4
        with patch("license_client.SessionLocal", return_value=session):
            self.assertEqual(active_user_count(), 4)
        session.query.return_value.filter_by.assert_called_once_with(
            is_active=True,
            role="practitioner",
        )
        session.close.assert_called_once_with()

    def test_status_must_be_active(self):
        from license_client import _canonical_json, status

        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        now = datetime.now(timezone.utc)
        base = {
            "schema_version": 1,
            "license_id": "YMH-TEST",
            "product": "业码汇",
            "status": "active",
            "starts_at": (now - timedelta(days=1)).isoformat(),
            "expires_at": (now + timedelta(days=30)).isoformat(),
            "grace_days": 0,
        }

        with TemporaryDirectory() as data_dir:
            old_values = {
                key: os.environ.get(key)
                for key in (
                    "FIRM_MANAGER_LICENSE_REQUIRED",
                    "FIRM_MANAGER_LICENSE_PUBLIC_KEY",
                    "FIRM_MANAGER_LICENSE_FILE",
                )
            }
            try:
                os.environ["FIRM_MANAGER_LICENSE_REQUIRED"] = "1"
                os.environ["FIRM_MANAGER_LICENSE_PUBLIC_KEY"] = base64.urlsafe_b64encode(public_key).decode().rstrip("=")
                os.environ["FIRM_MANAGER_LICENSE_FILE"] = str(Path(data_dir) / "license.json")
                for document_status, expected in (("active", True), ("suspended", False), ("revoked", False)):
                    unsigned = {**base, "status": document_status}
                    signed = {
                        **unsigned,
                        "signature": base64.urlsafe_b64encode(
                            private_key.sign(_canonical_json(unsigned))
                        ).decode().rstrip("="),
                    }
                    Path(os.environ["FIRM_MANAGER_LICENSE_FILE"]).write_text(
                        json.dumps(signed), encoding="utf-8"
                    )
                    self.assertEqual(status()["allowed"], expected, document_status)
            finally:
                for key, value in old_values.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

    def test_terminal_heartbeat_denial_blocks_until_reactivation(self):
        from license_client import _canonical_json, heartbeat, status

        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        now = datetime.now(timezone.utc)
        unsigned = {
            "schema_version": 1,
            "license_id": "YMH-HEARTBEAT",
            "product": "业码汇",
            "status": "active",
            "starts_at": (now - timedelta(days=1)).isoformat(),
            "expires_at": (now + timedelta(days=30)).isoformat(),
            "grace_days": 0,
        }
        signed = {
            **unsigned,
            "signature": base64.urlsafe_b64encode(private_key.sign(_canonical_json(unsigned))).decode().rstrip("="),
        }

        class Response:
            status_code = 403
            text = '{"detail":{"code":"license_unavailable","message":"授权不可用"}}'

            @staticmethod
            def json():
                return {"detail": {"code": "license_unavailable", "message": "授权不可用"}}

        with TemporaryDirectory() as data_dir:
            old_values = {key: os.environ.get(key) for key in ("FIRM_MANAGER_LICENSE_REQUIRED", "FIRM_MANAGER_LICENSE_PUBLIC_KEY", "FIRM_MANAGER_LICENSE_FILE", "FIRM_MANAGER_LICENSE_SERVER_URL")}
            try:
                os.environ["FIRM_MANAGER_LICENSE_REQUIRED"] = "1"
                os.environ["FIRM_MANAGER_LICENSE_PUBLIC_KEY"] = base64.urlsafe_b64encode(public_key).decode().rstrip("=")
                os.environ["FIRM_MANAGER_LICENSE_FILE"] = str(Path(data_dir) / "license.json")
                os.environ["FIRM_MANAGER_LICENSE_SERVER_URL"] = "https://license.example.test"
                Path(os.environ["FIRM_MANAGER_LICENSE_FILE"]).write_text(json.dumps(signed), encoding="utf-8")
                with patch("license_client.httpx.AsyncClient") as client_factory:
                    client = client_factory.return_value
                    client.__aenter__ = AsyncMock(return_value=client)
                    client.__aexit__ = AsyncMock(return_value=None)
                    client.post = AsyncMock(return_value=Response())
                    with self.assertRaises(ValueError):
                        import asyncio
                        asyncio.run(heartbeat(active_users=0))
                self.assertFalse(status()["allowed"])
                self.assertIn("授权不可用", status()["reason"])
            finally:
                for key, value in old_values.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

    def test_activation_persists_server_url_for_future_heartbeats(self):
        from license_client import _canonical_json, activate, heartbeat, license_server_url_file

        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        now = datetime.now(timezone.utc)
        unsigned = {
            "schema_version": 1,
            "license_id": "YMH-PERSIST",
            "product": "业码汇",
            "status": "active",
            "starts_at": (now - timedelta(days=1)).isoformat(),
            "expires_at": (now + timedelta(days=30)).isoformat(),
            "grace_days": 0,
        }
        signed = {
            **unsigned,
            "signature": base64.urlsafe_b64encode(private_key.sign(_canonical_json(unsigned))).decode().rstrip("="),
        }

        class Response:
            status_code = 200
            text = "{}"

            @staticmethod
            def json():
                return {
                    "license_file": base64.b64encode(json.dumps(signed).encode("utf-8")).decode("ascii"),
                    "public_key": base64.urlsafe_b64encode(public_key).decode("ascii").rstrip("="),
                    "instance_id": "instance-from-server",
                }

        with TemporaryDirectory() as data_dir:
            old_values = {key: os.environ.get(key) for key in ("FIRM_MANAGER_LICENSE_PUBLIC_KEY", "FIRM_MANAGER_LICENSE_FILE", "FIRM_MANAGER_LICENSE_SERVER_URL")}
            try:
                os.environ["FIRM_MANAGER_LICENSE_PUBLIC_KEY"] = base64.urlsafe_b64encode(public_key).decode().rstrip("=")
                os.environ["FIRM_MANAGER_LICENSE_FILE"] = str(Path(data_dir) / "license.json")
                os.environ.pop("FIRM_MANAGER_LICENSE_SERVER_URL", None)
                with patch("license_client.httpx.AsyncClient") as client_factory:
                    client = client_factory.return_value
                    client.__aenter__ = AsyncMock(return_value=client)
                    client.__aexit__ = AsyncMock(return_value=None)
                    client.post = AsyncMock(return_value=Response())
                    import asyncio
                    asyncio.run(activate(signed, "https://license.example.test/", "测试实例"))
                    asyncio.run(heartbeat(active_users=2))
                self.assertEqual(license_server_url_file().read_text(encoding="utf-8").strip(), "https://license.example.test")
                self.assertTrue(Path(os.environ["FIRM_MANAGER_LICENSE_FILE"]).with_name("license-instance-id").exists())
                self.assertEqual(client.post.await_count, 2)
                self.assertEqual(client.post.await_args_list[0].args[0], "https://license.example.test/api/v1/activate")
                self.assertEqual(client.post.await_args_list[1].args[0], "https://license.example.test/api/v1/heartbeat")
                self.assertEqual(client.post.await_args_list[0].kwargs["json"]["authorization_code"], "YMH-PERSIST")
                self.assertEqual(client.post.await_args_list[1].kwargs["json"]["instance_id"], Path(data_dir, "license-instance-id").read_text(encoding="ascii").strip())
            finally:
                for key, value in old_values.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

    def test_activation_rejects_server_key_mismatch(self):
        from license_client import _canonical_json, activate

        signing_key = Ed25519PrivateKey.generate()
        unexpected_key = Ed25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        public_key = signing_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        now = datetime.now(timezone.utc)
        unsigned = {
            "schema_version": 1,
            "license_id": "YMH-KEY-MISMATCH",
            "product": "业码汇",
            "status": "active",
            "starts_at": (now - timedelta(days=1)).isoformat(),
            "expires_at": (now + timedelta(days=30)).isoformat(),
            "grace_days": 0,
        }
        signed = {
            **unsigned,
            "signature": base64.urlsafe_b64encode(signing_key.sign(_canonical_json(unsigned))).decode().rstrip("="),
        }

        class Response:
            status_code = 200
            text = "{}"

            @staticmethod
            def json():
                return {
                    "license_file": base64.b64encode(json.dumps(signed).encode("utf-8")).decode("ascii"),
                    "public_key": base64.urlsafe_b64encode(unexpected_key).decode("ascii").rstrip("="),
                }

        with TemporaryDirectory() as data_dir:
            old_values = {key: os.environ.get(key) for key in ("FIRM_MANAGER_LICENSE_PUBLIC_KEY", "FIRM_MANAGER_LICENSE_FILE")}
            try:
                os.environ["FIRM_MANAGER_LICENSE_PUBLIC_KEY"] = base64.urlsafe_b64encode(public_key).decode("ascii").rstrip("=")
                os.environ["FIRM_MANAGER_LICENSE_FILE"] = str(Path(data_dir) / "license.json")
                with patch("license_client.httpx.AsyncClient") as client_factory:
                    client = client_factory.return_value
                    client.__aenter__ = AsyncMock(return_value=client)
                    client.__aexit__ = AsyncMock(return_value=None)
                    client.post = AsyncMock(return_value=Response())
                    import asyncio
                    with self.assertRaisesRegex(ValueError, "公钥与当前业码汇版本不匹配"):
                        asyncio.run(activate(signed, "https://license.example.test"))
                self.assertFalse(Path(os.environ["FIRM_MANAGER_LICENSE_FILE"]).exists())
            finally:
                for key, value in old_values.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

    def test_successful_heartbeat_refreshes_renewed_document_and_clears_remote_block(self):
        from license_client import _canonical_json, heartbeat, status

        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        now = datetime.now(timezone.utc)
        original = {
            "schema_version": 1,
            "license_id": "YMH-RENEW",
            "product": "业码汇",
            "status": "active",
            "starts_at": (now - timedelta(days=60)).isoformat(),
            "expires_at": (now - timedelta(days=30)).isoformat(),
            "grace_days": 0,
        }
        renewed = {
            **original,
            "expires_at": (now + timedelta(days=365)).isoformat(),
        }
        original["signature"] = base64.urlsafe_b64encode(private_key.sign(_canonical_json(original))).decode().rstrip("=")
        renewed["signature"] = base64.urlsafe_b64encode(private_key.sign(_canonical_json(renewed))).decode().rstrip("=")

        class Response:
            status_code = 200
            text = "{}"

            @staticmethod
            def json():
                return {
                    "status": "active",
                    "license_file": base64.b64encode(json.dumps(renewed).encode("utf-8")).decode("ascii"),
                }

        with TemporaryDirectory() as data_dir:
            old_values = {key: os.environ.get(key) for key in ("FIRM_MANAGER_LICENSE_REQUIRED", "FIRM_MANAGER_LICENSE_PUBLIC_KEY", "FIRM_MANAGER_LICENSE_FILE", "FIRM_MANAGER_LICENSE_SERVER_URL")}
            try:
                os.environ["FIRM_MANAGER_LICENSE_REQUIRED"] = "1"
                os.environ["FIRM_MANAGER_LICENSE_PUBLIC_KEY"] = base64.urlsafe_b64encode(public_key).decode().rstrip("=")
                os.environ["FIRM_MANAGER_LICENSE_FILE"] = str(Path(data_dir) / "license.json")
                os.environ["FIRM_MANAGER_LICENSE_SERVER_URL"] = "https://license.example.test"
                Path(os.environ["FIRM_MANAGER_LICENSE_FILE"]).write_text(json.dumps(original), encoding="utf-8")
                Path(data_dir, "license-remote-block.json").write_text(json.dumps({"license_id": "YMH-RENEW", "reason": "授权不可用"}), encoding="utf-8")
                with patch("license_client.httpx.AsyncClient") as client_factory:
                    client = client_factory.return_value
                    client.__aenter__ = AsyncMock(return_value=client)
                    client.__aexit__ = AsyncMock(return_value=None)
                    client.post = AsyncMock(return_value=Response())
                    import asyncio
                    asyncio.run(heartbeat(active_users=0))
                saved = json.loads(Path(os.environ["FIRM_MANAGER_LICENSE_FILE"]).read_text(encoding="utf-8"))
                self.assertEqual(saved["expires_at"], renewed["expires_at"])
                self.assertFalse(Path(data_dir, "license-remote-block.json").exists())
                self.assertTrue(status()["allowed"])
            finally:
                for key, value in old_values.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
