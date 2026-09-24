from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from datetime import timedelta, datetime
from typing import Optional, List
import os
import re
from pathlib import Path
from pypinyin import lazy_pinyin, Style
from io import BytesIO
from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.styles import Alignment

from database import engine, get_db, SessionLocal
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text, or_
import models
import schemas
from migrations import upgrade_database
from finance import refresh_project_finance, cents
from auth import (
    get_password_hash, verify_password, create_access_token,
    get_current_user, ACCESS_TOKEN_EXPIRE_MINUTES,
    can_view_project, can_edit_project, can_delete_project,
    can_edit_financial_fields, can_generate_report_no, can_export,
    can_manage_users, can_manage_fiscal_config, can_create_project
)
from report_no_generator import (
    generate_report_no, recycle_report_no,
    get_available_report_years, get_available_firms, get_available_report_types, get_rule
)
from version import APP_VERSION

upgrade_database(engine)

app = FastAPI(title="事务所项目编号管理系统", version=APP_VERSION)

MIN_CONFIG_YEAR = 2000
MAX_CONFIG_YEAR = 2100


def normalize_required_text(value: str, label: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > max_length:
        raise HTTPException(status_code=400, detail=f"{label}不能为空且不能超过 {max_length} 个字符")
    return normalized


def validate_config_year(year: int) -> int:
    if year < MIN_CONFIG_YEAR or year > MAX_CONFIG_YEAR:
        raise HTTPException(
            status_code=400,
            detail=f"年度必须在 {MIN_CONFIG_YEAR}-{MAX_CONFIG_YEAR} 之间",
        )
    return year

# 默认采用同源部署；独立前端部署时可明确配置允许的来源。
cors_origins = [origin.strip() for origin in os.getenv("FIRM_MANAGER_CORS_ORIGINS", "").split(",") if origin.strip()]
if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ==================== 首次安装与认证 ====================
def is_system_initialized(db: Session) -> bool:
    """已有用户的数据库不再开放首次安装。"""
    return db.query(models.User.id).first() is not None


def validate_setup_template(template: str) -> int:
    """校验规则模板，并返回序号位数。"""
    if not template or "{yyyy}" not in template:
        raise HTTPException(status_code=400, detail="编号模板必须包含 {yyyy} 年度占位符")
    matches = re.findall(r"\{(n{1,10})\}", template)
    if len(matches) != 1:
        raise HTTPException(status_code=400, detail="编号模板必须包含且只能包含一个序号占位符，例如 {nnn}")
    if re.search(r"[{}]", re.sub(r"\{yyyy\}|\{yy\}|\{n{1,10}\}", "", template)):
        raise HTTPException(status_code=400, detail="编号模板包含不支持的占位符")
    return len(matches[0])


def numbering_format_key(template: str, year: int) -> str:
    """Compare rendered formats before a sequence is assigned."""
    rendered = template.replace("{yyyy}", str(year)).replace("{yy}", str(year)[-2:])
    return re.sub(r"\{n{1,10}\}", "{sequence}", rendered)


def numbering_pattern(template: str, year: int):
    rendered = template.replace("{yyyy}", str(year)).replace("{yy}", str(year)[-2:])
    sequence = re.search(r"\{n{1,10}\}", rendered)
    digits = len(sequence.group()) - 2
    return re.compile(
        "^" + re.escape(rendered[:sequence.start()]) +
        rf"[0-9]{{{digits},}}" + re.escape(rendered[sequence.end():]) + "$"
    )


def ensure_unique_numbering_format(db: Session, template: str, year: int, exclude_rule_id: Optional[int] = None):
    candidate = numbering_format_key(template, year)
    rules = db.query(models.ReportNumberRule).join(models.FiscalYearFirm).join(models.FiscalYear).filter(
        models.FiscalYear.year == year
    ).all()
    if any(rule.id != exclude_rule_id and numbering_format_key(rule.template, year) == candidate for rule in rules):
        raise HTTPException(status_code=400, detail="该年度已有相同的编号格式，请使用不同模板或复用已有规则")
    if exclude_rule_id is not None:
        previous = db.query(models.ReportNumberRule).filter_by(id=exclude_rule_id).first()
        if previous and previous.template == template:
            return
    pattern = numbering_pattern(template, year)
    historical_numbers = db.query(models.ReportNumberHistory.report_no).filter(
        models.ReportNumberHistory.report_no.isnot(None),
    ).all()
    historical_numbers += db.query(models.Project.report_no).filter(
        models.Project.fiscal_year == year,
        models.Project.report_no.isnot(None),
    ).all()
    if any(pattern.fullmatch(number) for (number,) in historical_numbers):
        raise HTTPException(status_code=400, detail="该编号格式与历史报告编号冲突，不能复用")


@app.get("/api/setup/status", response_model=schemas.SetupStatus)
async def setup_status(db: Session = Depends(get_db)):
    """公开返回安装状态，供登录页决定是否进入安装向导。"""
    return {"initialized": is_system_initialized(db)}


@app.post("/api/setup")
async def setup_system(data: schemas.SetupRequest, request: Request, db: Session = Depends(get_db)):
    """首次安装：创建管理员和第一年度的自定义编号配置。"""
    if not request.client or request.client.host not in ("127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="首次安装仅允许从服务器本机完成")
    if db.get_bind().dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
    if is_system_initialized(db):
        raise HTTPException(status_code=409, detail="系统已经完成安装")

    username = data.admin_username.strip()
    real_name = data.admin_real_name.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,50}", username):
        raise HTTPException(status_code=400, detail="管理员账号需为 3-50 位字母、数字、下划线、点或短横线")
    if len(data.admin_password) < 8:
        raise HTTPException(status_code=400, detail="管理员密码至少需要 8 位")
    if not real_name:
        raise HTTPException(status_code=400, detail="请输入管理员姓名")
    validate_config_year(data.fiscal_year)
    if not data.firms:
        raise HTTPException(status_code=400, detail="至少配置一个事务所")

    normalized_firms = []
    firm_names = set()
    numbering_formats = set()
    for firm_data in data.firms:
        firm_name = firm_data.name.strip()
        if not firm_name or len(firm_name) > 100 or firm_name in firm_names:
            raise HTTPException(status_code=400, detail="事务所名称不能为空且不能重复")
        if not firm_data.report_types:
            raise HTTPException(status_code=400, detail=f"事务所“{firm_name}”至少配置一个业务类型")
        firm_names.add(firm_name)
        report_types = []
        report_names = set()
        rule_names = set()
        for report_data in firm_data.report_types:
            report_name = report_data.report_type.strip()
            if not report_name or len(report_name) > 100 or report_name in report_names:
                raise HTTPException(status_code=400, detail=f"事务所“{firm_name}”的业务类型不能为空且不能重复")
            sequence_digits = validate_setup_template(report_data.template.strip())
            format_key = numbering_format_key(report_data.template.strip(), data.fiscal_year)
            if format_key in numbering_formats:
                raise HTTPException(status_code=400, detail="存在重复编号格式，请为不同规则设置不同模板")
            numbering_formats.add(format_key)
            rule_name = (report_data.rule_name or '').strip() or f"{report_name}编号"
            if len(rule_name) > 50 or rule_name in rule_names:
                raise HTTPException(status_code=400, detail=f"事务所“{firm_name}”的规则名称过长或重复")
            report_names.add(report_name)
            rule_names.add(rule_name)
            report_types.append((report_name, report_data.template.strip(), sequence_digits, rule_name))
        normalized_firms.append((firm_name, report_types))

    try:
        admin = models.User(
            username=username,
            hashed_password=get_password_hash(data.admin_password),
            real_name=real_name,
            role=models.UserRole.ADMIN.value,
            fiscal_year=data.fiscal_year,
        )
        fiscal_year = models.FiscalYear(year=data.fiscal_year)
        db.add_all([admin, fiscal_year])
        db.flush()

        for firm_name, report_types in normalized_firms:
            firm = models.FiscalYearFirm(fiscal_year_id=fiscal_year.id, firm=firm_name)
            db.add(firm)
            db.flush()
            for report_name, template, sequence_digits, rule_name in report_types:
                rule = models.ReportNumberRule(
                    fiscal_year_firm_id=firm.id,
                    rule_name=rule_name or f"{report_name}编号",
                    template=template,
                    sequence_digits=sequence_digits,
                )
                db.add(rule)
                db.flush()
                db.add(models.FiscalYearReportType(
                    fiscal_year_firm_id=firm.id,
                    report_type=report_name,
                    rule_id=rule.id,
                ))
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {"message": "系统初始化完成，请使用新建管理员账号登录"}


# ==================== 认证相关 ====================
@app.post("/api/auth/login", response_model=schemas.Token)
async def login(form_data: schemas.UserLogin, db: Session = Depends(get_db)):
    if not is_system_initialized(db):
        raise HTTPException(status_code=428, detail="系统尚未完成首次安装，请先完成安装向导")
    user = db.query(models.User).filter(
        models.User.username == form_data.username,
        models.User.is_active == True
    ).first()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )

    # 确定操作年度：如果登录时指定了年度，使用指定年度；否则使用用户保存的年度或当前年份
    fiscal_year = form_data.fiscal_year or user.fiscal_year or datetime.now().year
    configured_years = [row[0] for row in db.query(models.FiscalYear.year).order_by(models.FiscalYear.year.desc()).all()]
    if fiscal_year not in configured_years:
        if form_data.fiscal_year is not None:
            raise HTTPException(status_code=400, detail="该编号年度尚未配置")
        if configured_years:
            fiscal_year = configured_years[0]

    # 更新用户的当前操作年度
    if user.fiscal_year != fiscal_year:
        user.fiscal_year = fiscal_year
        db.commit()

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "user_id": user.id,
            "username": user.username,
            "role": user.role,
            "fiscal_year": fiscal_year
        },
        expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer", "fiscal_year": fiscal_year}


@app.get("/api/auth/me", response_model=schemas.UserResponse)
async def get_me(current_user: models.User = Depends(get_current_user)):
    return current_user


# ==================== 用户管理 ====================
@app.get("/api/users", response_model=list[schemas.UserResponse])
async def list_users(
    include_disabled: bool = False,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if not can_manage_users(current_user):
        raise HTTPException(status_code=403, detail="无权限")
    query = db.query(models.User)
    if not include_disabled:
        query = query.filter(models.User.is_active == True)
    return query.order_by(models.User.is_active.desc(), models.User.id.desc()).all()


@app.get("/api/users/practitioners", response_model=list[schemas.PractitionerResponse])
async def list_practitioners(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """获取所有执业人员（用于项目表单选择负责人和成员）"""
    return db.query(models.User).filter(
        models.User.is_active == True,
        models.User.role == models.UserRole.PRACTITIONER.value
    ).all()


def get_pinyin_initial(name: str) -> str:
    """获取姓名的拼音首字母"""
    pinyin_list = lazy_pinyin(name, style=Style.FIRST_LETTER)
    return ''.join(pinyin_list).upper()


def get_full_pinyin(name: str) -> str:
    """获取姓名的完整拼音"""
    pinyin_list = lazy_pinyin(name, style=Style.NORMAL)
    return ''.join(pinyin_list).lower()


@app.get("/api/users/search", response_model=list[schemas.PractitionerResponse])
async def search_users(
    q: str = Query(..., min_length=1, description="搜索关键字（支持姓名、拼音、拼音首字母）"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """搜索执业人员（支持姓名、拼音、拼音首字母匹配）
    用于项目表单中快速查找团队成员
    """
    all_users = db.query(models.User).filter(
        models.User.is_active == True,
        models.User.role == models.UserRole.PRACTITIONER.value
    ).all()

    results = []
    for user in all_users:
        name = user.real_name

        # 检查是否是中文搜索（包含中文字符）
        if any('\u4e00' <= c <= '\u9fff' for c in q):
            # 中文搜索：精确匹配姓名
            if q in name:
                results.append(user)
        else:
            # 拼音搜索
            q_lower = q.lower()
            q_upper = q.upper()
            full_pinyin = get_full_pinyin(name)
            pinyin_initial = get_pinyin_initial(name)

            # 匹配：完整拼音包含 / 拼音首字母包含
            if (q_lower in full_pinyin or q_upper in pinyin_initial):
                results.append(user)

    return results


@app.get("/api/users/current-fiscal-year")
async def get_current_fiscal_year(
    current_user: models.User = Depends(get_current_user)
):
    """获取当前操作年度"""
    return {"fiscal_year": current_user.fiscal_year or datetime.now().year}


@app.put("/api/users/current-fiscal-year")
async def set_current_fiscal_year(
    data: dict,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """设置当前操作年度"""
    fiscal_year = data.get("fiscal_year")
    if isinstance(fiscal_year, bool) or not isinstance(fiscal_year, int):
        raise HTTPException(status_code=400, detail="请提供有效的年度")
    validate_config_year(fiscal_year)
    if not db.query(models.FiscalYear.id).filter_by(year=fiscal_year).first():
        raise HTTPException(status_code=400, detail="该编号年度尚未配置")

    current_user.fiscal_year = fiscal_year
    db.commit()

    # 生成新的 token 包含更新后的年度
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "user_id": current_user.id,
            "username": current_user.username,
            "role": current_user.role,
            "fiscal_year": fiscal_year
        },
        expires_delta=access_token_expires
    )

    return {"access_token": access_token, "token_type": "bearer", "fiscal_year": fiscal_year}


@app.post("/api/users", response_model=schemas.UserResponse)
async def create_user(
    user_data: schemas.UserCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if not can_manage_users(current_user):
        raise HTTPException(status_code=403, detail="无权限")

    real_name = user_data.real_name.strip()
    if not real_name:
        raise HTTPException(status_code=400, detail="姓名不能为空")
    if not db.query(models.FiscalYear.id).filter_by(year=current_user.fiscal_year).first():
        raise HTTPException(status_code=400, detail="当前编号年度尚未配置")

    existing = db.query(models.User).filter(models.User.username == user_data.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="用户名已存在")

    user = models.User(
        username=user_data.username,
        hashed_password=get_password_hash(user_data.password),
        real_name=real_name,
        role=user_data.role,
        fiscal_year=current_user.fiscal_year
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def ensure_admin_remains(db: Session, user: models.User, next_role: str, next_active: bool):
    if (user.role == models.UserRole.ADMIN.value and user.is_active
            and (next_role != models.UserRole.ADMIN.value or not next_active)):
        active_admins = db.query(models.User.id).filter_by(
            role=models.UserRole.ADMIN.value, is_active=True
        ).count()
        if active_admins <= 1:
            raise HTTPException(status_code=400, detail="必须保留至少一名启用的管理人员")


@app.put("/api/users/{user_id}", response_model=schemas.UserResponse)
async def update_user(
    user_id: int,
    user_data: schemas.UserUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if not can_manage_users(current_user):
        raise HTTPException(status_code=403, detail="无权限")
    if db.get_bind().dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    next_role = user_data.role if user_data.role is not None else user.role
    next_active = user_data.is_active if user_data.is_active is not None else user.is_active
    ensure_admin_remains(db, user, next_role, next_active)

    if user_data.real_name is not None:
        real_name = user_data.real_name.strip()
        if not real_name:
            raise HTTPException(status_code=400, detail="姓名不能为空")
        user.real_name = real_name
    if user_data.role is not None:
        user.role = user_data.role
    if user_data.password:
        user.hashed_password = get_password_hash(user_data.password)
    if user_data.is_active is not None:
        user.is_active = user_data.is_active

    db.commit()
    db.refresh(user)
    return user


@app.delete("/api/users/{user_id}")
async def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if not can_manage_users(current_user):
        raise HTTPException(status_code=403, detail="无权限")
    if db.get_bind().dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能删除自己")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    ensure_admin_remains(db, user, user.role, False)
    user.is_active = False
    db.commit()
    return {"message": "删除成功"}


# ==================== 签字人管理 ====================
def eligible_signer_user(db: Session, user_id: int) -> models.User:
    user = db.query(models.User).filter_by(id=user_id).first()
    if not user or not user.is_active or user.role != models.UserRole.PRACTITIONER.value:
        raise HTTPException(status_code=400, detail="所选人员必须是启用的执业人员账号")
    return user


def signer_used(db: Session, signer_id: int) -> bool:
    return db.query(models.Project.id).filter(or_(
        models.Project.signer1_id == signer_id,
        models.Project.signer2_id == signer_id,
    )).first() is not None


def validate_project_people(db: Session, leader_id: int, member_ids: list[int],
                            original: Optional[models.Project] = None):
    if original is None or leader_id != original.leader_id:
        eligible_signer_user(db, leader_id)
    if len(member_ids) != len(set(member_ids)):
        raise HTTPException(status_code=400, detail="团队成员不能重复")
    if leader_id in member_ids:
        raise HTTPException(status_code=400, detail="负责人不能重复加入团队成员")
    previous_members = {member.user_id for member in original.members} if original else set()
    for member_id in member_ids:
        if member_id not in previous_members:
            eligible_signer_user(db, member_id)


def validate_project_signers(db: Session, signer_ids: tuple[Optional[int], Optional[int]],
                             firm: str, original: Optional[models.Project] = None):
    if signer_ids[0] and signer_ids[0] == signer_ids[1]:
        raise HTTPException(status_code=400, detail="签字人一和签字人二不能为同一人")
    users = []
    for position, signer_id in enumerate(signer_ids):
        if signer_id is None:
            continue
        signer = db.query(models.Signer).filter_by(id=signer_id).first()
        if not signer:
            raise HTTPException(status_code=400, detail="签字人不存在")
        if signer.signer_type != firm:
            raise HTTPException(status_code=400, detail="签字人事务所与项目事务所不匹配")
        # Existing history can be saved without reselecting an unlinked or retired signer.
        unchanged = (original is not None and original.firm == firm and
                     signer_id == (original.signer1_id if position == 0 else original.signer2_id))
        if not unchanged:
            if not signer.is_active or signer.user_id is None:
                raise HTTPException(status_code=400, detail="该签字人未关联执业账号或已禁用")
            eligible_signer_user(db, signer.user_id)
        if signer.user_id is not None:
            users.append(signer.user_id)
    if len(users) != len(set(users)):
        raise HTTPException(status_code=400, detail="两名签字人不能是同一执业人员")


def append_export_row(sheet, values):
    sheet.append(values)
    for cell in sheet[sheet.max_row]:
        if cell.data_type == "f":
            cell.data_type = "s"


@app.get("/api/signers", response_model=list[schemas.SignerResponse])
async def list_signers(
    signer_type: Optional[str] = None,
    include_disabled: bool = False,
    eligible_only: bool = False,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """获取签字人列表（行政人员和管理人员可用）
    - signer_type: 按事务所名称筛选
    - include_disabled: 是否包含已禁用的签字人，默认否
    """
    if not eligible_only and current_user.role not in [models.UserRole.ADMIN.value, models.UserRole.ADMIN_STAFF.value]:
        raise HTTPException(status_code=403, detail="无权限管理签字人")

    query = db.query(models.Signer)
    if not include_disabled or eligible_only:
        query = query.filter(models.Signer.is_active == True)
    if signer_type:
        query = query.filter(models.Signer.signer_type == signer_type)
    if eligible_only:
        query = query.filter(
            models.Signer.user_id.isnot(None),
            models.Signer.user.has(is_active=True, role=models.UserRole.PRACTITIONER.value),
        )
    return query.order_by(models.Signer.signer_type, models.Signer.name).all()


@app.post("/api/signers", response_model=schemas.SignerResponse)
async def create_signer(
    signer_data: schemas.SignerCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """创建签字人"""
    if current_user.role not in [models.UserRole.ADMIN.value, models.UserRole.ADMIN_STAFF.value]:
        raise HTTPException(status_code=403, detail="无权限管理签字人")

    user = eligible_signer_user(db, signer_data.user_id)
    if not db.query(models.FiscalYearFirm.id).filter_by(firm=signer_data.signer_type).first():
        raise HTTPException(status_code=400, detail="事务所未配置")
    existing = db.query(models.Signer).filter(
        models.Signer.user_id == user.id,
        models.Signer.signer_type == signer_data.signer_type
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="该执业人员已是此事务所签字人")

    signer = models.Signer(
        name=user.real_name,
        user_id=user.id,
        signer_type=signer_data.signer_type,
        is_active=True
    )
    db.add(signer)
    db.commit()
    db.refresh(signer)
    return signer


@app.put("/api/signers/{signer_id}", response_model=schemas.SignerResponse)
async def update_signer(
    signer_id: int,
    signer_data: schemas.SignerUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """更新签字人"""
    if current_user.role not in [models.UserRole.ADMIN.value, models.UserRole.ADMIN_STAFF.value]:
        raise HTTPException(status_code=403, detail="无权限管理签字人")

    signer = db.query(models.Signer).filter(models.Signer.id == signer_id).first()
    if not signer:
        raise HTTPException(status_code=404, detail="签字人不存在")

    if signer_data.user_id is not None:
        user = eligible_signer_user(db, signer_data.user_id)
        if signer.user_id is not None and signer.user_id != user.id:
            raise HTTPException(status_code=400, detail="已关联的签字人不能改绑其他账号")
        duplicate = db.query(models.Signer.id).filter(
            models.Signer.user_id == user.id,
            models.Signer.signer_type == (signer_data.signer_type or signer.signer_type),
            models.Signer.id != signer.id,
        ).first()
        if duplicate:
            raise HTTPException(status_code=400, detail="该执业人员已是此事务所签字人")
        signer.user_id = user.id
    if signer_data.signer_type is not None:
        if signer_data.signer_type != signer.signer_type and signer_used(db, signer.id):
            raise HTTPException(status_code=400, detail="已有签字项目，不能修改所属事务所")
        if not db.query(models.FiscalYearFirm.id).filter_by(firm=signer_data.signer_type).first():
            raise HTTPException(status_code=400, detail="事务所未配置")
        signer.signer_type = signer_data.signer_type

    if signer.user_id is not None and db.query(models.Signer.id).filter(
        models.Signer.user_id == signer.user_id,
        models.Signer.signer_type == signer.signer_type,
        models.Signer.id != signer.id,
    ).first():
        raise HTTPException(status_code=400, detail="该执业人员已是此事务所签字人")

    db.commit()
    db.refresh(signer)
    return signer


@app.delete("/api/signers/{signer_id}")
async def delete_signer(
    signer_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """物理删除签字人"""
    if current_user.role != models.UserRole.ADMIN.value:
        raise HTTPException(status_code=403, detail="只有管理人员可以删除签字人")

    signer = db.query(models.Signer).filter(models.Signer.id == signer_id).first()
    if not signer:
        raise HTTPException(status_code=404, detail="签字人不存在")

    # 检查是否被项目引用
    projects = db.query(models.Project).filter(
        (models.Project.signer1_id == signer_id) | (models.Project.signer2_id == signer_id)
    ).first()
    if projects:
        raise HTTPException(status_code=400, detail="该签字人已被项目引用，无法删除")

    db.delete(signer)
    db.commit()
    return {"message": "签字人已删除"}


@app.post("/api/signers/{signer_id}/disable")
async def disable_signer(
    signer_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """禁用签字人"""
    if current_user.role not in [models.UserRole.ADMIN.value, models.UserRole.ADMIN_STAFF.value]:
        raise HTTPException(status_code=403, detail="无权限管理签字人")

    signer = db.query(models.Signer).filter(models.Signer.id == signer_id).first()
    if not signer:
        raise HTTPException(status_code=404, detail="签字人不存在")

    signer.is_active = False
    signer.disabled_at = datetime.now()
    db.commit()
    return {"message": "签字人已禁用"}


@app.post("/api/signers/{signer_id}/enable")
async def enable_signer(
    signer_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """启用签字人"""
    if current_user.role not in [models.UserRole.ADMIN.value, models.UserRole.ADMIN_STAFF.value]:
        raise HTTPException(status_code=403, detail="无权限管理签字人")

    signer = db.query(models.Signer).filter(models.Signer.id == signer_id).first()
    if not signer:
        raise HTTPException(status_code=404, detail="签字人不存在")

    if signer.user_id is None:
        raise HTTPException(status_code=400, detail="请先关联执业人员账号")
    eligible_signer_user(db, signer.user_id)
    signer.is_active = True
    signer.disabled_at = None
    db.commit()
    return {"message": "签字人已启用"}


@app.post("/api/signers/import")
async def import_signers(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """导入签字人（Excel格式）
    Excel格式：账号, 事务所
    """
    if current_user.role not in [models.UserRole.ADMIN.value, models.UserRole.ADMIN_STAFF.value]:
        raise HTTPException(status_code=403, detail="无权限管理签字人")

    filename = file.filename or ""
    if not filename.lower().endswith('.xlsx'):
        raise HTTPException(status_code=400, detail="只支持 xlsx 格式")

    try:
        wb = load_workbook(BytesIO(await file.read()), read_only=True, data_only=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Excel 文件无法读取，请检查文件格式")

    ws = wb.active

    imported = 0
    skipped = 0
    errors = []
    seen = set()

    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not row or not row[0]:
            continue
        username = str(row[0]).strip()
        firm = str(row[1]).strip() if len(row) > 1 and row[1] else None
        if not firm:
            errors.append(f"第{row_idx}行：事务所不能为空")
            skipped += 1
            continue
        user = db.query(models.User).filter_by(username=username).first()
        if not user or not user.is_active or user.role != models.UserRole.PRACTITIONER.value:
            errors.append(f"第{row_idx}行：账号 {username} 不是启用的执业人员")
            skipped += 1
            continue
        if not db.query(models.FiscalYearFirm.id).filter_by(firm=firm).first():
            errors.append(f"第{row_idx}行：事务所未配置")
            skipped += 1
            continue
        if (user.id, firm) in seen:
            errors.append(f"第{row_idx}行：账号 {username}（{firm}）在文件中重复")
            skipped += 1
            continue
        seen.add((user.id, firm))
        existing = db.query(models.Signer).filter(
            models.Signer.user_id == user.id,
            models.Signer.signer_type == firm
        ).first()

        if existing:
            if existing.is_active:
                errors.append(f"第{row_idx}行：账号 {username}（{firm}）已存在")
            else:
                existing.is_active = True
                existing.disabled_at = None
                imported += 1
            skipped += 1
        else:
            signer = models.Signer(name=user.real_name, user_id=user.id, signer_type=firm, is_active=True)
            db.add(signer)
            imported += 1

    db.commit()
    return {
        "message": f"导入完成：新增 {imported} 条，跳过 {skipped} 条",
        "errors": errors[:10]  # 最多返回10条错误
    }


@app.get("/api/signers/export")
async def export_signers(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """导出签字人（Excel格式）"""
    if current_user.role not in [models.UserRole.ADMIN.value, models.UserRole.ADMIN_STAFF.value]:
        raise HTTPException(status_code=403, detail="无权限管理签字人")

    signers = db.query(models.Signer).order_by(
        models.Signer.signer_type, models.Signer.name
    ).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "签字人"

    # 表头
    headers = ["姓名", "执业账号", "事务所", "状态", "新增日期", "禁用日期"]
    append_export_row(ws, headers)

    # 数据
    for s in signers:
        append_export_row(ws, [
            s.name,
            s.user.username if s.user else "未关联",
            s.signer_type,
            "启用" if s.is_active else "禁用",
            s.created_at.strftime("%Y-%m-%d") if s.created_at else "",
            s.disabled_at.strftime("%Y-%m-%d") if s.disabled_at else ""
        ])

    # 调整列宽
    ws.column_dimensions['A'].width = 15
    ws.column_dimensions['B'].width = 18
    ws.column_dimensions['C'].width = 20
    ws.column_dimensions['D'].width = 8
    ws.column_dimensions['E'].width = 12
    ws.column_dimensions['F'].width = 12

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=signers.xlsx"}
    )


@app.get("/api/signers/template")
async def download_signer_template(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """下载签字人导入模板"""
    if current_user.role not in [models.UserRole.ADMIN.value, models.UserRole.ADMIN_STAFF.value]:
        raise HTTPException(status_code=403, detail="无权限管理签字人")

    # 获取事务所列表用于示例
    firms = db.query(models.FiscalYearFirm.firm).distinct().all()
    firm_list = [f[0] for f in firms]

    wb = Workbook()
    ws = wb.active
    ws.title = "签字人导入模板"

    # 表头说明
    ws.merge_cells('A1:C1')
    ws['A1'] = "签字人导入模板 - 请按以下格式填写"
    ws['A1'].font = ws['A1'].font.copy(bold=True, size=12)
    ws['A1'].alignment = Alignment(horizontal='center')

    ws.merge_cells('A2:C2')
    ws['A2'] = "说明：填写已启用执业人员的唯一登录账号；不要按姓名匹配"
    ws['A2'].font = ws['A2'].font.copy(color="808080")
    ws['A2'].alignment = Alignment(horizontal='center')

    # 表头
    ws.append(["", "", ""])  # 空行
    ws.append(["执业账号", "事务所"])
    ws.row_dimensions[4].height = 20

    # 数据验证 - 事务所下拉列表
    ws.row_dimensions[4].hidden = False
    dv = DataValidation(type="list", formula1=f'"{",".join(firm_list)}"', allow_blank=True)
    dv.error = "请从下拉列表选择事务所"
    dv.errorTitle = "无效的事务所"
    ws.add_data_validation(dv)
    dv.add(f"B5:B100")

    # 调整列宽
    ws.column_dimensions['A'].width = 20
    ws.column_dimensions['B'].width = 15
    ws.column_dimensions['C'].width = 20

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=signers_template.xlsx"}
    )




# ==================== 项目管理 ====================

def generate_unique_project_no(db: Session, fiscal_year: int) -> str:
    """Called under the SQLite write lock held by create_project."""
    prefix = f"PRJ-{fiscal_year}-"
    project_ids = db.query(models.Project.project_id).filter(
        models.Project.project_id.like(f"{prefix}%")
    ).all()
    last_seq = max((
        int(project_id[0][len(prefix):])
        for project_id in project_ids
        if project_id[0][len(prefix):].isdigit()
    ), default=0)
    return f"{prefix}{last_seq + 1:04d}"


def resolve_project(db: Session, project_id: str):
    """根据数字ID或项目编号（PRJ-2026-0002）解析项目"""
    if project_id.isdigit():
        project = db.query(models.Project).filter(
            models.Project.id == int(project_id),
            models.Project.is_deleted == False
        ).first()
    else:
        project = db.query(models.Project).filter(
            models.Project.project_id == project_id,
            models.Project.is_deleted == False
        ).first()
    return project


@app.get("/api/projects", response_model=schemas.ProjectListResponse)
async def list_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    firm: Optional[str] = None,
    report_type: Optional[str] = None,
    project_status: Optional[str] = None,
    leader_id: Optional[int] = None,
    year: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.Project).filter(models.Project.is_deleted == False)

    # 执业人员只能看自己参与的项目
    if current_user.role == models.UserRole.PRACTITIONER.value:
        query = query.filter(
            or_(
                models.Project.leader_id == current_user.id,
                models.Project.members.any(models.ProjectMember.user_id == current_user.id),
                models.Project.signer1.has(models.Signer.user_id == current_user.id),
                models.Project.signer2.has(models.Signer.user_id == current_user.id),
            )
        )

    # 筛选条件
    if search:
        query = query.filter(
            (models.Project.customer_name.contains(search)) |
            (models.Project.project_id.contains(search)) |
            (models.Project.report_no.contains(search))
        )
    if firm:
        query = query.filter(models.Project.firm == firm)
    if report_type:
        query = query.filter(models.Project.report_type == report_type)
    if project_status:
        query = query.filter(models.Project.project_status == project_status)
    if leader_id:
        query = query.filter(models.Project.leader_id == leader_id)
    if year:
        # 指定年份时，按报告编号年份过滤
        query = query.filter(models.Project.report_year == year)
    else:
        # 默认按当前用户的操作年度过滤
        query = query.filter(models.Project.fiscal_year == current_user.fiscal_year)

    total = query.count()
    items = query.order_by(models.Project.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    # 显式转换为 Pydantic 模型，确保 fiscal_year 字段被正确序列化
    return schemas.ProjectListResponse(
        items=[schemas.ProjectResponse.from_orm(item) for item in items],
        total=total,
        page=page,
        page_size=page_size
    )


@app.get("/api/projects/signed-by-me", response_model=schemas.ProjectListResponse)
async def signed_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role != models.UserRole.PRACTITIONER.value:
        raise HTTPException(status_code=403, detail="只有执业人员可查看签字项目")
    query = db.query(models.Project).filter(
        models.Project.is_deleted == False,
        models.Project.fiscal_year == current_user.fiscal_year,
        or_(
            models.Project.signer1.has(models.Signer.user_id == current_user.id),
            models.Project.signer2.has(models.Signer.user_id == current_user.id),
        ),
    )
    return schemas.ProjectListResponse(
        items=[schemas.ProjectResponse.from_orm(item) for item in query.order_by(
            models.Project.created_at.desc(), models.Project.id.desc()
        ).offset((page - 1) * page_size).limit(page_size).all()],
        total=query.count(), page=page, page_size=page_size,
    )


@app.get("/api/projects/{project_id}", response_model=schemas.ProjectResponse)
async def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    project = resolve_project(db, project_id)

    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    if not can_view_project(current_user, project):
        raise HTTPException(status_code=403, detail="无权限查看此项目")

    return project


@app.get("/api/projects/{project_id}/report-number-history", response_model=List[schemas.ReportNumberHistoryResponse])
async def get_report_number_history(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    project = resolve_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    if not can_view_project(current_user, project):
        raise HTTPException(status_code=403, detail="无权限查看此项目")
    return db.query(models.ReportNumberHistory).filter_by(project_id=project.id).order_by(
        models.ReportNumberHistory.id.desc()
    ).all()


@app.post("/api/projects", response_model=schemas.ProjectResponse)
async def create_project(
    project_data: schemas.ProjectCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if not can_create_project(current_user):
        raise HTTPException(status_code=403, detail="无权限创建项目")

    if db.get_bind().dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))

    # 获取用户的当前操作年度
    fiscal_year = current_user.fiscal_year or datetime.now().year

    # 报告年份不能超过编号年度
    if project_data.report_year > fiscal_year:
        raise HTTPException(
            status_code=400,
            detail=f"业务年度({project_data.report_year}年)不能超过编号年度({fiscal_year}年)"
        )

    try:
        get_rule(db, project_data.firm, project_data.report_type, fiscal_year)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    validate_project_people(db, project_data.leader_id, project_data.member_ids or [])
    validate_project_signers(db, (project_data.signer1_id, project_data.signer2_id), project_data.firm)

    # 生成项目ID（使用当前操作年度），带竞态条件保护
    project_id = generate_unique_project_no(db, fiscal_year)

    project = models.Project(
        project_id=project_id,
        firm=project_data.firm,
        report_type=project_data.report_type,
        report_year=project_data.report_year,
        customer_name=project_data.customer_name,
        contract_no=project_data.contract_no,
        order_date=project_data.order_date,
        leader_id=project_data.leader_id,
        project_status=project_data.project_status,
        project_phase=project_data.project_phase,
        priority=project_data.priority,
        scale=project_data.scale,
        business_source=project_data.business_source,
        contract_amount=project_data.contract_amount,
        signer1_id=project_data.signer1_id,
        signer2_id=project_data.signer2_id,
        uninvoiced_amount=project_data.contract_amount,
        unreceived_amount=0,
        report_no_status=models.ReportStatus.PENDING.value,
        fiscal_year=fiscal_year  # 保存创建时的编号年度
    )
    db.add(project)

    db.flush()
    db.add(models.FinanceMigration(project_id=project.id))

    # 添加团队成员
    for member_id in (project_data.member_ids or []):
        member = models.ProjectMember(project_id=project.id, user_id=member_id)
        db.add(member)

    db.commit()
    db.refresh(project)
    return project


@app.put("/api/projects/{project_id}", response_model=schemas.ProjectResponse)
async def update_project(
    project_id: str,
    project_data: schemas.ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    project = resolve_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    update_data = project_data.dict(exclude_unset=True)
    if update_data and not can_edit_project(current_user, project):
        raise HTTPException(status_code=403, detail="无权限编辑此项目")

    if project.report_no and any(
        field in update_data and update_data[field] != getattr(project, field)
        for field in ("firm", "report_type", "report_year")
    ):
        raise HTTPException(status_code=400, detail="已有编号的项目不能修改事务所、业务类型或业务年度")

    if 'report_year' in update_data and (
        update_data['report_year'] is None or update_data['report_year'] > project.fiscal_year
    ):
        raise HTTPException(status_code=400, detail="业务年度不能超过项目编号年度，且不能为空")

    # 验证签字人联动：签字人一和签字人二不能为同一人
    signer1_id = update_data.get('signer1_id', project.signer1_id)
    signer2_id = update_data.get('signer2_id', project.signer2_id)
    firm = update_data.get('firm', project.firm)
    report_type = update_data.get('report_type', project.report_type)

    if 'firm' in update_data or 'report_type' in update_data:
        try:
            get_rule(db, firm, report_type, project.fiscal_year)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    validate_project_signers(db, (signer1_id, signer2_id), firm, project)
    validate_project_people(
        db, update_data.get('leader_id', project.leader_id),
        update_data.get('member_ids', [member.user_id for member in project.members]) or [], project,
    )

    # 处理团队成员
    if 'member_ids' in update_data:
        member_ids = update_data.pop('member_ids')
        # 清除旧成员（使用数据库数字ID）
        db.query(models.ProjectMember).filter(
            models.ProjectMember.project_id == project.id
        ).delete()
        # 添加新成员
        for mid in (member_ids or []):
            db.add(models.ProjectMember(project_id=project.id, user_id=mid))

    # 更新其他字段
    for field, value in update_data.items():
        setattr(project, field, value)

    # 更新计算字段
    refresh_project_finance(db, project)

    try:
        db.commit()
        db.refresh(project)
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"保存失败: {str(e)}")

    return project


def finance_kind(kind: str) -> str:
    kinds = {"invoices": "invoice", "receipts": "receipt"}
    if kind not in kinds:
        raise HTTPException(status_code=404, detail="财务记录类型不存在")
    return kinds[kind]


def finance_project(db: Session, project_id: str, user: models.User, write: bool = False):
    project = resolve_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    if write and not can_edit_financial_fields(user):
        raise HTTPException(status_code=403, detail="无权限编辑财务记录")
    if not can_view_project(user, project):
        raise HTTPException(status_code=403, detail="无权限查看此项目")
    return project


@app.get("/api/projects/{project_id}/finance/{kind}", response_model=List[schemas.FinancialEntryResponse])
async def list_financial_entries(
    project_id: str, kind: str, db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    entry_kind = finance_kind(kind)
    project = finance_project(db, project_id, current_user)
    return db.query(models.FinancialEntry).filter_by(
        project_id=project.id, kind=entry_kind
    ).order_by(models.FinancialEntry.occurred_on.desc(), models.FinancialEntry.id.desc()).all()


@app.post("/api/projects/{project_id}/finance/{kind}", response_model=schemas.FinancialEntryResponse)
async def create_financial_entry(
    project_id: str, kind: str, data: schemas.FinancialEntryCreate,
    db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user),
):
    entry_kind = finance_kind(kind)
    project = finance_project(db, project_id, current_user, write=True)
    entry = models.FinancialEntry(
        project_id=project.id, kind=entry_kind, amount_cents=cents(data.amount),
        occurred_on=data.occurred_on, reference=data.reference, note=data.note,
    )
    db.add(entry)
    db.flush()
    refresh_project_finance(db, project)
    db.commit()
    db.refresh(entry)
    return entry


def get_financial_entry(db: Session, project: models.Project, kind: str, entry_id: int):
    entry = db.query(models.FinancialEntry).filter_by(
        id=entry_id, project_id=project.id, kind=finance_kind(kind)
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="财务记录不存在")
    return entry


@app.put("/api/projects/{project_id}/finance/{kind}/{entry_id}", response_model=schemas.FinancialEntryResponse)
async def update_financial_entry(
    project_id: str, kind: str, entry_id: int, data: schemas.FinancialEntryUpdate,
    db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user),
):
    project = finance_project(db, project_id, current_user, write=True)
    entry = get_financial_entry(db, project, kind, entry_id)
    changes = data.dict(exclude_unset=True)
    if 'occurred_on' in changes and changes['occurred_on'] is None and not entry.is_legacy:
        raise HTTPException(status_code=400, detail="日期不能为空")
    if 'amount' in changes:
        if changes['amount'] is None:
            raise HTTPException(status_code=400, detail="金额不能为空")
        entry.amount_cents = cents(changes.pop('amount'))
    for field, value in changes.items():
        setattr(entry, field, value)
    db.flush()
    refresh_project_finance(db, project)
    db.commit()
    db.refresh(entry)
    return entry


@app.delete("/api/projects/{project_id}/finance/{kind}/{entry_id}")
async def delete_financial_entry(
    project_id: str, kind: str, entry_id: int,
    db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user),
):
    project = finance_project(db, project_id, current_user, write=True)
    entry = get_financial_entry(db, project, kind, entry_id)
    db.delete(entry)
    db.flush()
    refresh_project_finance(db, project)
    db.commit()
    return {"message": "财务记录已删除"}


@app.delete("/api/projects/{project_id}")
async def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    project = resolve_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    if not can_delete_project(current_user, project):
        raise HTTPException(status_code=403, detail="无权限删除项目")

    # 软删除并回收编号
    project.is_deleted = True
    recycle_report_no(db, project)
    db.commit()

    return {"message": "删除成功，编号已回收"}


# ==================== 报告编号生成 ====================
@app.post("/api/projects/{project_id}/generate-report-no")
async def generate_report_number(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if not can_generate_report_no(current_user):
        raise HTTPException(status_code=403, detail="无权限生成编号")

    if db.get_bind().dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))

    project = resolve_project(db, project_id)

    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 生成编号时始终使用项目创建时的编号年度。
    fiscal_year = project.fiscal_year

    if not can_edit_project(current_user, project):
        raise HTTPException(status_code=403, detail="无权限为此项目生成编号")

    # 检查是否可以生成编号
    if project.report_no_status == models.ReportStatus.ASSIGNED.value:
        raise HTTPException(status_code=400, detail="项目已有报告编号")

    # 验证基础信息完整性
    if not all([project.firm, project.report_type, project.report_year, project.customer_name]):
        raise HTTPException(status_code=400, detail="请先填写完整基础信息")

    # 检查业务年度是否超过编号年度
    if project.report_year > fiscal_year:
        raise HTTPException(
            status_code=400,
            detail=f"业务年度({project.report_year}年)不能超过编号年度({fiscal_year}年)"
        )

    # 使用项目创建时保存的编号年度，与业务年度无关。
    try:
        report_no = generate_report_no(
            db, project.firm, project.report_type, fiscal_year
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 已删除或已回收项目的编号也保留，不能再次发放。
    existing = db.query(models.ReportNumberHistory.id).filter_by(report_no=report_no).first()
    if not existing:
        existing = db.query(models.Project.id).filter_by(report_no=report_no).first()
    if existing:
        db.rollback()
        raise HTTPException(status_code=409, detail="编号与历史项目冲突，请检查编号规则")

    project.report_no = report_no
    project.report_no_status = models.ReportStatus.ASSIGNED.value
    if db.get_bind().dialect.name != "sqlite":
        db.add(models.ReportNumberHistory(project_id=project.id, report_no=report_no))
    db.commit()
    db.refresh(project)

    return {"report_no": report_no, "message": "编号生成成功"}


@app.post("/api/projects/{project_id}/recycle-report-no")
async def recycle_report_number(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if not can_delete_project(current_user):
        raise HTTPException(status_code=403, detail="无权限回收编号")

    project = resolve_project(db, project_id)

    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    if not project.report_no:
        raise HTTPException(status_code=400, detail="项目没有报告编号")
    if project.report_no_status == models.ReportStatus.RECYCLED.value:
        raise HTTPException(status_code=400, detail="编号已回收")

    recycle_report_no(db, project)
    db.commit()
    db.refresh(project)

    return {"message": "编号已回收"}


# ==================== 看板统计 ====================
@app.get("/api/dashboard", response_model=schemas.DashboardStats)
async def get_dashboard(
    fiscal_year: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    from calendar import monthrange

    query = db.query(models.Project).filter(models.Project.is_deleted == False)

    # 按年度过滤：如果提供了 fiscal_year 参数则使用，否则使用当前用户的操作年度
    filter_year = fiscal_year or current_user.fiscal_year
    if filter_year:
        query = query.filter(models.Project.fiscal_year == filter_year)

    # 执业人员只能看自己的项目
    if current_user.role == models.UserRole.PRACTITIONER.value:
        query = query.filter(
            or_(
                models.Project.leader_id == current_user.id,
                models.Project.members.any(models.ProjectMember.user_id == current_user.id),
                models.Project.signer1.has(models.Signer.user_id == current_user.id),
                models.Project.signer2.has(models.Signer.user_id == current_user.id),
            )
        )

    projects = query.all()

    # 统计
    total = len(projects)
    ongoing = len([p for p in projects if p.project_status == "进行中"])
    completed = len([p for p in projects if p.project_status == "已完成"])
    paused = len([p for p in projects if p.project_status == "已暂停"])
    cancelled = len([p for p in projects if p.project_status == "已取消"])

    # 本月新增
    now = datetime.now()
    first_day = datetime(now.year, now.month, 1)
    this_month_new = len([p for p in projects if p.created_at >= first_day])

    # 金额统计
    total_contract = sum(p.contract_amount or 0 for p in projects)
    total_invoiced = sum(p.invoiced_amount or 0 for p in projects)
    total_received = sum(p.received_amount or 0 for p in projects)
    total_uninvoiced = sum(p.uninvoiced_amount or 0 for p in projects)
    total_unreceived = sum(p.unreceived_amount or 0 for p in projects)

    return schemas.DashboardStats(
        total_projects=total,
        ongoing_projects=ongoing,
        completed_projects=completed,
        paused_projects=paused,
        cancelled_projects=cancelled,
        this_month_new=this_month_new,
        total_contract_amount=total_contract,
        total_invoiced_amount=total_invoiced,
        total_received_amount=total_received,
        total_uninvoiced=total_uninvoiced,
        total_unreceived=total_unreceived
    )


@app.get("/api/public/numbered-years")
async def public_list_numbered_years(db: Session = Depends(get_db)):
    years = db.query(models.FiscalYear.year).order_by(
        models.FiscalYear.year.desc()
    ).all()
    return {"years": [y[0] for y in years]}


# ==================== 编号年度配置管理 ====================

@app.get("/api/numbered-years/options")
async def numbered_year_options(
    year: Optional[int] = None,
    firm: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    years = get_available_report_years(db)
    if year is None:
        firms = [name for (name,) in db.query(models.FiscalYearFirm.firm).distinct().order_by(
            models.FiscalYearFirm.firm
        ).all()]
    else:
        firms = get_available_firms(db, year)
    return {
        "years": years,
        "fiscal_year": current_user.fiscal_year,
        "firms": firms,
        "report_types": get_available_report_types(db, firm, year) if firm and year else [],
    }

@app.get("/api/numbered-years")
async def list_numbered_years(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """获取所有年度（树形结构）"""
    if not can_manage_fiscal_config(current_user):
        raise HTTPException(status_code=403, detail="无权限管理")

    # 获取所有年度
    fiscal_years = db.query(models.FiscalYear).order_by(models.FiscalYear.year.desc()).all()

    result = []
    for fy in fiscal_years:
        # 获取该年度下的所有事务所
        firms = db.query(models.FiscalYearFirm).filter(
            models.FiscalYearFirm.fiscal_year_id == fy.id
        ).all()

        firm_list = []
        for firm in firms:
            # 获取该事务所下的所有编号规则
            rules = db.query(models.ReportNumberRule).filter(
                models.ReportNumberRule.fiscal_year_firm_id == firm.id
            ).all()

            # 获取该事务所下的所有业务类型
            report_types = db.query(models.FiscalYearReportType).filter(
                models.FiscalYearReportType.fiscal_year_firm_id == firm.id
            ).all()

            # 关联规则名称
            rule_map = {r.id: r.rule_name for r in rules}
            report_type_list = []
            for rt in report_types:
                report_type_list.append({
                    "id": rt.id,
                    "report_type": rt.report_type,
                    "rule_id": rt.rule_id,
                    "rule_name": rule_map.get(rt.rule_id, "未知规则"),
                    "created_at": rt.created_at.isoformat() if rt.created_at else None
                })

            rule_list = [{"id": r.id, "rule_name": r.rule_name, "template": r.template,
                          "sequence_digits": r.sequence_digits, "current_sequence": r.current_sequence,
                          "is_active": r.is_active} for r in rules]

            firm_list.append({
                "id": firm.id,
                "firm": firm.firm,
                "rules": rule_list,
                "report_types": report_type_list
            })

        result.append({
            "id": fy.id,
            "year": fy.year,
            "is_active": fy.is_active,
            "firms": firm_list
        })

    return result


# 年度管理
@app.post("/api/numbered-years", response_model=schemas.FiscalYearResponse)
async def create_numbered_year(
    data: schemas.FiscalYearCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """创建年度"""
    if not can_manage_fiscal_config(current_user):
        raise HTTPException(status_code=403, detail="无权限管理")

    year = validate_config_year(data.year)
    # 检查是否已存在
    existing = db.query(models.FiscalYear).filter(models.FiscalYear.year == year).first()
    if existing:
        raise HTTPException(status_code=400, detail="该年度已存在")

    fy = models.FiscalYear(year=year)
    db.add(fy)
    db.commit()
    db.refresh(fy)
    return fy


@app.delete("/api/numbered-years/{year_id}")
async def delete_numbered_year(
    year_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """删除年度（级联删除事务所、规则、业务类型）"""
    if not can_manage_fiscal_config(current_user):
        raise HTTPException(status_code=403, detail="无权限管理")

    fy = db.query(models.FiscalYear).filter(models.FiscalYear.id == year_id).first()
    if not fy:
        raise HTTPException(status_code=404, detail="年度不存在")

    if db.query(models.Project.id).filter_by(fiscal_year=fy.year).first():
        raise HTTPException(status_code=400, detail="该年度已有项目，不能删除")
    if db.query(models.User.id).filter_by(fiscal_year=fy.year).first():
        raise HTTPException(status_code=400, detail="有用户正在使用该年度，请先切换操作年度")

    for firm in db.query(models.FiscalYearFirm).filter_by(fiscal_year_id=fy.id).all():
        db.delete(firm)
    db.delete(fy)
    db.commit()
    return {"message": "删除成功"}


# 事务所管理
@app.post("/api/numbered-years/firms", response_model=schemas.FiscalYearFirmResponse)
async def create_fiscal_year_firm(
    data: schemas.FiscalYearFirmCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """在年度下创建事务所"""
    if not can_manage_fiscal_config(current_user):
        raise HTTPException(status_code=403, detail="无权限管理")

    firm_name = normalize_required_text(data.firm, "事务所名称", 100)
    # 检查年度是否存在
    fy = db.query(models.FiscalYear).filter(models.FiscalYear.id == data.fiscal_year_id).first()
    if not fy:
        raise HTTPException(status_code=404, detail="年度不存在")

    # 检查是否已存在
    existing = db.query(models.FiscalYearFirm).filter(
        models.FiscalYearFirm.fiscal_year_id == data.fiscal_year_id,
        models.FiscalYearFirm.firm == firm_name
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="该事务所在此年度已存在")

    firm = models.FiscalYearFirm(fiscal_year_id=data.fiscal_year_id, firm=firm_name)
    db.add(firm)
    db.commit()
    db.refresh(firm)
    return firm


@app.delete("/api/numbered-years/firms/{firm_id}")
async def delete_fiscal_year_firm(
    firm_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """删除事务所（级联删除规则和业务类型）"""
    if not can_manage_fiscal_config(current_user):
        raise HTTPException(status_code=403, detail="无权限管理")

    firm = db.query(models.FiscalYearFirm).filter(models.FiscalYearFirm.id == firm_id).first()
    if not firm:
        raise HTTPException(status_code=404, detail="事务所不存在")

    if db.query(models.Project.id).filter_by(
        fiscal_year=firm.fiscal_year.year, firm=firm.firm
    ).first():
        raise HTTPException(status_code=400, detail="该事务所已有项目，不能删除")

    db.delete(firm)
    db.commit()
    return {"message": "删除成功"}


# 编号规则管理
@app.post("/api/numbered-years/rules", response_model=schemas.ReportNumberRuleResponse)
async def create_report_number_rule(
    data: schemas.ReportNumberRuleCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """创建编号规则"""
    if not can_manage_fiscal_config(current_user):
        raise HTTPException(status_code=403, detail="无权限管理")
    if db.get_bind().dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))

    rule_name = normalize_required_text(data.rule_name, "规则名称", 50)
    template = normalize_required_text(data.template, "编号模板", 200)
    # 检查事务所是否存在
    firm = db.query(models.FiscalYearFirm).filter(models.FiscalYearFirm.id == data.fiscal_year_firm_id).first()
    if not firm:
        raise HTTPException(status_code=404, detail="事务所不存在")

    # 检查规则名是否已存在
    existing = db.query(models.ReportNumberRule).filter(
        models.ReportNumberRule.fiscal_year_firm_id == data.fiscal_year_firm_id,
        models.ReportNumberRule.rule_name == rule_name
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="该规则名称已存在")

    sequence_digits = validate_setup_template(template)
    if 'sequence_digits' in data.__fields_set__ and data.sequence_digits != sequence_digits:
        raise HTTPException(status_code=400, detail="编号位数必须与模板序号占位符一致")
    ensure_unique_numbering_format(db, template, firm.fiscal_year.year)

    rule = models.ReportNumberRule(
        fiscal_year_firm_id=data.fiscal_year_firm_id,
        rule_name=rule_name,
        template=template,
        sequence_digits=sequence_digits
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@app.put("/api/numbered-years/rules/{rule_id}", response_model=schemas.ReportNumberRuleResponse)
async def update_report_number_rule(
    rule_id: int,
    data: schemas.ReportNumberRuleUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """更新编号规则"""
    if not can_manage_fiscal_config(current_user):
        raise HTTPException(status_code=403, detail="无权限管理")
    if db.get_bind().dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))

    rule = db.query(models.ReportNumberRule).filter(models.ReportNumberRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")

    changes = data.dict(exclude_unset=True)
    if any(value is None for value in changes.values()):
        raise HTTPException(status_code=400, detail="规则字段不能为空")
    if 'rule_name' in changes:
        changes['rule_name'] = normalize_required_text(changes['rule_name'], "规则名称", 50)
    if 'template' in changes:
        changes['template'] = normalize_required_text(changes['template'], "编号模板", 200)
    if 'rule_name' in changes and changes['rule_name'] != rule.rule_name:
        if db.query(models.ReportNumberRule.id).filter_by(
            fiscal_year_firm_id=rule.fiscal_year_firm_id, rule_name=changes['rule_name']
        ).first():
            raise HTTPException(status_code=400, detail="该规则名称已存在")
    if 'template' in changes or 'sequence_digits' in changes:
        sequence_digits = validate_setup_template(changes.get('template', rule.template))
        if 'sequence_digits' in changes and changes['sequence_digits'] != sequence_digits:
            raise HTTPException(status_code=400, detail="编号位数必须与模板序号占位符一致")
        if rule.current_sequence and changes.get('template', rule.template) != rule.template:
            raise HTTPException(status_code=400, detail="该规则已有编号，不能修改模板")
        changes['sequence_digits'] = sequence_digits
        ensure_unique_numbering_format(
            db, changes.get('template', rule.template), rule.fiscal_year_firm.fiscal_year.year, rule.id
        )

    for key, value in changes.items():
        setattr(rule, key, value)

    db.commit()
    db.refresh(rule)
    return rule


@app.delete("/api/numbered-years/rules/{rule_id}")
async def delete_report_number_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """删除编号规则"""
    if not can_manage_fiscal_config(current_user):
        raise HTTPException(status_code=403, detail="无权限管理")

    rule = db.query(models.ReportNumberRule).filter(models.ReportNumberRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")

    if rule.report_types or rule.current_sequence:
        raise HTTPException(status_code=400, detail="规则已关联业务类型或已有编号，请停用规则")

    db.delete(rule)
    db.commit()
    return {"message": "删除成功"}


# 业务类型管理
@app.post("/api/numbered-years/report-types", response_model=schemas.FiscalYearReportTypeResponse)
async def create_fiscal_year_report_type(
    data: schemas.FiscalYearReportTypeCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """创建业务类型（关联到编号规则）"""
    if not can_manage_fiscal_config(current_user):
        raise HTTPException(status_code=403, detail="无权限管理")

    report_type = normalize_required_text(data.report_type, "业务类型名称", 100)
    # 检查事务所是否存在
    firm = db.query(models.FiscalYearFirm).filter(models.FiscalYearFirm.id == data.fiscal_year_firm_id).first()
    if not firm:
        raise HTTPException(status_code=404, detail="事务所不存在")

    # 检查规则是否存在
    rule = db.query(models.ReportNumberRule).filter(models.ReportNumberRule.id == data.rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    if rule.fiscal_year_firm_id != firm.id:
        raise HTTPException(status_code=400, detail="业务类型只能关联同一事务所的编号规则")

    # 检查业务类型是否已存在
    existing = db.query(models.FiscalYearReportType).filter(
        models.FiscalYearReportType.fiscal_year_firm_id == data.fiscal_year_firm_id,
        models.FiscalYearReportType.report_type == report_type
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="该业务类型已存在")

    rt = models.FiscalYearReportType(
        fiscal_year_firm_id=data.fiscal_year_firm_id,
        report_type=report_type,
        rule_id=data.rule_id
    )
    db.add(rt)
    db.commit()
    db.refresh(rt)
    return rt


@app.put("/api/numbered-years/report-types/{rt_id}", response_model=schemas.FiscalYearReportTypeResponse)
async def update_fiscal_year_report_type(
    rt_id: int,
    data: schemas.FiscalYearReportTypeUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """更新业务类型（修改名称或关联规则）"""
    if not can_manage_fiscal_config(current_user):
        raise HTTPException(status_code=403, detail="无权限管理")

    rt = db.query(models.FiscalYearReportType).filter(models.FiscalYearReportType.id == rt_id).first()
    if not rt:
        raise HTTPException(status_code=404, detail="业务类型不存在")

    if data.report_type is not None:
        data.report_type = normalize_required_text(data.report_type, "业务类型名称", 100)

    # 更新业务类型名称
    if data.report_type is not None and data.report_type != rt.report_type:
        firm = rt.fiscal_year_firm
        if db.query(models.Project.id).filter_by(
            fiscal_year=firm.fiscal_year.year, firm=firm.firm, report_type=rt.report_type
        ).first():
            raise HTTPException(status_code=400, detail="该业务类型已有项目，不能改名")
        existing = db.query(models.FiscalYearReportType).filter(
            models.FiscalYearReportType.fiscal_year_firm_id == rt.fiscal_year_firm_id,
            models.FiscalYearReportType.report_type == data.report_type
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="该业务类型已存在")
        rt.report_type = data.report_type

    # 更新关联规则
    if data.rule_id is not None and data.rule_id != rt.rule_id:
        rule = db.query(models.ReportNumberRule).filter(models.ReportNumberRule.id == data.rule_id).first()
        if not rule:
            raise HTTPException(status_code=404, detail="规则不存在")
        if rule.fiscal_year_firm_id != rt.fiscal_year_firm_id:
            raise HTTPException(status_code=400, detail="业务类型只能关联同一事务所的编号规则")
        rt.rule_id = data.rule_id

    db.commit()
    db.refresh(rt)
    return rt


@app.delete("/api/numbered-years/report-types/{rt_id}")
async def delete_fiscal_year_report_type(
    rt_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """删除业务类型"""
    if not can_manage_fiscal_config(current_user):
        raise HTTPException(status_code=403, detail="无权限管理")

    rt = db.query(models.FiscalYearReportType).filter(models.FiscalYearReportType.id == rt_id).first()
    if not rt:
        raise HTTPException(status_code=404, detail="业务类型不存在")

    firm = rt.fiscal_year_firm
    if db.query(models.Project.id).filter_by(
        fiscal_year=firm.fiscal_year.year, firm=firm.firm, report_type=rt.report_type
    ).first():
        raise HTTPException(status_code=400, detail="该业务类型已有项目，不能删除")

    db.delete(rt)
    db.commit()
    return {"message": "删除成功"}


# ==================== Excel 导出 ====================
@app.get("/api/export/projects")
async def export_projects(
    fiscal_year: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if not can_export(current_user):
        raise HTTPException(status_code=403, detail="无权限导出")

    query = db.query(models.Project).filter(models.Project.is_deleted == False)

    # 按年度过滤：如果提供了 fiscal_year 参数则使用，否则使用当前用户的操作年度
    filter_year = fiscal_year or current_user.fiscal_year
    if filter_year:
        query = query.filter(models.Project.fiscal_year == filter_year)

    projects = query.all()

    wb = Workbook()
    ws = wb.active
    ws.title = "项目列表"

    # 表头
    headers = [
        "项目ID", "事务所", "报告类型", "报告年度", "报告编号", "编号状态",
        "客户名称", "合同号", "下单时间", "执业负责人", "团队成员",
        "项目状态", "项目阶段", "优先级", "项目规模", "业务来源",
        "合同金额", "开票金额", "开票时间", "收款金额", "收款时间",
        "未开票金额", "未收款金额", "签字人一", "签字人一账号",
        "签字人二", "签字人二账号", "创建时间"
    ]
    append_export_row(ws, headers)

    # 数据
    for p in projects:
        try:
            members = ", ".join([m.user.real_name for m in p.members if m.user])
            append_export_row(ws, [
                p.project_id, p.firm, p.report_type, p.report_year, p.report_no or "",
                p.report_no_status, p.customer_name, p.contract_no or "",
                p.order_date.strftime("%Y-%m-%d") if p.order_date else "",
                p.leader.real_name if p.leader else "", members,
                p.project_status, p.project_phase, p.priority, p.scale or "", p.business_source or "",
                p.contract_amount, p.invoiced_amount,
                p.invoice_date.strftime("%Y-%m-%d") if p.invoice_date else "",
                p.received_amount,
                p.receive_date.strftime("%Y-%m-%d") if p.receive_date else "",
                p.uninvoiced_amount, p.unreceived_amount,
                p.signer1.name if p.signer1 else "",
                p.signer1.user.username if p.signer1 and p.signer1.user else "",
                p.signer2.name if p.signer2 else "",
                p.signer2.user.username if p.signer2 and p.signer2.user else "",
                p.created_at.strftime("%Y-%m-%d %H:%M")
            ])
        except Exception as e:
            # 跳过有问题的项目，记录错误
            append_export_row(ws, [p.project_id, f"导出错误: {str(e)}"])

    # 保存到BytesIO
    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=projects_{datetime.now().strftime('%Y%m%d')}.xlsx"}
    )


# ==================== 前端静态文件服务 ====================
# 构建产物可缺席；开发模式下 API 与 Vite 分别运行。
STATIC_DIR = Path(os.getenv("FIRM_MANAGER_STATIC_DIR", Path(__file__).resolve().parent / "static"))
(STATIC_DIR / "assets").mkdir(parents=True, exist_ok=True)

# favicon.ico 专门处理（必须在 catch-all 之前）
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Serve favicon"""
    favicon_path = STATIC_DIR / "favicon.ico"
    if os.path.exists(favicon_path):
        return FileResponse(favicon_path)
    # fallback 到 assets 目录
    assets_favicon = STATIC_DIR / "assets" / "favicon.ico"
    if os.path.exists(assets_favicon):
        return FileResponse(assets_favicon)
    # 兜底：返回 204 No Content，避免 500 错误
    from starlette.responses import Response
    return Response(status_code=204)

# 挂载静态资源目录（assets）
app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

# SPA 路由支持：所有非 API 路径都返回 index.html（由前端 React Router 处理）
# 注意：此路由必须在 assets mount 之后注册，否则 assets 请求会被拦截
@app.get("/{path:path}", include_in_schema=False)
async def serve_spa(path: str):
    """Catch-all route for Single Page Application routing"""
    if path == "api" or path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API 不存在")
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=503, detail="前端尚未构建，请先运行 frontend 的 npm run build 并部署 dist 内容")
    return FileResponse(index_path)


if __name__ == "__main__":
    import uvicorn

    print()
    print("=" * 50)
    print("  事务所项目编号管理系统")
    print("=" * 50)
    print("  访问地址: http://localhost:8000")
    print("  首次访问请在浏览器中完成安装向导")
    print("=" * 50)
    print("  按 Ctrl+C 停止服务")
    print("=" * 50)
    print()

    uvicorn.run(
        app,
        host=os.getenv("FIRM_MANAGER_HOST", "127.0.0.1"),
        port=int(os.getenv("FIRM_MANAGER_PORT", "8000")),
        access_log=False,
        log_level="warning",  # 只显示警告和错误
    )
