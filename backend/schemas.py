from pydantic import BaseModel, condecimal, constr
from typing import Optional, List, Literal
from datetime import datetime, date


# ============ 用户相关 ============
class UserBase(BaseModel):
    username: str
    real_name: str
    role: str


class UserCreate(UserBase):
    username: constr(regex=r"^[A-Za-z0-9_.-]{3,50}$")
    role: Literal["admin", "practitioner", "admin_staff"]
    password: constr(min_length=8)


class UserResponse(UserBase):
    id: int
    fiscal_year: int
    is_active: bool
    created_at: datetime

    class Config:
        orm_mode = True


class UserUpdate(BaseModel):
    real_name: Optional[str] = None
    role: Optional[Literal["admin", "practitioner", "admin_staff"]] = None
    password: Optional[constr(min_length=8)] = None
    is_active: Optional[bool] = None


class PractitionerResponse(BaseModel):
    """执业人员简单信息（用于项目表单选择）"""
    id: int
    username: str
    real_name: str
    role: str
    is_active: bool

    class Config:
        orm_mode = True


# ============ 签字人相关 ============
class SignerBase(BaseModel):
    name: str
    signer_type: str  # 关联的事务所名称


class SignerCreate(BaseModel):
    user_id: int
    signer_type: str


class SignerUpdate(BaseModel):
    user_id: Optional[int] = None
    signer_type: Optional[str] = None


class SignerResponse(SignerBase):
    id: int
    user_id: Optional[int] = None
    user: Optional[PractitionerResponse] = None
    is_active: bool
    disabled_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        orm_mode = True


# ============ 项目相关 ============


# ============ 认证相关 ============
class Token(BaseModel):
    access_token: str
    token_type: str
    fiscal_year: int  # 当前操作年度


class TokenData(BaseModel):
    user_id: int
    username: str
    role: str
    fiscal_year: int  # 当前操作年度


class UserLogin(BaseModel):
    username: str
    password: str
    fiscal_year: Optional[int] = None  # 登录时可选指定年度，不指定则用当前年


class LicenseActivationRequest(BaseModel):
    license_document: dict
    server_url: Optional[str] = None
    instance_name: Optional[str] = None


# ============ 首次安装 ============
class SetupReportType(BaseModel):
    report_type: str
    template: str
    rule_name: Optional[str] = None


class SetupFirm(BaseModel):
    name: str
    report_types: List[SetupReportType]


class SetupRequest(BaseModel):
    admin_username: str
    admin_password: str
    admin_real_name: str
    fiscal_year: int
    firms: List[SetupFirm]
    license_document: Optional[dict] = None
    license_server_url: Optional[str] = None
    instance_name: Optional[str] = None


class SetupStatus(BaseModel):
    initialized: bool


class ProjectMemberBase(BaseModel):
    user_id: int


class ProjectMemberCreate(ProjectMemberBase):
    pass


class ProjectMemberResponse(BaseModel):
    id: int
    user_id: int
    user: Optional[UserResponse] = None

    class Config:
        orm_mode = True


class ProjectBase(BaseModel):
    firm: str
    report_type: str
    report_year: int
    customer_name: str
    contract_no: Optional[str] = None
    order_date: Optional[datetime] = None
    project_status: str = "进行中"
    project_phase: str = "签约"
    priority: str = "中"
    scale: Optional[str] = None
    business_source: Optional[str] = None
    contract_amount: float = 0
    signer1_id: Optional[int] = None
    signer2_id: Optional[int] = None

    class Config:
        orm_mode = True


class ProjectCreate(ProjectBase):
    leader_id: int
    member_ids: Optional[List[int]] = []

    class Config:
        extra = "forbid"


class ProjectUpdate(BaseModel):
    firm: Optional[str] = None
    report_type: Optional[str] = None
    report_year: Optional[int] = None
    customer_name: Optional[str] = None
    contract_no: Optional[str] = None
    order_date: Optional[datetime] = None
    leader_id: Optional[int] = None
    project_status: Optional[str] = None
    project_phase: Optional[str] = None
    priority: Optional[str] = None
    scale: Optional[str] = None
    business_source: Optional[str] = None
    contract_amount: Optional[float] = None
    signer1_id: Optional[int] = None
    signer2_id: Optional[int] = None
    member_ids: Optional[List[int]] = None

    class Config:
        extra = "forbid"


class ProjectResponse(ProjectBase):
    id: int
    project_id: str
    fiscal_year: int  # 编号年度
    report_no: Optional[str] = None
    report_no_status: str
    leader_id: int
    leader: Optional[UserResponse] = None
    members: List[ProjectMemberResponse] = []
    signer1: Optional[SignerResponse] = None
    signer2: Optional[SignerResponse] = None
    invoiced_amount: float = 0
    invoice_date: Optional[datetime] = None
    received_amount: float = 0
    receive_date: Optional[datetime] = None
    uninvoiced_amount: float = 0
    unreceived_amount: float = 0
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class ProjectListResponse(BaseModel):
    items: List[ProjectResponse]
    total: int
    page: int
    page_size: int

    class Config:
        orm_mode = True


class ReportNumberHistoryResponse(BaseModel):
    id: int
    report_no: str
    is_recycled: bool
    is_legacy: bool
    created_at: datetime
    recycled_at: Optional[datetime] = None

    class Config:
        orm_mode = True


class FinancialEntryCreate(BaseModel):
    amount: condecimal(gt=0, max_digits=12, decimal_places=2)
    occurred_on: date
    reference: Optional[constr(max_length=100)] = None
    note: Optional[constr(max_length=500)] = None


class FinancialEntryUpdate(BaseModel):
    amount: Optional[condecimal(gt=0, max_digits=12, decimal_places=2)] = None
    occurred_on: Optional[date] = None
    reference: Optional[constr(max_length=100)] = None
    note: Optional[constr(max_length=500)] = None


class FinancialEntryResponse(BaseModel):
    id: int
    amount: float
    occurred_on: Optional[date]
    reference: Optional[str]
    note: Optional[str]
    is_legacy: bool
    created_at: datetime

    class Config:
        orm_mode = True


# ============ 看板统计 ============
class DashboardStats(BaseModel):
    total_projects: int
    ongoing_projects: int
    completed_projects: int
    paused_projects: int
    cancelled_projects: int
    this_month_new: int
    total_contract_amount: float
    total_invoiced_amount: float
    total_received_amount: float
    total_uninvoiced: float
    total_unreceived: float


# ============ 编号生成 ============
class GenerateReportNoRequest(BaseModel):
    project_id: int
    force_regenerate: bool = False  # 管理员可强制重新生成


# ============ 编号回收 ============
class RecycleReportNoRequest(BaseModel):
    project_id: int


# ============ 新版编号年度配置（三级管理） ============
# 年度
class FiscalYearBase(BaseModel):
    year: int


class FiscalYearCreate(FiscalYearBase):
    pass


class FiscalYearResponse(FiscalYearBase):
    id: int
    is_active: bool
    created_at: datetime

    class Config:
        orm_mode = True


# 年度-事务所组合
class FiscalYearFirmBase(BaseModel):
    firm: str


class FiscalYearFirmCreate(FiscalYearFirmBase):
    fiscal_year_id: int


class FiscalYearFirmResponse(FiscalYearFirmBase):
    id: int
    fiscal_year_id: int
    created_at: datetime

    class Config:
        orm_mode = True


# 编号规则
class ReportNumberRuleBase(BaseModel):
    rule_name: str
    template: str
    sequence_digits: int = 3


class ReportNumberRuleCreate(ReportNumberRuleBase):
    fiscal_year_firm_id: int


class ReportNumberRuleUpdate(BaseModel):
    rule_name: Optional[str] = None
    template: Optional[str] = None
    sequence_digits: Optional[int] = None
    is_active: Optional[bool] = None


class ReportNumberRuleResponse(ReportNumberRuleBase):
    id: int
    fiscal_year_firm_id: int
    current_sequence: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


# 业务类型
class FiscalYearReportTypeBase(BaseModel):
    report_type: str
    rule_id: int


class FiscalYearReportTypeCreate(FiscalYearReportTypeBase):
    fiscal_year_firm_id: int


class FiscalYearReportTypeUpdate(BaseModel):
    report_type: Optional[str] = None
    rule_id: Optional[int] = None


class FiscalYearReportTypeResponse(FiscalYearReportTypeBase):
    id: int
    fiscal_year_firm_id: int
    created_at: datetime

    class Config:
        orm_mode = True
