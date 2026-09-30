"""One-time password primitives and an intentionally small SMS adapter seam."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from pathlib import Path

from database import DATA_DIR


def normalize_phone(value: str) -> str:
    phone = "".join(value.strip().split())
    if not phone or not __import__("re").fullmatch(r"\+?[0-9]{6,20}", phone):
        raise ValueError("手机号格式不正确")
    return phone


def _secret() -> bytes:
    configured = os.getenv("FIRM_MANAGER_OTP_SECRET") or os.getenv("FIRM_MANAGER_SECRET_KEY")
    if configured:
        return configured.encode("utf-8")
    path = DATA_DIR / "otp_secret"
    if path.exists():
        return path.read_bytes()
    value = secrets.token_bytes(32)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(value)
    return value


def generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_code(phone: str, code: str) -> str:
    return hmac.new(_secret(), f"{phone}:{code}".encode("utf-8"), hashlib.sha256).hexdigest()


def send_sms_code(phone: str, code: str) -> str:
    """Return delivery status; replace this adapter with the chosen SMS provider.

    No provider is configured by default, so the code is never returned to the API
    client. Deployment can wire a provider around this function without changing
    the OTP storage or login contract.
    """
    log_path = os.getenv("FIRM_MANAGER_OTP_LOG")
    if log_path:
        with Path(log_path).open("a", encoding="utf-8") as output:
            output.write(f"{phone}\n")
    return "not_configured"
