import json
from datetime import datetime
from typing import Optional, Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import constr
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from database import get_db
from auth import get_current_user
from permissions import require, has, can_read_customer, related_clause
from audit import write_lock, check_revision, event
import models
import schemas

router = APIRouter(prefix="/api")


def normalize_tax(value):
    return (value or "").strip().upper() or None


def mask_tax(value):
    return (value[:3] + "*" * (len(value) - 7) + value[-4:] if len(value) > 7 else "****" + value[-2:]) if value else None


def minimal(customer):
    return {"id": customer.id, "name": customer.name, "tax_id_masked": mask_tax(customer.tax_id),
            "identity_status": customer.identity_status, "type": customer.type}


def get_customer(db, user, customer_id, billing=False):
    customer = db.get(models.Customer, customer_id)
    if not customer or not can_read_customer(user, customer, db, billing):
        raise HTTPException(404, "客户不存在或不在可见范围内")
    return customer


def commit(db):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, {"code": "duplicate_customer", "message": "税号已有客户档案，请使用精确匹配核对"})


def create_entity(db, data, user):
    customer = models.Customer(name=data.name.strip(), tax_id=normalize_tax(data.tax_id), type=data.type,
                               created_by=user.id, updated_by=user.id)
    if not customer.name:
        raise HTTPException(422, "客户名称不能为空")
    db.add(customer)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "税号已有客户档案，请先匹配")
    return customer


@router.get("/customers/lookup")
def lookup(q: str = Query(..., min_length=2, max_length=200), cursor: int = Query(0, ge=0),
           limit: int = Query(20, ge=1, le=50), db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(user, "customer.lookup")
    rows = db.query(models.Customer).filter(models.Customer.is_active == True,
        models.Customer.identity_status != "merged", models.Customer.id > cursor,
        or_(models.Customer.name.contains(q, autoescape=True),
            models.Customer.aliases.any(models.CustomerAlias.name.contains(q, autoescape=True)))) \
        .order_by(models.Customer.id).limit(limit + 1).all()
    return {"items": [minimal(c) for c in rows[:limit]],
            "next_cursor": rows[limit - 1].id if len(rows) > limit else None}


class TaxMatch(schemas.InputModel):
    tax_id: constr(min_length=1, max_length=50)


@router.post("/customers/match")
def match(data: TaxMatch, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    from http_security import throttle
    require(user, "customer.lookup")
    throttle.consume("tax-match", user.id)
    customer = db.query(models.Customer).filter_by(tax_id=normalize_tax(data.tax_id)).first()
    return {"item": minimal(customer) if customer else None}


@router.get("/customers")
def list_customers(search: Optional[str] = Query(None, max_length=200), page: int = Query(1, ge=1),
                   page_size: int = Query(20, ge=1, le=50), include_disabled: bool = False,
                   db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(user, "customer.read.all")
    query = db.query(models.Customer)
    if not include_disabled:
        query = query.filter_by(is_active=True)
    if search:
        query = query.filter(or_(models.Customer.name.contains(search, autoescape=True),
             models.Customer.aliases.any(models.CustomerAlias.name.contains(search, autoescape=True))))
    return {"items": [schemas.CustomerResponse.from_orm(c) for c in query.order_by(models.Customer.id.desc()).offset((page-1)*page_size).limit(page_size).all()],
            "total": query.count(), "page": page, "page_size": page_size}


@router.get("/customers/{customer_id}")
def detail(customer_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    customer = db.get(models.Customer, customer_id)
    if not customer:
        raise HTTPException(404, '客户不存在')
    full_read = can_read_customer(user, customer, db)
    own = has(user, 'billing.propose.new') and customer.created_by == user.id
    if not full_read and not own:
        raise HTTPException(404, '客户不存在或不在可见范围')
    return {**schemas.CustomerResponse.from_orm(customer).dict(),
            'billing_access': can_read_customer(user, customer, db, billing=True) or own,
            'full_read': full_read}


@router.get('/customers/{customer_id}/changes')
def customer_changes(customer_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    get_customer(db, user, customer_id)
    rows = db.query(models.AuditEvent).filter_by(customer_id=customer_id).filter(models.AuditEvent.action.like('customer.%')).order_by(models.AuditEvent.id.desc()).limit(50).all()
    return [{'action': r.action, 'actor_id': r.actor_id, 'created_at': r.created_at, 'reason': r.reason} for r in rows]


@router.post("/customers", response_model=schemas.CustomerResponse)
def create(data: schemas.CustomerCreate, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(user, "customer.manage")
    write_lock(db)
    customer = create_entity(db, data, user)
    event(db, user, "customer.create", customer, request=request)
    commit(db)
    return customer


def apply_changes(db, user, customer, changes, reason):
    if "tax_id" in changes and normalize_tax(changes["tax_id"]) != customer.tax_id:
        require(user, "customer.correct")
        if not reason:
            raise HTTPException(422, "税号纠错必须填写原因")
        customer.tax_id = normalize_tax(changes.pop("tax_id"))
    else:
        changes.pop("tax_id", None)
    if customer.identity_status == "merged":
        raise HTTPException(409, "已合并客户不能普通编辑")
    if "name" in changes and changes["name"] != customer.name:
        new_name = (changes["name"] or "").strip()
        if not new_name:
            raise HTTPException(422, "名称不能为空")
        if not db.query(models.CustomerAlias.id).filter_by(customer_id=customer.id, name=customer.name).first():
            db.add(models.CustomerAlias(customer_id=customer.id, name=customer.name, valid_to=datetime.utcnow()))
        changes["name"] = new_name
    if any(value is None for value in changes.values()):
        raise HTTPException(422, "字段不能为空")
    for field, value in changes.items():
        setattr(customer, field, value)
    customer.revision += 1
    customer.updated_by = user.id


@router.patch("/customers/{customer_id}", response_model=schemas.CustomerResponse)
def update(customer_id: int, data: schemas.CustomerUpdate, request: Request,
           db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(user, "customer.manage")
    write_lock(db)
    customer = get_customer(db, user, customer_id)
    changes = data.dict(exclude_unset=True, exclude={"expected_revision", "reason"})
    if not changes:
        raise HTTPException(422, {"code": "empty_update", "message": "请提供修改字段"})
    check_revision(customer, data.expected_revision)
    apply_changes(db, user, customer, changes, data.reason)
    event(db, user, "customer.update", customer, reason=data.reason, diff={"fields": sorted(changes)}, request=request)
    commit(db)
    return customer


class Proposal(schemas.InputModel):
    kind: Literal['create', 'update', 'confirm']
    customer_id: Optional[int] = None
    expected_customer_revision: Optional[int] = None
    proposal: schemas.CustomerCreate
    reason: constr(min_length=1, max_length=500)


@router.post("/customer-change-requests")
def propose(data: Proposal, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if not (has(user, "customer.propose") or has(user, "customer.propose.led")):
        raise HTTPException(403, "无权限提交客户申请")
    if data.kind != "create":
        customer = get_customer(db, user, data.customer_id)
        if not has(user, "customer.propose") and not can_read_customer(user, customer, db, billing=True):
            raise HTTPException(404, "客户不在负责范围")
        check_revision(customer, data.expected_customer_revision)
    elif data.customer_id:
        raise HTTPException(422, "新建申请不能指定客户")
    item = models.CustomerChangeRequest(customer_id=data.customer_id, kind=data.kind,
        proposal_json=data.proposal.json(), submitted_by=user.id, reason=data.reason,
        customer_revision=data.expected_customer_revision)
    db.add(item)
    db.flush()
    event(db, user, "customer.propose", item, request=request)
    db.commit()
    return request_response(item)


def request_response(item):
    return {"id": item.id, "customer_id": item.customer_id, "kind": item.kind, "status": item.status,
            "proposal": json.loads(item.proposal_json), "submitted_by": item.submitted_by,
            "revision": item.revision, "reason": item.reason, "created_at": item.created_at}


@router.get("/customer-change-requests")
def requests(page: int = Query(1, ge=1), db: Session = Depends(get_db), user=Depends(get_current_user)):
    query = db.query(models.CustomerChangeRequest)
    if not has(user, "customer.manage"):
        query = query.filter_by(submitted_by=user.id)
    return {"items": [request_response(r) for r in query.order_by(models.CustomerChangeRequest.id.desc()).offset((page-1)*20).limit(20).all()], "total": query.count()}


class Review(schemas.InputModel):
    expected_revision: int
    decision: Literal['approve', 'reject']
    reason: constr(min_length=1, max_length=500)


@router.post("/customer-change-requests/{item_id}/review")
def review(item_id: int, data: Review, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(user, "customer.manage")
    write_lock(db)
    item = db.get(models.CustomerChangeRequest, item_id)
    if not item:
        raise HTTPException(404, "申请不存在")
    check_revision(item, data.expected_revision)
    if item.status != "submitted":
        raise HTTPException(409, "申请已处理")
    if data.decision == "approve":
        proposal = schemas.CustomerCreate.parse_raw(item.proposal_json)
        if item.kind == "create":
            customer = create_entity(db, proposal, user)
            customer.created_by = item.submitted_by
            item.customer_id = customer.id
        else:
            customer = get_customer(db, user, item.customer_id)
            check_revision(customer, item.customer_revision)
            apply_changes(db, user, customer, {"name": proposal.name, "tax_id": proposal.tax_id}, data.reason)
        if customer.type == "enterprise" and not customer.tax_id:
            raise HTTPException(422, "企业主体确认前请补齐税号")
        customer.identity_status = "confirmed"
        customer.revision += 1
    item.status = "approved" if data.decision == "approve" else "rejected"
    item.revision += 1
    item.reviewed_by = user.id
    item.reviewed_at = datetime.utcnow()
    event(db, user, "customer.review", item, reason=data.reason, request=request)
    commit(db)
    return request_response(item)


def resolve_for_project(db, customer_id, tax_id, name, user):
    if customer_id is not None:
        customer = db.get(models.Customer, customer_id)
        if not customer or not customer.is_active or customer.identity_status == "merged":
            raise HTTPException(422, "客户不存在或不可用于新项目")
        return customer
    normalized = normalize_tax(tax_id)
    customer = db.query(models.Customer).filter_by(tax_id=normalized).first() if normalized else None
    if customer:
        if not customer.is_active or customer.identity_status == "merged":
            raise HTTPException(409, "该税号客户已停用或合并")
        return customer
    return create_entity(db, schemas.CustomerCreate(name=name, tax_id=normalized), user)


class Merge(schemas.InputModel):
    target_id: int
    expected_revision: int
    expected_target_revision: int
    reason: constr(min_length=1, max_length=500)
    identity_checked: bool
    dry_run: bool = True


@router.post('/customers/{customer_id}/merge')
def merge(customer_id: int, data: Merge, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(user, 'customer.merge')
    if not data.dry_run:
        write_lock(db)
    source = get_customer(db, user, customer_id)
    target = get_customer(db, user, data.target_id)
    check_revision(source, data.expected_revision); check_revision(target, data.expected_target_revision)
    if source.id == target.id or not source.is_active or not target.is_active or source.identity_status != 'confirmed' or target.identity_status != 'confirmed':
        raise HTTPException(409, '合并需两个不同的启用且已确认主体')
    if source.type != target.type or not data.identity_checked or not data.reason.strip():
        raise HTTPException(422, '请核对双方主体类型和身份并填写合并原因')
    query = db.query(models.Project).filter_by(customer_id=source.id)
    preview = {'source': schemas.CustomerResponse.from_orm(source), 'target': schemas.CustomerResponse.from_orm(target),
               'project_count': query.count(), 'billing_profile_count': db.query(models.BillingProfile.id).filter_by(customer_id=source.id).count(),
               'snapshots_preserved': True}
    if data.dry_run:
        return preview
    for project in query.all():
        project.customer_id = target.id
        project.revision += 1
    if source.name != target.name and not db.query(models.CustomerAlias.id).filter_by(customer_id=target.id, name=source.name).first():
        db.add(models.CustomerAlias(customer_id=target.id, name=source.name))
    source.identity_status = 'merged'; source.is_active = False; source.merged_into_id = target.id
    source.revision += 1; target.revision += 1
    event(db, user, 'customer.merge', source, reason=data.reason, diff={'target_id': target.id, 'project_count': preview['project_count']}, request=request, customer_id=source.id)
    commit(db)
    return {'source_id': source.id, 'target_id': target.id, 'revision': source.revision}
