import json
from datetime import datetime
from typing import Optional, Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import constr, validator
from sqlalchemy import func
from sqlalchemy.orm import Session
from database import get_db
from auth import get_current_user
from permissions import has, require, can_read_customer
from audit import write_lock, check_revision, event
from customers import get_customer, normalize_tax
from data_crypto import encrypt, decrypt
import models
import schemas

router = APIRouter(prefix="/api")
SENSITIVE_FIELDS = {"registered_address", "registered_phone", "bank_name", "bank_account", "contact_name", "recipient_phone", "recipient_email", "note"}


class BillingFields(schemas.InputModel):
    buyer_type: Optional[Literal['enterprise', 'individual', 'overseas']] = None
    title: Optional[constr(min_length=1, max_length=200)] = None
    tax_id: Optional[constr(max_length=50)] = None
    registered_address: Optional[constr(max_length=300)] = None
    registered_phone: Optional[constr(max_length=50)] = None
    bank_name: Optional[constr(max_length=200)] = None
    bank_account: Optional[constr(max_length=64)] = None
    contact_name: Optional[constr(max_length=100)] = None
    recipient_phone: Optional[constr(max_length=50)] = None
    recipient_email: Optional[constr(max_length=254)] = None
    invoice_preference: Literal['normal', 'special', 'other', 'unspecified'] = 'unspecified'
    note: Optional[constr(max_length=1000)] = None

    @validator('recipient_email')
    def email_valid(cls, value):
        import re
        if value and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("收票邮箱格式无效")
        return value or None

    @validator('bank_account')
    def bank_valid(cls, value):
        if value and (not value.isascii() or not value.isdigit() or len(value) < 8):
            raise ValueError("银行账号需为数字字符串，保留前导零")
        return value or None


class ProfileCreate(schemas.InputModel):
    label: constr(min_length=1, max_length=50) = '默认开票资料'
    is_default: bool = False
    fields: BillingFields


class VersionCreate(schemas.InputModel):
    expected_profile_revision: int
    fields: BillingFields


class VersionUpdate(schemas.InputModel):
    expected_revision: int
    fields: BillingFields


class Verification(schemas.InputModel):
    expected_revision: int
    expected_profile_revision: int
    decision: Literal['approve', 'reject']
    verification_note: constr(min_length=1, max_length=500)


class Reveal(schemas.InputModel):
    purpose: constr(min_length=1, max_length=200)


class ProfileUpdate(schemas.InputModel):
    expected_revision: int
    label: Optional[constr(min_length=1, max_length=50)] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None


def can_propose(user, customer, db):
    return has(user, 'billing.manage') or (has(user, 'billing.propose.led') and can_read_customer(user, customer, db, billing=True)) or (has(user, 'billing.propose.new') and customer.created_by == user.id)


def profile_entity(db, profile_id):
    profile = db.get(models.BillingProfile, profile_id)
    if not profile:
        raise HTTPException(404, "开票档案不存在")
    customer = db.get(models.Customer, profile.customer_id)
    return profile, customer


def version_entity(db, user, version_id, editing=False):
    version = db.get(models.BillingVersion, version_id)
    if not version:
        raise HTTPException(404, "开票版本不存在")
    profile, customer = profile_entity(db, version.profile_id)
    allowed = can_read_customer(user, customer, db, billing=True)
    own_draft = version.submitted_by == user.id and version.status in ('draft', 'submitted', 'rejected') and can_propose(user, customer, db)
    if not allowed and not own_draft:
        raise HTTPException(404, "开票版本不存在或不在可见范围")
    if editing and not (has(user, 'billing.manage') or own_draft):
        raise HTTPException(403, "无权限修改该草稿")
    return version, profile, customer


def version_response(version):
    return {"id": version.id, "profile_id": version.profile_id, "version_no": version.version_no,
            "status": version.status, "fields": json.loads(version.public_json), "bank_last4": version.bank_last4,
            "revision": version.revision, "submitted_by": version.submitted_by, "verified_by": version.verified_by,
            "verification_note": version.verification_note, "submitted_at": version.submitted_at, "verified_at": version.verified_at}


def profile_response(db, profile):
    versions = db.query(models.BillingVersion).filter_by(profile_id=profile.id).order_by(models.BillingVersion.version_no.desc()).all()
    return {"id": profile.id, "customer_id": profile.customer_id, "label": profile.label, "is_active": profile.is_active,
            "is_default": profile.is_default, "revision": profile.revision, "current_verified_version_id": profile.current_verified_version_id,
            "versions": [version_response(v) for v in versions]}


def payload(version):
    return {**json.loads(version.public_json), **decrypt(version.sensitive_ciphertext, version.key_id, f"billing-version:{version.id}")}


def save_payload(version, fields):
    values = BillingFields.parse_obj(fields).dict()
    version.public_json = json.dumps({k: v for k, v in values.items() if k not in SENSITIVE_FIELDS}, ensure_ascii=False)
    version.sensitive_ciphertext, version.key_id = encrypt({k: v for k, v in values.items() if k in SENSITIVE_FIELDS}, f"billing-version:{version.id}")
    account = values.get('bank_account')
    version.bank_last4 = account[-4:] if account else None


def create_version(db, user, profile, customer, fields):
    number = (db.query(func.max(models.BillingVersion.version_no)).filter_by(profile_id=profile.id).scalar() or 0) + 1
    values = fields.dict()
    values['title'] = values['title'] or customer.name
    values['tax_id'] = normalize_tax(values['tax_id']) or customer.tax_id
    values['buyer_type'] = values['buyer_type'] or customer.type
    version = models.BillingVersion(profile_id=profile.id, version_no=number, submitted_by=user.id,
        public_json='{}', sensitive_ciphertext='', key_id='')
    db.add(version); db.flush()
    save_payload(version, values)
    event(db, user, "billing.draft_create", version, customer_id=customer.id)
    return version


@router.get('/customers/{customer_id}/billing-profiles')
def profiles(customer_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    customer = db.get(models.Customer, customer_id)
    if not customer:
        raise HTTPException(404, '客户不存在')
    full_read = can_read_customer(user, customer, db, billing=True)
    if not full_read and not can_propose(user, customer, db):
        raise HTTPException(404, '客户不存在或不在可见范围')
    result = []
    for profile in db.query(models.BillingProfile).filter_by(customer_id=customer_id).order_by(models.BillingProfile.id).all():
        response = profile_response(db, profile)
        if not full_read:
            response['versions'] = [v for v in response['versions'] if v['submitted_by'] == user.id and v['status'] in ('draft', 'submitted', 'rejected')]
            response['current_verified_version_id'] = None
        if full_read or response['versions']:
            result.append(response)
    return result


@router.post('/customers/{customer_id}/billing-profiles')
def create_profile(customer_id: int, data: ProfileCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    write_lock(db)
    customer = db.get(models.Customer, customer_id)
    if not customer or not can_propose(user, customer, db):
        raise HTTPException(404, "客户不存在或无权提交开票资料")
    if not customer.is_active or customer.identity_status == 'merged':
        raise HTTPException(409, "客户已停用或合并")
    if data.is_default:
        require(user, 'billing.manage')
        if db.query(models.BillingProfile.id).filter_by(customer_id=customer.id, is_active=True, is_default=True).first():
            raise HTTPException(409, "该客户已有默认开票档案")
    profile = models.BillingProfile(customer_id=customer.id, label=data.label.strip(), is_default=data.is_default, created_by=user.id)
    db.add(profile); db.flush()
    create_version(db, user, profile, customer, data.fields)
    db.commit()
    return profile_response(db, profile)


@router.post('/billing-profiles/{profile_id}/versions')
def new_version(profile_id: int, data: VersionCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    write_lock(db)
    profile, customer = profile_entity(db, profile_id)
    if not can_propose(user, customer, db):
        raise HTTPException(404, "无权提交该客户开票资料")
    check_revision(profile, data.expected_profile_revision)
    if not profile.is_active or not customer.is_active or customer.identity_status == 'merged':
        raise HTTPException(409, "档案或客户已停用")
    version = create_version(db, user, profile, customer, data.fields)
    profile.revision += 1
    db.commit()
    return version_response(version)


@router.patch('/billing-profiles/{profile_id}')
def profile_update(profile_id: int, data: ProfileUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(user, 'billing.manage')
    write_lock(db)
    profile, customer = profile_entity(db, profile_id)
    check_revision(profile, data.expected_revision)
    changes = data.dict(exclude_unset=True, exclude={'expected_revision'})
    if not changes:
        raise HTTPException(422, {'code': 'empty_update', 'message': '请提交修改字段'})
    if any(v is None for v in changes.values()):
        raise HTTPException(422, '档案字段不能为空')
    if changes.get('is_default'):
        for other in db.query(models.BillingProfile).filter_by(customer_id=customer.id, is_default=True).filter(models.BillingProfile.id != profile.id).all():
            other.is_default = False; other.revision += 1
        db.flush()
    for field, value in changes.items():
        setattr(profile, field, value)
    profile.revision += 1
    event(db, user, 'billing.profile_update', profile, diff={'fields': sorted(changes)}, customer_id=customer.id)
    db.commit()
    return profile_response(db, profile)


@router.get('/billing-versions/{version_id}')
def version_detail(version_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    version, _, _ = version_entity(db, user, version_id)
    return version_response(version)


@router.patch('/billing-versions/{version_id}')
def update_version(version_id: int, data: VersionUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    write_lock(db)
    version, profile, customer = version_entity(db, user, version_id, editing=True)
    if version.status != 'draft':
        raise HTTPException(409, "已提交或确认资料不可修改，请创建新版本")
    check_revision(version, data.expected_revision)
    changes = data.fields.dict(exclude_unset=True)
    if not changes:
        raise HTTPException(422, {"code": "empty_update", "message": "请提交修改字段"})
    save_payload(version, {**payload(version), **changes})
    version.revision += 1
    event(db, user, 'billing.draft_update', version, diff={"fields": sorted(changes)}, customer_id=customer.id)
    db.commit()
    return version_response(version)


@router.post('/billing-versions/{version_id}/submit')
def submit(version_id: int, data: schemas.RevisionRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    write_lock(db)
    version, _, customer = version_entity(db, user, version_id, editing=True)
    check_revision(version, data.expected_revision)
    if version.status != 'draft':
        raise HTTPException(409, "只有草稿可提交")
    version.status = 'submitted'; version.revision += 1; version.submitted_at = datetime.utcnow()
    event(db, user, 'billing.submit', version, customer_id=customer.id)
    db.commit()
    return version_response(version)


@router.post('/billing-versions/{version_id}/verify')
def verify(version_id: int, data: Verification, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(user, 'billing.verify')
    write_lock(db)
    version, profile, customer = version_entity(db, user, version_id)
    check_revision(version, data.expected_revision); check_revision(profile, data.expected_profile_revision)
    if version.status not in ('draft', 'submitted'):
        raise HTTPException(409, "该版本已核验")
    values = payload(version)
    if data.decision == 'approve':
        if customer.identity_status != 'confirmed' or not customer.is_active:
            raise HTTPException(409, "请先确认客户主体")
        if values['title'] != customer.name or normalize_tax(values.get('tax_id')) != customer.tax_id or values['buyer_type'] != customer.type:
            raise HTTPException(409, "开票主体与客户主档不一致，请由管理员核对客户身份；不能使用第三方抬头")
        if profile.current_verified_version_id:
            previous = db.get(models.BillingVersion, profile.current_verified_version_id)
            old = payload(previous)
            changed_identity = any(values.get(k) != old.get(k) for k in ('tax_id', 'buyer_type'))
            if changed_identity:
                require(user, 'customer.correct')
            previous.status = 'superseded'
        version.status = 'verified'; version.verified_by = user.id; version.verified_at = datetime.utcnow()
        version.verification_note = data.verification_note
        db.flush()
        profile.current_verified_version_id = version.id
        profile.revision += 1
    else:
        version.status = 'rejected'; version.verification_note = data.verification_note
        version.verified_by = user.id; version.verified_at = datetime.utcnow()
    version.revision += 1
    event(db, user, 'billing.verify', version, reason=data.verification_note, diff={"decision": data.decision}, customer_id=customer.id)
    db.commit()
    return {"version": version_response(version), "profile_revision": profile.revision}


@router.post('/billing-versions/{version_id}/verification-preview')
def verification_preview(version_id: int, data: Reveal, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(user, 'billing.verify')
    version, profile, customer = version_entity(db, user, version_id)
    if version.status not in ('draft', 'submitted'):
        raise HTTPException(409, '该版本已核验')
    current = payload(version)
    previous = payload(db.get(models.BillingVersion, profile.current_verified_version_id)) if profile.current_verified_version_id else {}
    event(db, user, 'billing.review_preview', version, reason=data.purpose, customer_id=customer.id)
    db.commit()
    return {'fields': current, 'changes': [{'field': k, 'before': previous.get(k), 'after': v} for k, v in current.items() if previous.get(k) != v]}


@router.post('/billing-versions/{version_id}/reveal')
def reveal(version_id: int, data: Reveal, db: Session = Depends(get_db), user=Depends(get_current_user)):
    version, _, customer = version_entity(db, user, version_id)
    if not can_read_customer(user, customer, db, billing=True) and not (version.submitted_by == user.id and version.status == 'draft'):
        raise HTTPException(404, "无权读取开票资料")
    values = payload(version)
    event(db, user, 'billing.reveal', version, reason=data.purpose, customer_id=customer.id)
    db.commit()
    labels = {'title': '抬头', 'tax_id': '税号', 'registered_address': '地址', 'registered_phone': '电话', 'bank_name': '开户银行', 'bank_account': '银行账号', 'contact_name': '联系人', 'recipient_phone': '收票电话', 'recipient_email': '收票邮箱'}
    return {"fields": values, "copy_text": '\n'.join(f'{label}：{values[key]}' for key, label in labels.items() if values.get(key))}


@router.get('/billing-worklist')
def worklist(status: str = Query('submitted', regex='^(draft|submitted|verified|rejected)$'), page: int = Query(1, ge=1),
             db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(user, 'billing.manage')
    query = db.query(models.BillingVersion).filter_by(status=status)
    rows = query.order_by(models.BillingVersion.id.desc()).offset((page-1)*20).limit(20).all()
    return {'items': [{**version_response(v), 'customer_id': db.get(models.BillingProfile, v.profile_id).customer_id} for v in rows], 'total': query.count()}
