from sqlalchemy import Column, Integer, String, Float, DateTime, Date, Boolean, ForeignKey, Text, Enum, Index, CheckConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from database import Base


class UserRole(str, enum.Enum):
    ADMIN = "admin"           # 管理人员
    PRACTITIONER = "practitioner"  # 执业人员
    ADMIN_STAFF = "admin_staff"     # 后勤行政


class ReportStatus(str, enum.Enum):
    PENDING = "pending"       # 待编号
    ASSIGNED = "assigned"      # 已编号
    RECYCLED = "recycled"     # 已回收


class Signer(Base):
    """签字人表"""
    __tablename__ = "signers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)  # 签字人姓名
    signer_type = Column(String(100), nullable=False)  # 关联的事务所名称
    is_active = Column(Boolean, default=True)  # 是否启用
    disabled_at = Column(DateTime, nullable=True)  # 禁用时间
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    real_name = Column(String(100), nullable=False)
    role = Column(String(20), nullable=False, default=UserRole.PRACTITIONER.value)
    fiscal_year = Column(Integer, nullable=False)  # 当前操作年度
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关联：作为执业负责人参与的项目
    led_projects = relationship("Project", back_populates="leader", foreign_keys="Project.leader_id")
    # 关联：作为团队成员参与的项目
    team_projects = relationship("ProjectMember", back_populates="user")


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(String(50), unique=True, index=True)  # 系统项目ID，如 PRJ-2026-001
    firm = Column(String(100), nullable=False)  # 事务所名称
    report_type = Column(String(100), nullable=False)  # 业务类型名称
    report_year = Column(Integer, nullable=False)  # 报告年度
    report_no = Column(String(100), unique=True, nullable=True)  # 报告编号
    report_no_status = Column(String(20), default=ReportStatus.PENDING.value)  # pending/assigned/recycled

    customer_name = Column(String(200), nullable=False)  # 客户名称
    contract_no = Column(String(100))  # 合同号
    order_date = Column(DateTime)  # 下单时间

    leader_id = Column(Integer, ForeignKey("users.id"))  # 执业负责人
    leader = relationship("User", back_populates="led_projects", foreign_keys=[leader_id])

    project_status = Column(String(20), default="进行中")  # 进行中/已完成/已暂停/已取消
    project_phase = Column(String(20), default="签约")  # 签约/进场/实施中/报告出具/归档
    priority = Column(String(10), default="中")  # 高/中/低
    scale = Column(String(50))  # 项目规模：会计准则/会计制度/小企业会计准则/民非/高校/社团组织
    business_source = Column(String(50))  # 业务来源

    contract_amount = Column(Float, default=0)  # 合同金额
    invoiced_amount = Column(Float, default=0)  # 开票金额
    invoice_date = Column(DateTime)  # 开票时间
    received_amount = Column(Float, default=0)  # 收款金额
    receive_date = Column(DateTime)  # 收款时间
    uninvoiced_amount = Column(Float, default=0)  # 未开票金额（计算）
    unreceived_amount = Column(Float, default=0)  # 未收款金额（计算）

    signer1_id = Column(Integer, ForeignKey("signers.id"), nullable=True)  # 签字人一
    signer2_id = Column(Integer, ForeignKey("signers.id"), nullable=True)  # 签字人二
    signer1 = relationship("Signer", foreign_keys=[signer1_id])
    signer2 = relationship("Signer", foreign_keys=[signer2_id])

    is_deleted = Column(Boolean, default=False)  # 软删除
    fiscal_year = Column(Integer, nullable=False, index=True)  # 编号年度（创建时的操作年度）
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关联：团队成员
    members = relationship("ProjectMember", back_populates="project", cascade="all, delete-orphan")
    financial_entries = relationship("FinancialEntry", back_populates="project", cascade="all, delete-orphan")

    @property
    def uninvoiced(self):
        return self.contract_amount - self.invoiced_amount

    @property
    def unreceived(self):
        return self.invoiced_amount - self.received_amount


class ProjectMember(Base):
    __tablename__ = "project_members"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    project = relationship("Project", back_populates="members")
    user = relationship("User", back_populates="team_projects")


class FinancialEntry(Base):
    __tablename__ = "financial_entries"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    kind = Column(String(10), nullable=False)  # invoice / receipt
    amount_cents = Column(Integer, nullable=False)
    occurred_on = Column(Date, nullable=True)  # 旧版汇总记录可能没有日期
    reference = Column(String(100), nullable=True)
    note = Column(String(500), nullable=True)
    is_legacy = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now())
    project = relationship("Project", back_populates="financial_entries")

    __table_args__ = (
        CheckConstraint("kind IN ('invoice', 'receipt')"),
        CheckConstraint("amount_cents > 0"),
    )

    @property
    def amount(self):
        return self.amount_cents / 100


class FinanceMigration(Base):
    __tablename__ = "finance_migrations"

    project_id = Column(Integer, ForeignKey("projects.id"), primary_key=True)


class FiscalYear(Base):
    """编号年度表"""
    __tablename__ = "fiscal_years"

    id = Column(Integer, primary_key=True, index=True)
    year = Column(Integer, nullable=False, unique=True, index=True)  # 年度
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class FiscalYearFirm(Base):
    """年度-事务所组合表"""
    __tablename__ = "fiscal_year_firms"

    id = Column(Integer, primary_key=True, index=True)
    fiscal_year_id = Column(Integer, ForeignKey("fiscal_years.id"), nullable=False)
    firm = Column(String(100), nullable=False)  # 事务所名称
    created_at = Column(DateTime, server_default=func.now())

    # 关联
    fiscal_year = relationship("FiscalYear")
    # 一个年度+事务所可以有多条编号规则
    rules = relationship("ReportNumberRule", back_populates="fiscal_year_firm", cascade="all, delete-orphan")
    # 一个年度+事务所可以有多条业务类型
    report_types = relationship("FiscalYearReportType", back_populates="fiscal_year_firm", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_fy_firm_unique', 'fiscal_year_id', 'firm', unique=True),
    )


class ReportNumberRule(Base):
    """编号规则表 - 管理编号模板"""
    __tablename__ = "report_number_rules"

    id = Column(Integer, primary_key=True, index=True)
    fiscal_year_firm_id = Column(Integer, ForeignKey("fiscal_year_firms.id"), nullable=False)
    rule_name = Column(String(50), nullable=False)  # 规则名称，如"年审编号"、"专项编号"
    template = Column(String(200), nullable=False)  # 完整编号模板
    sequence_digits = Column(Integer, default=3)  # 编号位数
    current_sequence = Column(Integer, default=0)  # 当前序号
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关联
    fiscal_year_firm = relationship("FiscalYearFirm", back_populates="rules")
    # 关联到此规则的业务类型
    report_types = relationship("FiscalYearReportType", back_populates="rule")

    __table_args__ = (
        Index('idx_rule_unique', 'fiscal_year_firm_id', 'rule_name', unique=True),
    )


class FiscalYearReportType(Base):
    """业务类型表 - 关联业务类型和编号规则"""
    __tablename__ = "fiscal_year_report_types"

    id = Column(Integer, primary_key=True, index=True)
    fiscal_year_firm_id = Column(Integer, ForeignKey("fiscal_year_firms.id"), nullable=False)
    report_type = Column(String(100), nullable=False)  # 业务类型名称
    rule_id = Column(Integer, ForeignKey("report_number_rules.id"), nullable=False)  # 关联的编号规则
    created_at = Column(DateTime, server_default=func.now())

    # 关联
    fiscal_year_firm = relationship("FiscalYearFirm", back_populates="report_types")
    rule = relationship("ReportNumberRule", back_populates="report_types")

    __table_args__ = (
        Index('idx_rpt_unique', 'fiscal_year_firm_id', 'report_type', unique=True),
    )
