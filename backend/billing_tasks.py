"""按任务办理开票；后勤提交结果，财务在同一事务确认流水和历史快照。"""
import json
import secrets
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import condecimal, constr
from sqlalchemy.orm import Session
from database import get_db
from auth import get_current_user
from audit import write_lock, check_revision, event
from billing import payload, version_response
from finance import cents
from finance_api import record_entry
from idempotency import lookup, remember
from permissions import has, require
import models
import schemas

router = APIRouter(prefix='/api/billing-tasks')


class Create(schemas.InputModel):
    project_id: int
    customer_id: int
    billing_profile_id: int
    billing_version_id: int
    assignee_id: int
    amount: condecimal(gt=0, max_digits=12, decimal_places=2)
    note: constr(max_length=500) = ''


class Action(schemas.InputModel):
    expected_revision: int
    reason: constr(strip_whitespace=True, min_length=1, max_length=500)


class Reassign(Action):
    assignee_id: int
    amount: Optional[condecimal(gt=0, max_digits=12, decimal_places=2)] = None


class Revalidate(Action):
    billing_profile_id: int
    billing_version_id: int


class Result(schemas.InputModel):
    expected_revision: int
    amount: condecimal(gt=0, max_digits=12, decimal_places=2)
    invoice_number: constr(strip_whitespace=True, min_length=1, max_length=100)
    invoice_date: date
    note: constr(max_length=500) = ''


class Confirm(Action):
    expected_project_revision: int
    confirm_historical: bool = False
    financial_entry_id: Optional[int] = None


class Reveal(schemas.InputModel):
    purpose: constr(strip_whitespace=True, min_length=1, max_length=100)


def assignee(db, user_id):
    user = db.get(models.User, user_id)
    if not user or not user.is_active or 'clerk' not in user.roles:
        raise HTTPException(422, '办理人须为启用且具有后勤角色的账号')
    return user


def entities(db, task):
    return (db.get(models.Project, task.project_id), db.get(models.Customer, task.customer_id),
            db.get(models.BillingProfile, task.billing_profile_id), db.get(models.BillingVersion, task.billing_version_id))


def current_valid(db, task):
    project, customer, profile, version = entities(db, task)
    return bool(project and not project.is_deleted and customer and customer.is_active
        and customer.identity_status == 'confirmed' and not customer.merged_into_id
        and customer.revision == task.customer_revision and project.customer_id == customer.id
        and profile and profile.is_active and profile.customer_id == customer.id
        and version and version.profile_id == profile.id and version.status == 'verified'
        and version.verified_at and profile.current_verified_version_id == version.id)


def visible(db, user, task_id):
    task = db.get(models.BillingTask, task_id)
    if not task or not (has(user, 'billing_task.read.all') or
        has(user, 'billing_task.read.assigned') and task.assignee_id == user.id):
        raise HTTPException(404, '任务不存在或不在可见范围')
    return task


def result_response(item):
    return {'id': item.id, 'task_revision': item.task_revision, 'billing_version_id': item.billing_version_id,
        'submitted_by': item.submitted_by, 'amount': f'{item.amount_cents / 100:.2f}',
        'invoice_number': item.invoice_number, 'invoice_date': item.invoice_date,
        'note': item.note, 'created_at': item.created_at}


def response(db, task, user):
    project, customer, profile, version = entities(db, task)
    valid = current_valid(db, task)
    public = json.loads(version.public_json) if version else {}
    answer = {'id': task.id, 'revision': task.revision,
        'status': 'needs_review' if task.status == 'assigned' and not valid else task.status,
        'project_id': task.project_id, 'project_number': project.report_no or project.project_id if project else '',
        'customer_id': task.customer_id, 'customer_name': customer.name if customer else '',
        'title': public.get('title'), 'tax_id': public.get('tax_id'),
        'billing_profile_id': task.billing_profile_id, 'billing_version_id': task.billing_version_id,
        'version_no': version.version_no if version else None,
        'current_version_id': profile.current_verified_version_id if profile else None,
        'historical_difference': not valid, 'bank_last4': version.bank_last4 if version else None,
        'assignee_id': task.assignee_id, 'amount': f'{task.amount_cents / 100:.2f}', 'note': task.note,
        'reason': task.reason, 'created_at': task.created_at, 'assigned_at': task.assigned_at,
        'submitted_at': task.submitted_at, 'completed_at': task.completed_at, 'revoked_at': task.revoked_at,
        'financial_entry_id': task.financial_entry_id}
    result = db.get(models.BillingTaskResult, task.submitted_result_id) if task.submitted_result_id else None
    answer['result'] = result_response(result) if result else None
    if has(user, 'billing_task.read.all'):
        answer['result_history'] = [result_response(item) for item in db.query(models.BillingTaskResult)
            .filter_by(task_id=task.id).order_by(models.BillingTaskResult.id).all()]
    return answer


def audit(db, user, action, task, request, reason=None, diff=None):
    event(db, user, 'billing_task.'+action, task, reason=reason, request=request,
          project_id=task.project_id, customer_id=task.customer_id,
          diff={'version_id': task.billing_version_id, **(diff or {})})


def ensure_assigned(db, user, task, request):
    require(user, 'billing_task.reveal.assigned')
    if not has(user, 'billing_task.manage') and (task.assignee_id != user.id or 'clerk' not in user.roles):
        raise HTTPException(404, '任务不存在或不在可见范围')
    if task.status != 'assigned':
        raise HTTPException(409, '任务已关闭、已提交或需重新核对，不能继续读取或办理')
    assignee(db, task.assignee_id)
    if not current_valid(db, task):
        task.status = 'needs_review'; task.revision += 1
        audit(db, user, 'needs_review', task, request, '项目或已核验资料发生变化')
        db.commit()
        raise HTTPException(409, '资料或所属关系已变化，请财务核对任务版本')


def checked_creation(db, data):
    project = db.get(models.Project, data.project_id)
    customer = db.get(models.Customer, data.customer_id)
    profile = db.get(models.BillingProfile, data.billing_profile_id)
    version = db.get(models.BillingVersion, data.billing_version_id)
    if not project or project.is_deleted or not customer or project.customer_id != customer.id:
        raise HTTPException(422, '项目与客户所属关系不一致')
    if not customer.is_active or customer.identity_status != 'confirmed' or customer.merged_into_id:
        raise HTTPException(409, '客户已停用、合并或尚未确认')
    if not profile or not version or profile.customer_id != customer.id or version.profile_id != profile.id:
        raise HTTPException(422, '请选择本项目客户的开票档案和版本')
    if not profile.is_active or profile.current_verified_version_id != version.id or version.status != 'verified' or not version.verified_at:
        raise HTTPException(409, '请选择当前已核验开票版本')
    assignee(db, data.assignee_id)
    return customer


@router.get('')
def listing(status: Optional[str] = None, owner: Optional[int] = None, page: int = Query(1, ge=1),
            limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), user=Depends(get_current_user)):
    query = db.query(models.BillingTask)
    if not has(user, 'billing_task.read.all'):
        require(user, 'billing_task.read.assigned')
        query = query.filter_by(assignee_id=user.id)
    elif owner is not None:
        query = query.filter_by(assignee_id=owner)
    if status:
        if status not in ('assigned','result_submitted','completed','revoked','needs_review'):
            raise HTTPException(422, '任务状态无效')
        query = query.filter_by(status=status)
    return {'items': [response(db, task, user) for task in query.order_by(models.BillingTask.created_at.desc(),
        models.BillingTask.id.desc()).offset((page-1)*limit).limit(limit).all()], 'total': query.count(), 'page': page}


@router.get('/assignees')
def assignees(db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(user, 'billing_task.manage')
    return [{'id': u.id, 'name': u.real_name} for u in db.query(models.User).filter(models.User.is_active.is_(True),
        models.User.role_records.any(models.UserRoleRecord.role_code == 'clerk')).order_by(models.User.id).all()]


@router.get('/{task_id}')
def detail(task_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return response(db, visible(db, user, task_id), user)


@router.post('')
def create(data: Create, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(user, 'billing_task.manage'); write_lock(db)
    key = request.headers.get('Idempotency-Key')
    prior, digest = lookup(db, user, 'billing_task.create', key, data.dict())
    if prior:
        return response(db, visible(db, user, prior['task_id']), user)
    customer = checked_creation(db, data)
    task = models.BillingTask(id=secrets.token_hex(16), project_id=data.project_id, customer_id=data.customer_id,
        customer_revision=customer.revision, billing_profile_id=data.billing_profile_id,
        billing_version_id=data.billing_version_id, assignee_id=data.assignee_id, created_by=user.id,
        amount_cents=cents(data.amount), note=data.note)
    db.add(task); db.flush(); audit(db, user, 'assign', task, request, data.note, {'assignee_id': task.assignee_id})
    remember(db, user, 'billing_task.create', key, digest, {'task_id': task.id}); db.commit()
    return response(db, task, user)


@router.post('/{task_id}/reveal')
def reveal(task_id: str, data: Reveal, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    write_lock(db); task = visible(db, user, task_id); ensure_assigned(db, user, task, request)
    version = db.get(models.BillingVersion, task.billing_version_id); values = payload(version)
    audit(db, user, 'reveal', task, request, data.purpose); db.commit()
    labels = {'title':'抬头','tax_id':'税号','registered_address':'地址','registered_phone':'电话',
              'bank_name':'开户银行','bank_account':'银行账号','contact_name':'联系人',
              'recipient_phone':'收票电话','recipient_email':'收票邮箱'}
    required = ['title'] + (['tax_id'] if values.get('buyer_type') == 'enterprise' else [])
    return {'fields': values, 'missing_fields': [labels[k] for k in required if not values.get(k)],
            'copy_text': '\n'.join(f'{label}：{values[k]}' for k,label in labels.items() if values.get(k))}


@router.post('/{task_id}/submit-result')
def submit(task_id: str, data: Result, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(user, 'billing_task.submit.assigned'); write_lock(db); task = visible(db,user,task_id)
    if task.assignee_id != user.id:
        raise HTTPException(404, '任务不存在或不在可见范围')
    key=request.headers.get('Idempotency-Key'); operation='billing_task.submit:'+task.id
    prior,digest=lookup(db,user,operation,key,data.dict())
    if prior:
        return response(db,task,user)
    check_revision(task,data.expected_revision); ensure_assigned(db,user,task,request)
    if cents(data.amount) != task.amount_cents:
        raise HTTPException(409, '本次开票金额与分配任务不一致，请财务核对')
    result=models.BillingTaskResult(task_id=task.id,task_revision=task.revision,
        billing_version_id=task.billing_version_id,submitted_by=user.id,amount_cents=cents(data.amount),
        invoice_number=data.invoice_number,invoice_date=data.invoice_date,note=data.note)
    db.add(result); db.flush(); task.submitted_result_id=result.id; task.status='result_submitted'
    task.submitted_at=datetime.utcnow(); task.revision+=1
    audit(db,user,'submit',task,request, data.note, {'result_id':result.id})
    remember(db,user,operation,key,digest,{'result_id':result.id}); db.commit()
    return response(db,task,user)


@router.post('/{task_id}/reassign')
def reassign(task_id: str,data: Reassign,request: Request,db: Session=Depends(get_db),user=Depends(get_current_user)):
    require(user,'billing_task.manage'); write_lock(db); task=visible(db,user,task_id);check_revision(task,data.expected_revision)
    if task.status not in ('assigned','needs_review'):
        raise HTTPException(409,'已提交、完成或撤回的任务不能直接转派')
    assignee(db,data.assignee_id); task.assignee_id=data.assignee_id;task.assigned_at=datetime.utcnow()
    if data.amount is not None: task.amount_cents=cents(data.amount)
    task.reason=data.reason;task.revision+=1
    audit(db,user,'reassign',task,request,data.reason,{'assignee_id':task.assignee_id});db.commit()
    return response(db,task,user)


@router.post('/{task_id}/revoke')
def revoke(task_id: str,data: Action,request: Request,db: Session=Depends(get_db),user=Depends(get_current_user)):
    require(user,'billing_task.manage');write_lock(db);task=visible(db,user,task_id);check_revision(task,data.expected_revision)
    if task.status not in ('assigned','result_submitted','needs_review'):
        raise HTTPException(409,'任务已完成或撤回')
    task.status='revoked';task.revoked_at=datetime.utcnow();task.reason=data.reason;task.revision+=1
    audit(db,user,'revoke',task,request,data.reason);db.commit();return response(db,task,user)


@router.post('/{task_id}/return')
def return_result(task_id: str,data: Action,request: Request,db: Session=Depends(get_db),user=Depends(get_current_user)):
    require(user,'billing_task.manage');write_lock(db);task=visible(db,user,task_id);check_revision(task,data.expected_revision)
    if task.status!='result_submitted':raise HTTPException(409,'只有待财务确认结果可以退回')
    task.status='assigned' if current_valid(db,task) else 'needs_review'
    task.submitted_result_id=None;task.submitted_at=None;task.reason=data.reason;task.revision+=1
    audit(db,user,'return',task,request,data.reason);db.commit();return response(db,task,user)


@router.post('/{task_id}/revalidate')
def revalidate(task_id: str,data: Revalidate,request: Request,db: Session=Depends(get_db),user=Depends(get_current_user)):
    require(user,'billing_task.manage');write_lock(db);task=visible(db,user,task_id);check_revision(task,data.expected_revision)
    if task.status!='needs_review' and not (task.status=='assigned' and not current_valid(db,task)):
        raise HTTPException(409,'只有需重新核对的未提交任务可以更新版本')
    project=db.get(models.Project,task.project_id)
    customer=checked_creation(db,SimpleNamespace(project_id=task.project_id,customer_id=project.customer_id if project else None,
        billing_profile_id=data.billing_profile_id,billing_version_id=data.billing_version_id,assignee_id=task.assignee_id))
    task.customer_id=customer.id;task.customer_revision=customer.revision
    task.billing_profile_id=data.billing_profile_id;task.billing_version_id=data.billing_version_id
    task.status='assigned';task.reason=data.reason;task.revision+=1
    audit(db,user,'revalidate',task,request,data.reason);db.commit();return response(db,task,user)


@router.post('/{task_id}/confirm')
def confirm(task_id: str,data: Confirm,request: Request,db: Session=Depends(get_db),user=Depends(get_current_user)):
    require(user,'billing_task.confirm');write_lock(db);task=visible(db,user,task_id)
    key=request.headers.get('Idempotency-Key');operation='billing_task.confirm:'+task.id
    prior,digest=lookup(db,user,operation,key,data.dict())
    if prior:return response(db,task,user)
    check_revision(task,data.expected_revision)
    if task.status!='result_submitted' or not task.submitted_result_id:
        raise HTTPException(409,'只有已经提交的办理结果可以财务确认')
    project,customer,profile,version=entities(db,task);result=db.get(models.BillingTaskResult,task.submitted_result_id)
    if not project or project.is_deleted:raise HTTPException(409,'项目已删除，须先核对处理')
    check_revision(project,data.expected_project_revision)
    if not current_valid(db,task) and not data.confirm_historical:
        raise HTTPException(409,'使用版本与当前资料不同，请明确核对历史开票并填写原因')
    if not version or result.billing_version_id!=version.id or not profile or version.profile_id!=profile.id or profile.customer_id!=task.customer_id:
        raise HTTPException(409,'历史版本所属关系不一致')
    if data.financial_entry_id:
        entry=db.get(models.FinancialEntry,data.financial_entry_id)
        snap=db.query(models.InvoiceSnapshot).filter_by(financial_entry_id=data.financial_entry_id).first()
        if not entry or entry.kind!='invoice' or entry.voided_at or entry.project_id!=task.project_id or entry.amount_cents!=result.amount_cents or entry.reference!=result.invoice_number or entry.occurred_on!=result.invoice_date or not snap or snap.version_id!=result.billing_version_id or snap.customer_id!=task.customer_id:
            raise HTTPException(422,'关联流水的项目、金额、票号、日期或开票版本不符')
        if db.query(models.BillingTask.id).filter_by(financial_entry_id=entry.id).first():
            raise HTTPException(409,'该流水已关联其他任务')
    else:
        entry=record_entry(db,user,project,'invoice',SimpleNamespace(amount=Decimal(result.amount_cents)/100,
            occurred_on=result.invoice_date,reference=result.invoice_number,note=result.note,replacement_of_id=None),
            request,profile,version,task.customer_id)
    task.financial_entry_id=entry.id;task.status='completed';task.completed_at=datetime.utcnow()
    task.reason=data.reason;task.revision+=1
    audit(db,user,'confirm',task,request,data.reason,{'entry_id':entry.id,'historical':not current_valid(db,task)})
    remember(db,user,operation,key,digest,{'entry_id':entry.id});db.commit();return response(db,task,user)
