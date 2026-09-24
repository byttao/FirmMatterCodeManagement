from datetime import datetime, timedelta
from typing import Optional
import os
import secrets
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from database import DATA_DIR, get_db
import models
import schemas

# JWT 配置
def load_secret_key() -> str:
    configured = os.getenv("FIRM_MANAGER_SECRET_KEY")
    if configured:
        if len(configured) < 32:
            raise RuntimeError("FIRM_MANAGER_SECRET_KEY 至少需要 32 个字符")
        return configured

    secret_file = DATA_DIR / "jwt_secret"
    if secret_file.exists():
        return secret_file.read_text(encoding="ascii").strip()

    secret = secrets.token_urlsafe(48)
    try:
        fd = os.open(secret_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return secret_file.read_text(encoding="ascii").strip()
    with os.fdopen(fd, "w", encoding="ascii") as output:
        output.write(secret)
    return secret


SECRET_KEY = load_secret_key()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8小时

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="认证失败，请重新登录",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("user_id")
        if user_id is None:
            raise credentials_exception
        token_data = schemas.TokenData(
            user_id=user_id,
            username=payload.get("username"),
            role=payload.get("role"),
            fiscal_year=payload.get("fiscal_year")
        )
    except JWTError:
        raise credentials_exception

    user = db.query(models.User).filter(models.User.id == token_data.user_id).first()
    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(status_code=400, detail="用户已被禁用")
    return user


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
    - admin/admin_staff：始终可以删除
    - practitioner：只能删除未编号的项目（且必须是自己的项目）
    """
    if user.role in [models.UserRole.ADMIN.value, models.UserRole.ADMIN_STAFF.value]:
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
        # 执业人员：负责人或团队成员可查看
        if project.leader_id == user.id:
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
