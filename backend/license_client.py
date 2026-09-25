"""业码汇客户端的可选商用授权校验。"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import socket
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from database import DATA_DIR
from version import APP_VERSION


def _version_in_range(version: str, minimum: str | None, maximum: str | None) -> bool:
    def parts(value: str | None) -> tuple[int, ...]:
        if not value:
            return ()
        values = [int(part) for part in value.replace("-", ".").split(".") if part.isdigit()]
        return tuple(values) or (0,)
    current = parts(version)
    return (not minimum or current >= parts(minimum)) and (not maximum or current <= parts(maximum))


def _canonical_json(document: dict[str, Any]) -> bytes:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def instance_fingerprint() -> str:
    raw = "|".join((platform.system(), platform.machine(), socket.gethostname(), hex(uuid.getnode())))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def instance_id() -> str:
    path = DATA_DIR / "license-instance-id"
    if path.exists():
        value = path.read_text(encoding="ascii").strip()
        if value:
            return value
    value = uuid.uuid4().hex
    path.write_text(value + "\n", encoding="ascii")
    return value


def license_required() -> bool:
    return os.getenv("FIRM_MANAGER_LICENSE_REQUIRED", "0").strip().lower() in {"1", "true", "yes", "on"}


def license_file() -> Path:
    return Path(os.getenv("FIRM_MANAGER_LICENSE_FILE", str(DATA_DIR / "license.json"))).expanduser()


def _public_key() -> bytes | None:
    value = os.getenv("FIRM_MANAGER_LICENSE_PUBLIC_KEY", "").strip()
    if not value:
        return None
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError):
        return None


def verify_document(document: dict[str, Any]) -> bool:
    key = _public_key()
    signature = document.get("signature")
    if key is None or not isinstance(signature, str):
        return False
    try:
        signature_bytes = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        unsigned = dict(document)
        unsigned.pop("signature", None)
        Ed25519PublicKey.from_public_bytes(key).verify(signature_bytes, _canonical_json(unsigned))
        return True
    except Exception:
        return False


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def read_document() -> dict[str, Any] | None:
    path = license_file()
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return document if isinstance(document, dict) else None


def status() -> dict[str, Any]:
    if not license_required():
        return {"required": False, "allowed": True, "reason": "开发模式未启用授权强制校验"}
    document = read_document()
    if not document:
        return {"required": True, "allowed": False, "reason": "尚未导入授权文件"}
    if not verify_document(document):
        return {"required": True, "allowed": False, "reason": "授权文件签名无效或未配置公钥"}
    if document.get("product") != os.getenv("LICENSE_PRODUCT_NAME", "业码汇"):
        return {"required": True, "allowed": False, "reason": "授权产品不匹配"}
    document_status = document.get("status")
    if document_status in {"suspended", "revoked"}:
        return {"required": True, "allowed": False, "reason": f"授权当前状态为 {document_status}", "document": document}
    if document_status != "active":
        return {"required": True, "allowed": False, "reason": "授权状态无效", "document": document}
    if not _version_in_range(APP_VERSION, document.get("version_min"), document.get("version_max")):
        return {"required": True, "allowed": False, "reason": "当前业码汇版本不在授权版本范围内", "document": document}
    try:
        now = datetime.now(timezone.utc)
        starts = _parse_utc(str(document["starts_at"]))
        expires = _parse_utc(str(document["expires_at"]))
        grace_until = expires + timedelta(days=int(document.get("grace_days", 0)))
    except (KeyError, TypeError, ValueError):
        return {"required": True, "allowed": False, "reason": "授权文件字段不完整"}
    if now < starts:
        return {"required": True, "allowed": False, "reason": "授权尚未生效", "document": document}
    if now > grace_until:
        return {"required": True, "allowed": False, "reason": "授权已过期且超过宽限期", "document": document}
    return {"required": True, "allowed": True, "reason": "授权有效", "document": document, "expires_at": expires.isoformat(), "grace_until": grace_until.isoformat()}


def save_document(document: dict[str, Any]) -> None:
    if not verify_document(document):
        raise ValueError("授权文件签名无效")
    path = license_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


async def activate(document: dict[str, Any], server_url: str | None = None, instance_name: str | None = None) -> dict[str, Any]:
    if not verify_document(document):
        raise ValueError("授权文件签名无效，请检查 FIRM_MANAGER_LICENSE_PUBLIC_KEY")
    url = (server_url or os.getenv("FIRM_MANAGER_LICENSE_SERVER_URL", "")).rstrip("/")
    if not url:
        raise ValueError("未配置 FIRM_MANAGER_LICENSE_SERVER_URL")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url + "/api/client/activate", json={"license_document": document, "instance_id": instance_id(), "instance_name": instance_name, "fingerprint": instance_fingerprint(), "app_version": APP_VERSION})
    if response.status_code >= 400:
        raise ValueError(response.text)
    save_document(document)
    return response.json()


async def heartbeat(server_url: str | None = None, active_users: int = 0) -> dict[str, Any]:
    document = read_document()
    if not document:
        raise ValueError("尚未导入授权文件")
    url = (server_url or os.getenv("FIRM_MANAGER_LICENSE_SERVER_URL", "")).rstrip("/")
    if not url:
        raise ValueError("未配置 FIRM_MANAGER_LICENSE_SERVER_URL")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url + "/api/client/heartbeat", json={"license_key": document.get("license_id"), "instance_id": instance_id(), "fingerprint": instance_fingerprint(), "active_users": active_users, "app_version": APP_VERSION})
    if response.status_code >= 400:
        raise ValueError(response.text)
    return response.json()
