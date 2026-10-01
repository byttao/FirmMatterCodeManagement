from datetime import datetime, timedelta
from typing import Optional
import secrets
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from database import get_db
import models
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
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="您没有权限执行此操作"
            )
        return current_user
    return role_checker


# 权限检查函数（用于在业务逻辑中调用）
def can_edit_project(user: models.User, project: models.Project) -> bool:
    """检查用户是否可以编辑项目"""
    if user.role == models.UserRole.ADMIN.value:
        return True
    if user.role == models.UserRole.PRACTITIONER.value:
        # 执业人员只能编辑自己负责的项目
        return project.leader_id == user.id
    if user.role == models.UserRole.ADMIN_STAFF.value:
        # 后勤只能编辑财务字段
        return False  # 财务字段通过专门的API编辑
    return False


def can_delete_project(user: models.User, project: Optional[models.Project] = None) -> bool:
    """检查用户是否可以删除项目
    - admin：可以删除
    - practitioner：只能删除未编号的项目（且必须是自己的项目）
    """
    if user.role == models.UserRole.ADMIN.value:
        return True
    if user.role == models.UserRole.PRACTITIONER.value:
        # 执业人员只能删除自己负责且未编号的项目
        if project is None:
            return False
        return project.leader_id == user.id and not project.report_no
    return False


def can_view_project(user: models.User, project: models.Project) -> bool:
    """检查用户是否可以查看项目"""
    if user.role in [models.UserRole.ADMIN.value, models.UserRole.ADMIN_STAFF.value]:
        return True
    if user.role == models.UserRole.PRACTITIONER.value:
        # 执业人员：负责人、团队成员或签字人可查看
        if project.leader_id == user.id:
            return True
        if ((project.signer1 and project.signer1.user_id == user.id) or
                (project.signer2 and project.signer2.user_id == user.id)):
            return True
        member_ids = [m.user_id for m in project.members]
        return user.id in member_ids
    return False


def can_edit_financial_fields(user: models.User) -> bool:
    """检查用户是否可以编辑财务字段"""
    return user.role in [models.UserRole.ADMIN.value, models.UserRole.ADMIN_STAFF.value]


def can_generate_report_no(user: models.User) -> bool:
    """检查用户是否可以生成报告编号"""
    return user.role in [models.UserRole.ADMIN.value, models.UserRole.PRACTITIONER.value]


def can_export(user: models.User) -> bool:
    """检查用户是否可以导出数据"""
    return user.role in [models.UserRole.ADMIN.value, models.UserRole.ADMIN_STAFF.value]


def can_manage_users(user: models.User) -> bool:
    """检查用户是否可以管理用户"""
    return user.role == models.UserRole.ADMIN.value


def can_manage_fiscal_config(user: models.User) -> bool:
    """检查用户是否可以管理编号年度配置"""
    return user.role in [models.UserRole.ADMIN.value, models.UserRole.ADMIN_STAFF.value]


def can_create_project(user: models.User) -> bool:
    """检查用户是否可以创建项目"""
    return user.role in [models.UserRole.ADMIN.value, models.UserRole.PRACTITIONER.value]
