import json
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from database import get_db
from auth import get_current_user
from permissions import require
import models

router = APIRouter(prefix='/api')


@router.get('/audit-events')
def events(page: int = Query(1, ge=1), target_type: str | None = Query(None, max_length=32),
           target_id: str | None = Query(None, max_length=100), customer_id: int | None = None, action: str | None = Query(None, max_length=64),
           db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(user, 'audit.read')
    query = db.query(models.AuditEvent)
    for field, value in ((models.AuditEvent.target_type, target_type), (models.AuditEvent.target_id, target_id), (models.AuditEvent.customer_id, customer_id), (models.AuditEvent.action, action)):
        if value is not None:
            query = query.filter(field == value)
    rows = query.order_by(models.AuditEvent.id.desc()).offset((page-1)*50).limit(50).all()
    return {'items': [{'id': r.id, 'actor_id': r.actor_id, 'action': r.action, 'target_type': r.target_type,
        'target_id': r.target_id, 'project_id': r.project_id, 'customer_id': r.customer_id, 'reason': r.reason,
        'request_id': r.request_id, 'diff': json.loads(r.redacted_diff), 'created_at': r.created_at} for r in rows], 'total': query.count()}
