"""Authenticated encryption; key creation is an explicit installation action."""
import base64
import hashlib
import json
import os
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException
from database import DATA_DIR

KEY_PATH = Path(DATA_DIR) / "billing.key"


def initialize_key():
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        key_material()
        return
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(AESGCM.generate_key(bit_length=256))
        stream.flush()
        os.fsync(stream.fileno())


def key_material():
    try:
        key = KEY_PATH.read_bytes()
        if len(key) != 32:
            raise ValueError()
        return key, hashlib.sha256(key).hexdigest()[:16]
    except (OSError, ValueError):
        raise HTTPException(503, {"code": "billing_key_unavailable", "message": "资料密钥缺失或损坏，请恢复原密钥备份；不能生成新密钥替代"})


def encrypt(value, entity, field="sensitive"):
    key, key_id = key_material()
    nonce = os.urandom(12)
    aad = f"{entity}:{field}:{key_id}".encode()
    plaintext = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    return base64.b64encode(nonce + AESGCM(key).encrypt(nonce, plaintext, aad)).decode(), key_id


def decrypt(ciphertext, key_id, entity, field="sensitive"):
    key, actual_id = key_material()
    try:
        if key_id != actual_id:
            raise ValueError()
        blob = base64.b64decode(ciphertext, validate=True)
        plaintext = AESGCM(key).decrypt(blob[:12], blob[12:], f"{entity}:{field}:{key_id}".encode())
        return json.loads(plaintext)
    except Exception:
        raise HTTPException(503, {"code": "billing_decrypt_failed", "message": "资料密文无法验证，请核对密钥与备份"})
