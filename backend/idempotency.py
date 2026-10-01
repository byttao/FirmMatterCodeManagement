import hashlib
import json
from fastapi import HTTPException
import models


def lookup(db, user, operation, key, payload):
    if not key or not 8 <= len(key) <= 100 or not key.isascii():
        raise HTTPException(422, "请提交8至100位Idempotency-Key")
    payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    record = db.get(models.IdempotencyRecord, (user.id, operation, key))
    if record and record.payload_hash != payload_hash:
        raise HTTPException(409, {"code": "idempotency_conflict", "message": "同一幂等键不能用于不同内容"})
    return json.loads(record.result_json) if record else None, payload_hash


def remember(db, user, operation, key, payload_hash, result):
    db.add(models.IdempotencyRecord(actor_id=user.id, operation=operation, key=key,
           payload_hash=payload_hash, result_json=json.dumps(result, default=str)))
