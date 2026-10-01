import json
from fastapi import HTTPException
from sqlalchemy import text
import models


def write_lock(db):
    db.execute(text("BEGIN IMMEDIATE"))
    db.expire_all()


def check_revision(entity, expected):
    if expected is None:
        raise HTTPException(422, {"code": "revision_required", "message": "请提交当前修订号"})
    if entity.revision != expected:
        raise HTTPException(409, {"code": "revision_conflict", "message": "资料已被他人修改，请刷新核对；当前草稿尚未保存", "current_revision": entity.revision})


def event(db, user, action, entity, reason=None, diff=None, request=None, project_id=None, customer_id=None):
    if customer_id is None:
        customer_id = entity.id if entity.__tablename__ == 'customers' else getattr(entity, 'customer_id', None)
    db.add(models.AuditEvent(actor_id=user.id, action=action, target_type=entity.__tablename__,
                             target_id=entity.id, reason=reason, project_id=project_id, customer_id=customer_id,
                             request_id=getattr(getattr(request, "state", None), "request_id", None) or db.info.get("request_id"),
                             redacted_diff=json.dumps(diff or {}, ensure_ascii=False)))
