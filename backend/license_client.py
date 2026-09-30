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
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import HTTPException

from database import DATA_DIR, SessionLocal
import models
from version import APP_VERSION


# These codes are part of the signed license contract. Keep labels in the
# authorization center, while the client only relies on stable codes.
LICENSE_FEATURE_CODES = {
    "project_management",
    "project_assignment",
    "business_number",
    "signatory_review",
    "invoice_registration",
    "payment_registration",
    "user_management",
    "fiscal_year_settings",
    "data_export",
}

TRIAL_LIMITS = {"fiscal_years": 1, "practitioners": 3, "projects": 3}


def trial_mode() -> bool:
    """Release packages opt into a local trial when no signed license exists."""
    return os.getenv("FIRM_MANAGER_TRIAL_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}


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
    path = license_file().with_name("license-instance-id")
    if path.exists():
        value = path.read_text(encoding="ascii").strip()
        if value:
            return value
    value = uuid.uuid4().hex
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value + "\n", encoding="ascii")
    return value


def active_user_count() -> int:
    db = SessionLocal()
    try:
        return db.query(models.User).filter_by(
            is_active=True,
            role=models.UserRole.PRACTITIONER.value,
        ).count()
    finally:
        db.close()


def license_required() -> bool:
    return os.getenv("FIRM_MANAGER_LICENSE_REQUIRED", "0").strip().lower() in {"1", "true", "yes", "on"}


def license_file() -> Path:
    return Path(os.getenv("FIRM_MANAGER_LICENSE_FILE", str(DATA_DIR / "license.json"))).expanduser()


def license_server_url_file() -> Path:
    return license_file().with_name("license-server-url.txt")


def _normalize_server_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    if (parsed.scheme not in {"http", "https"} or not parsed.netloc
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("授权服务器地址必须是 http 或 https URL，且不能包含账号密码")
    return normalized


def configured_server_url(server_url: str | None = None) -> str:
    if server_url and server_url.strip():
        return _normalize_server_url(server_url)
    value = os.getenv("FIRM_MANAGER_LICENSE_SERVER_URL", "")
    if value.strip():
        return _normalize_server_url(value)
    path = license_server_url_file()
    if path.exists():
        saved = path.read_text(encoding="utf-8").strip()
        if saved:
            return _normalize_server_url(saved)
    raise ValueError("未配置 FIRM_MANAGER_LICENSE_SERVER_URL")


def save_server_url(server_url: str) -> None:
    path = license_server_url_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(_normalize_server_url(server_url) + "\n", encoding="utf-8")
    temporary.replace(path)


def remote_block_file() -> Path:
    return license_file().with_name("license-remote-block.json")


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
        if trial_mode():
            return {
                "required": False,
                "allowed": True,
                "mode": "trial",
                "reason": "当前为试用模式",
                "limits": TRIAL_LIMITS.copy(),
            }
        return {"required": False, "allowed": True, "mode": "development", "reason": "开发模式未启用授权强制校验"}
    document = read_document()
    if not document:
        return {"required": True, "allowed": False, "reason": "尚未导入授权文件"}
    if not verify_document(document):
        return {"required": True, "allowed": False, "reason": "授权文件签名无效或未配置公钥"}
    blocked_path = remote_block_file()
    if blocked_path.exists():
        try:
            block = json.loads(blocked_path.read_text(encoding="utf-8"))
            if block.get("license_id") == document.get("license_id"):
                return {"required": True, "allowed": False, "reason": block.get("reason", "授权服务器拒绝当前实例"), "document": document}
        except (OSError, ValueError):
            pass
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
        if document.get("license_type") == "perpetual":
            if now < starts:
                return {"required": True, "allowed": False, "reason": "授权尚未生效", "document": document}
            return {"required": True, "allowed": True, "reason": "永久授权有效", "document": document}
        expires = _parse_utc(str(document["expires_at"]))
        grace_until = expires + timedelta(days=int(document.get("grace_days", 0)))
    except (KeyError, TypeError, ValueError):
        return {"required": True, "allowed": False, "reason": "授权文件字段不完整"}
    if now < starts:
        return {"required": True, "allowed": False, "reason": "授权尚未生效", "document": document}
    if now > grace_until:
        return {"required": True, "allowed": False, "reason": "授权已过期且超过宽限期", "document": document}
    return {"required": True, "allowed": True, "reason": "授权有效", "document": document, "expires_at": expires.isoformat(), "grace_until": grace_until.isoformat()}


def license_features() -> set[str] | None:
    """Return licensed feature codes; None means a legacy unrestricted file."""
    current = status()
    document = current.get("document") or {}
    features = document.get("features")
    if features is None:
        return None
    if not isinstance(features, list):
        return set()
    return {str(item) for item in features if str(item) in LICENSE_FEATURE_CODES}


def has_license_feature(feature: str) -> bool:
    if not license_required():
        return True
    current = status()
    if not current.get("allowed"):
        return False
    features = license_features()
    return features is None or feature in features


def require_license_feature(feature: str) -> None:
    """Enforce a module gate after the global license middleware has run."""
    if not license_required():
        return
    current = status()
    if not current.get("allowed"):
        raise HTTPException(status_code=402, detail=current.get("reason", "授权不可用"))
    if not has_license_feature(feature):
        raise HTTPException(
            status_code=403,
            detail={"code": "feature_not_licensed", "feature": feature, "message": "当前授权未包含此功能模块"},
        )


def save_document(document: dict[str, Any]) -> None:
    if not verify_document(document):
        raise ValueError("授权文件签名无效")
    path = license_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    remote_block_file().unlink(missing_ok=True)


def _record_remote_block(document: dict[str, Any], reason: str) -> None:
    path = remote_block_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"license_id": document.get("license_id"), "reason": reason}, ensure_ascii=False) + "\n", encoding="utf-8")


def _is_terminal_heartbeat_denial(status_code: int, detail: Any) -> bool:
    if status_code in {404, 409}:
        return True
    if isinstance(detail, dict):
        return status_code == 403 and detail.get("code") in {
            "activation_not_found",
            "license_expired",
            "license_unavailable",
            "version_not_allowed",
        }
    return status_code == 403 and detail in {"授权不可用", "服务器实例未激活"}


def _decode_license_file(value: str) -> dict[str, Any]:
    document = json.loads(base64.b64decode(value, validate=True).decode("utf-8"))
    if not isinstance(document, dict):
        raise ValueError("授权服务器返回的许可证文件格式无效")
    return document


def _response_detail(response: httpx.Response) -> Any:
    try:
        payload = response.json()
    except ValueError:
        return response.text
    if not isinstance(payload, dict):
        return payload
    return payload.get("detail", payload)


async def activate(document: dict[str, Any], server_url: str | None = None, instance_name: str | None = None) -> dict[str, Any]:
    if not verify_document(document):
        raise ValueError("授权文件签名无效，请检查 FIRM_MANAGER_LICENSE_PUBLIC_KEY")
    license_key = document.get("license_id")
    if not isinstance(license_key, str) or not license_key.strip():
        raise ValueError("授权文件缺少授权编号")
    # A signed license carries the control-plane address so a customer can
    # replace the server URL by importing a freshly issued license file.
    url = configured_server_url(server_url or document.get("server_url"))
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url + "/api/v1/activate", json={
            "authorization_code": license_key,
            "product_code": document.get("product_code", "YMH-FMC"),
            "hardware_fingerprint": instance_fingerprint(),
            "instance_id": instance_id(),
            "device_info": instance_name,
            "software_version": APP_VERSION,
        })
    if response.status_code >= 400:
        detail = _response_detail(response)
        message = detail.get("message", detail) if isinstance(detail, dict) else detail
        raise ValueError(str(message))
    result = response.json()
    configured_key = _public_key()
    returned_key = result.get("public_key")
    try:
        returned_key_bytes = base64.urlsafe_b64decode(returned_key + "=" * (-len(returned_key) % 4))
    except (TypeError, ValueError):
        raise ValueError("授权服务器未返回有效公钥") from None
    if configured_key is None or returned_key_bytes != configured_key:
        raise ValueError("授权服务器公钥与当前业码汇版本不匹配")
    encoded_document = result.get("license_file")
    if not isinstance(encoded_document, str):
        raise ValueError("授权服务器未返回许可证文件")
    current_document = _decode_license_file(encoded_document)
    if not isinstance(current_document, dict) or current_document.get("license_id") != document.get("license_id"):
        raise ValueError("授权服务器返回的许可证与导入文件不匹配")
    save_document(current_document)
    save_server_url(url)
    return result


async def heartbeat(server_url: str | None = None, active_users: int | None = None) -> dict[str, Any]:
    document = read_document()
    if not document:
        raise ValueError("尚未导入授权文件")
    url = configured_server_url(server_url or document.get("server_url"))
    if active_users is None:
        active_users = active_user_count()
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url + "/api/v1/heartbeat", json={"license_key": document.get("license_id"), "instance_id": instance_id(), "hardware_fingerprint": instance_fingerprint(), "active_users": active_users, "software_version": APP_VERSION})
    if response.status_code >= 400:
        detail = _response_detail(response)
        if _is_terminal_heartbeat_denial(response.status_code, detail):
            message = detail.get("message", str(detail)) if isinstance(detail, dict) else str(detail)
            _record_remote_block(document, message)
        message = detail.get("message", detail) if isinstance(detail, dict) else detail
        raise ValueError(str(message))
    result = response.json()
    encoded_document = result.get("license_file")
    if not isinstance(encoded_document, str):
        raise ValueError("授权服务器未返回许可证文件")
    updated_document = _decode_license_file(encoded_document)
    if updated_document.get("license_id") != document.get("license_id"):
        raise ValueError("授权服务器返回的许可证与当前授权不匹配")
    save_document(updated_document)
    return result
