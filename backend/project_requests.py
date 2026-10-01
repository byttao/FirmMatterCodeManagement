from datetime import datetime
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import constr
from sqlalchemy.orm import Session
from database import get_db
from auth import get_current_user
from permissions import has, require, project_scope
from audit import write_lock, check_revision, event
from report_no_generator import recycle_report_no
import models
import schemas

router = APIRouter(prefix='/api')


class Proposal(schemas.InputModel):
    expected_revision: int
    kind: Literal['transfer', 'void_number']
    target_leader_id: Optional[int] = None
    reason: constr(min_length=1, max_length=500)


class Review(schemas.InputModel):
    expected_revision: int
    decision: Literal['approve', 'reject']
    reason: constr(min_length=1, max_length=500)


def eligible(db, user_id):
    person = db.get(models.User, user_id) if user_id else None
    if not person or not person.is_active or not person.is_practitioner:
        raise HTTPException(422, '请选择启用的专业人员作为负责人')


def response(item):
    return {field: getattr(item, field) for field in ('id', 'project_id', 'kind', 'target_leader_id', 'project_revision',
        'submitted_by', 'reason', 'status', 'revision', 'reviewed_by', 'review_reason', 'created_at', 'reviewed_at')}


@router.post('/projects/{project_id}/change-requests')
def propose(project_id: int, data: Proposal, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    write_lock(db)
    project = project_scope(db.query(models.Project).filter_by(id=project_id, is_deleted=False), user).first()
    if not project or project.leader_id != user.id or not has(user, 'project.edit.led'):
        raise HTTPException(404, '项目不存在或不在负责范围')
    check_revision(project, data.expected_revision)
    if not data.reason.strip():
        raise HTTPException(422, '必须填写申请原因')
    if data.kind == 'transfer':
        eligible(db, data.target_leader_id)
        if project.leader_id == data.target_leader_id:
            raise HTTPException(422, '新负责人不能与当前相同')
    elif data.target_leader_id is not None or not project.report_no or project.report_no_status == 'recycled':
        raise HTTPException(409, '无有效编号可申请作废')
    if db.query(models.ProjectChangeRequest.id).filter_by(project_id=project.id, kind=data.kind, status='submitted').first():
        raise HTTPException(409, '已有待处理的同类申请')
    item = models.ProjectChangeRequest(project_id=project.id, kind=data.kind, target_leader_id=data.target_leader_id,
        project_revision=project.revision, submitted_by=user.id, reason=data.reason)
    db.add(item); db.flush()
    event(db, user, 'project.request', item, reason=data.reason, project_id=project.id, request=request)
    db.commit()
    return response(item)


@router.get('/project-change-requests')
def list_requests(page: int = Query(1, ge=1), db: Session = Depends(get_db), user=Depends(get_current_user)):
    query = db.query(models.ProjectChangeRequest).join(models.Project)
    if not has(user, 'project.transfer'):
        query = query.filter(models.ProjectChangeRequest.submitted_by == user.id)
        query = project_scope(query, user)
    rows = query.order_by(models.ProjectChangeRequest.id.desc()).offset((page-1)*20).limit(20).all()
    return {'items': [response(item) for item in rows], 'total': query.count()}


@router.post('/project-change-requests/{item_id}/review')
def review(item_id: int, data: Review, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(user, 'project.transfer')
    write_lock(db)
    item = db.get(models.ProjectChangeRequest, item_id)
    if not item:
        raise HTTPException(404, '申请不存在')
    check_revision(item, data.expected_revision)
    if item.status != 'submitted':
        raise HTTPException(409, '申请已处理')
    if not data.reason.strip():
        raise HTTPException(422, '必须填写审核依据')
    project = db.get(models.Project, item.project_id)
    if data.decision == 'approve':
        check_revision(project, item.project_revision)
        if project.is_deleted or project.leader_id != item.submitted_by:
            raise HTTPException(409, '项目状态已变化，请重新申请')
        if item.kind == 'transfer':
            eligible(db, item.target_leader_id)
            project.leader_id = item.target_leader_id
        else:
            require(user, 'number.void')
            if not project.report_no or project.report_no_status == 'recycled':
                raise HTTPException(409, '编号已变化')
            recycle_report_no(db, project)
        project.revision += 1
        event(db, user, f'project.request_{item.kind}', project, reason=data.reason, project_id=project.id, request=request,
            diff={'request_id': item.id, 'target_leader_id': item.target_leader_id})
    item.status = 'approved' if data.decision == 'approve' else 'rejected'
    item.revision += 1; item.reviewed_by = user.id; item.review_reason = data.reason; item.reviewed_at = datetime.utcnow()
    event(db, user, 'project.request_review', item, reason=data.reason, project_id=project.id, request=request)
    db.commit()
    return response(item)


class CustomerCorrection(schemas.InputModel):
    expected_revision: int
    customer_id: int
    identity_checked: bool
    reason: constr(min_length=1, max_length=500)


@router.post('/projects/{project_id}/correct-customer')
def correct_customer(project_id: int, data: CustomerCorrection, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    require(user, 'customer.correct')
    write_lock(db)
    project = db.get(models.Project, project_id)
    customer = db.get(models.Customer, data.customer_id)
    if not project or project.is_deleted or not customer:
        raise HTTPException(404, '项目或客户不存在')
    check_revision(project, data.expected_revision)
    if not data.identity_checked or not data.reason.strip() or not customer.is_active or customer.identity_status != 'confirmed':
        raise HTTPException(422, '请核对启用且已确认的客户主体并填写原因')
    if project.customer_id == customer.id:
        raise HTTPException(422, '客户归属未变化')
    previous = project.customer_id
    project.customer_id = customer.id
    project.revision += 1
    event(db, user, 'project.correct_customer', project, reason=data.reason, project_id=project.id, customer_id=customer.id,
        diff={'previous_customer_id': previous, 'customer_id': customer.id, 'historical_snapshots_preserved': True}, request=request)
    db.commit()
    return {'revision': project.revision, 'customer_id': project.customer_id}
