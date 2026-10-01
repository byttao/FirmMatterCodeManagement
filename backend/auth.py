from datetime import datetime, timedelta
from typing import Optional
import secrets
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from database import get_db
import models
from permissions import has, is_related
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8小时

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    from http_security import password_slots
    with password_slots:
        return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    if not 12 <= len(password) <= 72 or len(password.encode("utf-8")) > 72:
        raise HTTPException(422, "密码需为12至72位，UTF-8编码不能超过72字节")
    from http_security import password_slots
    with password_slots:
        return pwd_context.hash(password)


def get_current_user(
    request: Request,
    db: Session = Depends(get_db)
):
    from http_security import COOKIE, digest, check_csrf
    session = db.get(models.AuthSession, digest(request.cookies.get(COOKIE, "")))
    if not session or session.revoked_at or session.expires_at <= datetime.utcnow():
        raise HTTPException(401, "登录已失效，请重新登录")
    user = db.get(models.User, session.user_id)
    if not user or not user.is_active or user.session_version != session.session_version:
        raise HTTPException(401, "登录已失效，请重新登录")
    check_csrf(request, session)
    db.info["request_id"] = getattr(request.state, "request_id", None)
    request.state.auth_session = session
    return user


def issue_session(db, user, response):
    from http_security import digest, set_session_cookies
    secret, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    db.add(models.AuthSession(id=digest(secret), user_id=user.id, csrf_hash=digest(csrf),
                             session_version=user.session_version,
                             expires_at=datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)))
    db.commit()
    set_session_cookies(response, secret, csrf, ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    return csrf


def get_user_fiscal_year(user: models.User) -> int:
    """获取用户的当前操作年度"""
    from datetime import datetime
    # 默认使用当前年份
    return getattr(user, 'fiscal_year', None) or datetime.now().year


def require_role(allowed_roles: list):
    """权限装饰器工厂"""
    def role_checker(current_user: models.User = Depends(get_current_user)):
        if not set(current_user.roles).intersection(allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="您没有权限执行此操作"
            )
        return current_user
    return role_checker


# 权限检查函数（用于在业务逻辑中调用）
def can_edit_project(user: models.User, project: models.Project) -> bool:
    return has(user, "project.edit.all_basic") or (has(user, "project.edit.led") and project.leader_id == user.id)


def can_delete_project(user: models.User, project: Optional[models.Project] = None) -> bool:
    """检查用户是否可以删除项目
    - admin：可以删除
    - practitioner：只能删除未编号的项目（且必须是自己的项目）
    """
    if project is None:
        return has(user, "number.void")
    return not project.report_no and (has(user, "project.delete.all") or (has(user, "project.delete.led") and project.leader_id == user.id))


def can_view_project(user: models.User, project: models.Project) -> bool:
    return has(user, "project.read.all_basic") or has(user, "project.read.finance") or (has(user, "project.read.related") and is_related(user, project))


def can_edit_financial_fields(user: models.User) -> bool:
    """检查用户是否可以编辑财务字段"""
    return has(user, "finance.write")


def can_generate_report_no(user: models.User) -> bool:
    """检查用户是否可以生成报告编号"""
    return has(user, "number.issue.all") or has(user, "number.issue.led")


def can_export(user: models.User) -> bool:
    """检查用户是否可以导出数据"""
    return any(has(user, p) for p in ("project.export.all", "project.export.finance", "project.export.related"))


def can_manage_users(user: models.User) -> bool:
    """检查用户是否可以管理用户"""
    return has(user, "identity.manage")


def can_manage_fiscal_config(user: models.User) -> bool:
    """检查用户是否可以管理编号年度配置"""
    return has(user, "number.configure")


def can_create_project(user: models.User) -> bool:
    """检查用户是否可以创建项目"""
    return has(user, "project.create.assign") or (user.is_practitioner and has(user, "project.create.self"))
