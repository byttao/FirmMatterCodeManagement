import base64
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class LicenseClientStatusTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
