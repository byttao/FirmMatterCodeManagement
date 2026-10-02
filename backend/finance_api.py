import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.orm import Session
from database import get_db
from auth import get_current_user, can_view_project
from permissions import require, can_read_customer
from audit import write_lock, check_revision, event
from idempotency import lookup, remember
from finance import cents, refresh_project_finance
from data_crypto import encrypt, decrypt
from billing import payload
import models
import schemas

router = APIRouter(prefix='/api/projects')


def project_entity(db, user, project_id):
    query = db.query(models.Project).filter_by(is_deleted=False)
    project = query.filter(models.Project.id == int(project_id) if project_id.isdigit() else models.Project.project_id == project_id).first()
    if not project or not can_view_project(user, project):
        raise HTTPException(404, '项目不存在或不在可见范围')
    return project


def kind_code(kind):
    if kind not in ('invoices', 'receipts'):
        raise HTTPException(404, '财务类型不存在')
    return 'invoice' if kind == 'invoices' else 'receipt'


def entry_entity(db, project, kind, entry_id):
    entry = db.query(models.FinancialEntry).filter_by(id=entry_id, project_id=project.id, kind=kind_code(kind)).first()
    if not entry:
        raise HTTPException(404, '财务记录不存在')
    return entry


@router.get('/{project_id}/finance/{kind}')
def list_entries(project_id: str, kind: str, page: int = Query(1, ge=1), db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(user, 'finance.read.all')
    project = project_entity(db, user, project_id)
    query = db.query(models.FinancialEntry).filter_by(project_id=project.id, kind=kind_code(kind))
    return {'items': [schemas.FinancialEntryResponse.from_orm(e) for e in query.order_by(models.FinancialEntry.occurred_on.desc(), models.FinancialEntry.id.desc()).offset((page-1)*50).limit(50).all()], 'total': query.count(), 'page': page}


@router.post('/{project_id}/finance/{kind}', response_model=schemas.FinancialEntryResponse)
def create_entry(project_id: str, kind: str, data: schemas.FinancialEntryCreate, request: Request,
                 db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(user, 'finance.write')
    write_lock(db)
    project = project_entity(db, user, project_id)
    code = kind_code(kind)
    operation = f'finance.{code}:{project.id}'
    key = request.headers.get('Idempotency-Key')
    prior, payload_hash = lookup(db, user, operation, key, data.dict())
    if prior:
        return entry_entity(db, project, kind, prior['entry_id'])
    check_revision(project, data.expected_project_revision)
    if data.replacement_of_id:
        original = entry_entity(db, project, kind, data.replacement_of_id)
        if not original.voided_at or db.query(models.FinancialEntry.id).filter_by(replacement_of_id=original.id).first():
            raise HTTPException(409, '替换记录必须引用尚未替换的已作废原记录')
    values = None
    if code == 'invoice':
        customer = db.get(models.Customer, project.customer_id)
        if not customer or not customer.is_active or customer.identity_status != 'confirmed':
            raise HTTPException(409, '客户未确认或已停用，请先核对主体')
        profile = db.get(models.BillingProfile, data.billing_profile_id) if data.billing_profile_id else None
        version = db.get(models.BillingVersion, data.billing_version_id) if data.billing_version_id else None
        if not profile or not version or profile.customer_id != project.customer_id or version.profile_id != profile.id:
            raise HTTPException(422, '请选择本项目客户的开票档案和版本')
        check_revision(profile, data.expected_profile_revision)
        if not profile.is_active or profile.current_verified_version_id != version.id or version.status != 'verified':
            raise HTTPException(409, '确认版本已变化或档案不可用，请重新核对')
        values = payload(version)
    elif any(v is not None for v in (data.billing_profile_id, data.billing_version_id, data.expected_profile_revision)):
        raise HTTPException(422, '收款不绑定开票资料')
    entry = record_entry(db, user, project, code, data, request, profile if values is not None else None,
                         version if values is not None else None)
    remember(db, user, operation, key, payload_hash, {'entry_id': entry.id})
    db.commit()
    return entry


def record_entry(db, user, project, code, data, request, profile=None, version=None, snapshot_customer_id=None):
    """同事务创建流水/不可变快照并聚合；普通入口继续严格校验当前版本。"""
    values = None
    if code == 'invoice':
        customer_id = snapshot_customer_id or project.customer_id
        if not profile or not version or version.profile_id != profile.id or profile.customer_id != customer_id:
            raise HTTPException(422, '开票资料所属关系不一致')
        if not version.verified_at or version.status not in ('verified', 'superseded'):
            raise HTTPException(409, '只能使用已经财务核验的开票资料')
        values = payload(version)
    entry = models.FinancialEntry(project_id=project.id, kind=code, amount_cents=cents(data.amount),
        occurred_on=data.occurred_on, reference=data.reference, note=data.note, created_by=user.id,
        replacement_of_id=data.replacement_of_id)
    db.add(entry); db.flush()
    if values is not None:
        from billing import SENSITIVE_FIELDS
        encrypted, key_id = encrypt({k: v for k, v in values.items() if k in SENSITIVE_FIELDS}, f'invoice-snapshot-entry:{entry.id}')
        snapshot = models.InvoiceSnapshot(financial_entry_id=entry.id, customer_id=customer_id,
            profile_id=profile.id, version_id=version.id, actor_id=user.id,
            public_json=json.dumps({**{k: v for k, v in values.items() if k not in SENSITIVE_FIELDS},
                'version_no': version.version_no, 'verified_by': version.verified_by, 'verified_at': version.verified_at.isoformat()}, ensure_ascii=False),
            sensitive_ciphertext=encrypted, key_id=key_id)
        db.add(snapshot)
    db.flush()
    refresh_project_finance(db, project)
    project.revision += 1
    event(db, user, f'finance.{code}.create', entry, request=request, project_id=project.id, customer_id=project.customer_id)
    return entry


@router.post('/{project_id}/finance/{kind}/{entry_id}/void', response_model=schemas.FinancialEntryResponse)
def void_entry(project_id: str, kind: str, entry_id: int, data: schemas.ReasonRequest, request: Request,
               db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(user, 'finance.void')
    write_lock(db)
    project = project_entity(db, user, project_id)
    entry = entry_entity(db, project, kind, entry_id)
    check_revision(entry, data.expected_revision)
    if entry.voided_at:
        raise HTTPException(409, '该记录已作废')
    if not data.reason.strip():
        raise HTTPException(422, '必须填写作废原因')
    entry.voided_at = datetime.utcnow(); entry.voided_by = user.id; entry.void_reason = data.reason; entry.revision += 1
    db.flush(); refresh_project_finance(db, project); project.revision += 1
    event(db, user, f'finance.{kind}.void', entry, reason=data.reason, request=request, project_id=project.id)
    db.commit()
    return entry


@router.get('/{project_id}/finance/invoices/{entry_id}/billing-snapshot')
def snapshot(project_id: str, entry_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    project = project_entity(db, user, project_id)
    entry_entity(db, project, 'invoices', entry_id)
    customer = db.get(models.Customer, project.customer_id)
    if not customer or not (can_read_customer(user, customer, db, billing=True) and (project.leader_id == user.id or 'billing.read.all' in user.permissions)):
        raise HTTPException(404, '快照不存在或无权读取')
    item = db.query(models.InvoiceSnapshot).filter_by(financial_entry_id=entry_id).first()
    if not item:
        raise HTTPException(404, '快照不存在')
    sensitive = decrypt(item.sensitive_ciphertext, item.key_id, f'invoice-snapshot-entry:{item.financial_entry_id}')
    event(db, user, 'invoice_snapshot.reveal', item, reason='读取历史开票资料', project_id=project.id, customer_id=item.customer_id)
    db.commit()
    return {'fields': {**json.loads(item.public_json), **sensitive}, 'version_id': item.version_id, 'created_at': item.created_at, 'actor_id': item.actor_id}
