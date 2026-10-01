from sqlalchemy import Column, Integer, String, Float, DateTime, Date, Boolean, ForeignKey, Text, Enum, Index, CheckConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.sql import func
import enum
from database import Base


class UserRole(str, enum.Enum):
    ADMIN = "office_admin"
    NUMBER_MANAGER = "number_manager"
    FINANCE = "finance"
    PRACTITIONER = "practitioner"  # 执业人员
    CLERK = "clerk"


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
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    user = relationship("User")
    is_active = Column(Boolean, default=True)  # 是否启用
    disabled_at = Column(DateTime, nullable=True)  # 禁用时间
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    phone = Column(String(30), unique=True, index=True, nullable=True)
    hashed_password = Column(String(255), nullable=False)
    real_name = Column(String(100), nullable=False)
    is_practitioner = Column(Boolean, nullable=False, default=False)
    permission_revision = Column(Integer, nullable=False, default=1)
    fiscal_year = Column(Integer, nullable=False)  # 当前操作年度
    is_active = Column(Boolean, default=True)
    session_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关联：作为执业负责人参与的项目
    led_projects = relationship("Project", back_populates="leader", foreign_keys="Project.leader_id")
    # 关联：作为团队成员参与的项目
    team_projects = relationship("ProjectMember", back_populates="user")
    role_records = relationship("UserRoleRecord", cascade="all, delete-orphan", lazy="selectin")
    special_grant_records = relationship("UserSpecialGrant", cascade="all, delete-orphan", lazy="selectin")

    @property
    def roles(self):
        return sorted(record.role_code for record in self.role_records)

    @property
    def special_grants(self):
        return sorted(record.permission_code for record in self.special_grant_records)

    @property
    def permissions(self):
        from permissions import effective_permissions
        return sorted(effective_permissions(self))


class UserRoleRecord(Base):
    __tablename__ = "user_roles"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    role_code = Column(String(32), primary_key=True)
    __table_args__ = (CheckConstraint("role_code IN ('office_admin','number_manager','finance','practitioner','clerk')"),)


class UserSpecialGrant(Base):
    __tablename__ = "user_special_grants"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    permission_code = Column(String(64), primary_key=True)
    __table_args__ = (CheckConstraint("permission_code IN ('project.export.related','billing.export_sensitive')"),)


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
    customer_tax_id = Column(String(50), nullable=True, index=True)  # 统一社会信用代码/税号
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)
    contract_no = Column(String(100))  # 合同号
    order_date = Column(DateTime)  # 下单时间

    leader_id = Column(Integer, ForeignKey("users.id"))  # 执业负责人
    leader = relationship("User", back_populates="led_projects", foreign_keys=[leader_id])

    project_status = Column(String(20), default="进行中")  # 进行中/已完成/已暂停/已取消
    project_phase = Column(String(20), default="签约")  # 签约/进场/实施中/报告出具/归档
    priority = Column(String(10), default="中")  # 高/中/低
    scale = Column(String(50))  # 项目规模：会计准则/会计制度/小企业会计准则/民非/高校/社团组织
    business_source = Column(String(50))  # 业务来源

    contract_amount_cents = Column(Integer, nullable=True)
    invoiced_amount_cents = Column(Integer, nullable=False, default=0)
    invoice_date = Column(DateTime)  # 开票时间
    received_amount_cents = Column(Integer, nullable=False, default=0)
    receive_date = Column(DateTime)  # 收款时间

    signer1_id = Column(Integer, ForeignKey("signers.id"), nullable=True)  # 签字人一
    signer2_id = Column(Integer, ForeignKey("signers.id"), nullable=True)  # 签字人二
    signer1 = relationship("Signer", foreign_keys=[signer1_id])
    signer2 = relationship("Signer", foreign_keys=[signer2_id])

    is_deleted = Column(Boolean, default=False)  # 软删除
    fiscal_year = Column(Integer, nullable=False, index=True)  # 编号年度（创建时的操作年度）
    revision = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关联：团队成员
    members = relationship("ProjectMember", back_populates="project", cascade="all, delete-orphan")
    financial_entries = relationship("FinancialEntry", back_populates="project", cascade="all, delete-orphan")
    report_number_history = relationship("ReportNumberHistory", back_populates="project")
    customer = relationship("Customer", back_populates="projects")

    @hybrid_property
    def contract_amount(self):
        return self.contract_amount_cents / 100 if self.contract_amount_cents is not None else None

    @contract_amount.setter
    def contract_amount(self, value):
        from finance import cents
        self.contract_amount_cents = cents(value) if value is not None else None

    @contract_amount.expression
    def contract_amount(cls):
        return cls.contract_amount_cents / 100

    @property
    def invoiced_amount(self):
        return (self.invoiced_amount_cents or 0) / 100

    @invoiced_amount.setter
    def invoiced_amount(self, value):
        from finance import cents
        self.invoiced_amount_cents = cents(value)

    @property
    def received_amount(self):
        return (self.received_amount_cents or 0) / 100

    @received_amount.setter
    def received_amount(self, value):
        from finance import cents
        self.received_amount_cents = cents(value)

    @property
    def uninvoiced_amount(self):
        return (self.contract_amount_cents - (self.invoiced_amount_cents or 0)) / 100 if self.contract_amount_cents is not None else None

    @property
    def unreceived_amount(self):
        return ((self.invoiced_amount_cents or 0) - (self.received_amount_cents or 0)) / 100

    @property
    def uninvoiced(self):
        return self.contract_amount - self.invoiced_amount

    @property
    def unreceived(self):
        return self.invoiced_amount - self.received_amount


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    csrf_hash = Column(String(64), nullable=False)
    session_version = Column(Integer, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    revoked_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())


class Customer(Base):
    """客户主体主数据；税号稳定，名称变更记录在 aliases。"""
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    tax_id = Column(String(50), nullable=True, unique=True, index=True)
    name = Column(String(200), nullable=False)
    type = Column(String(16), nullable=False, default="enterprise")
    identity_status = Column(String(16), nullable=False, default="pending")
    revision = Column(Integer, nullable=False, default=1)
    created_by = Column(Integer, ForeignKey("users.id"))
    updated_by = Column(Integer, ForeignKey("users.id"))
    merged_into_id = Column(Integer, ForeignKey("customers.id"))
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    projects = relationship("Project", back_populates="customer")
    aliases = relationship("CustomerAlias", back_populates="customer", cascade="all, delete-orphan")
    __table_args__ = (CheckConstraint("type IN ('enterprise','individual','overseas')"),
                      CheckConstraint("identity_status IN ('pending','confirmed','merged')"),
                      Index("idx_customer_name", "name", "id"))


class CustomerAlias(Base):
    __tablename__ = "customer_aliases"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    valid_from = Column(DateTime, server_default=func.now())
    valid_to = Column(DateTime, nullable=True)

    customer = relationship("Customer", back_populates="aliases")

    __table_args__ = (Index("uq_customer_alias_name", "customer_id", "name", unique=True),)


class CustomerChangeRequest(Base):
    __tablename__ = "customer_change_requests"
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), index=True)
    kind = Column(String(32), nullable=False)
    status = Column(String(16), nullable=False, default="submitted", index=True)
    proposal_json = Column(Text, nullable=False)
    submitted_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    reviewed_by = Column(Integer, ForeignKey("users.id"))
    reason = Column(String(500))
    revision = Column(Integer, nullable=False, default=1)
    customer_revision = Column(Integer)
    created_at = Column(DateTime, server_default=func.now())
    reviewed_at = Column(DateTime)


class ProjectChangeRequest(Base):
    __tablename__ = 'project_change_requests'
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False, index=True)
    kind = Column(String(20), nullable=False)
    target_leader_id = Column(Integer, ForeignKey('users.id'))
    project_revision = Column(Integer, nullable=False)
    submitted_by = Column(Integer, ForeignKey('users.id'), nullable=False)
    reason = Column(String(500), nullable=False)
    status = Column(String(20), nullable=False, default='submitted', index=True)
    revision = Column(Integer, nullable=False, default=1)
    reviewed_by = Column(Integer, ForeignKey('users.id'))
    review_reason = Column(String(500))
    created_at = Column(DateTime, server_default=func.now())
    reviewed_at = Column(DateTime)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id = Column(Integer, primary_key=True)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    action = Column(String(64), nullable=False)
    target_type = Column(String(32), nullable=False)
    target_id = Column(Integer, nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"))
    customer_id = Column(Integer, ForeignKey("customers.id"))
    request_id = Column(String(64))
    reason = Column(String(500))
    redacted_diff = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (Index("idx_audit_target_time", "target_type", "target_id", "created_at"),)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    actor_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    operation = Column(String(100), primary_key=True)
    key = Column(String(100), primary_key=True)
    payload_hash = Column(String(64), nullable=False)
    result_json = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class OtpChallenge(Base):
    __tablename__ = "otp_challenges"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String(30), nullable=False, index=True)
    code_hash = Column(String(128), nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    attempts = Column(Integer, nullable=False, default=0)
    consumed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)


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
    revision = Column(Integer, nullable=False, default=1)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    voided_at = Column(DateTime)
    voided_by = Column(Integer, ForeignKey("users.id"))
    void_reason = Column(String(500))
    replacement_of_id = Column(Integer, ForeignKey("financial_entries.id"), unique=True)
    created_at = Column(DateTime, server_default=func.now())
    project = relationship("Project", back_populates="financial_entries")

    __table_args__ = (
        CheckConstraint("kind IN ('invoice', 'receipt')"),
        CheckConstraint("amount_cents > 0"),
    )

    @property
    def amount(self):
        return self.amount_cents / 100


class BillingProfile(Base):
    __tablename__ = "customer_billing_profiles"
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    label = Column(String(50), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    is_default = Column(Boolean, nullable=False, default=False)
    revision = Column(Integer, nullable=False, default=1)
    current_verified_version_id = Column(Integer, ForeignKey("customer_billing_versions.id"))
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class BillingVersion(Base):
    __tablename__ = "customer_billing_versions"
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("customer_billing_profiles.id"), nullable=False, index=True)
    version_no = Column(Integer, nullable=False)
    status = Column(String(16), nullable=False, default="draft", index=True)
    public_json = Column(Text, nullable=False)
    sensitive_ciphertext = Column(Text, nullable=False)
    bank_last4 = Column(String(4))
    key_id = Column(String(32), nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    submitted_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    verified_by = Column(Integer, ForeignKey("users.id"))
    verification_note = Column(String(500))
    created_at = Column(DateTime, server_default=func.now())
    submitted_at = Column(DateTime)
    verified_at = Column(DateTime)
    __table_args__ = (Index("uq_billing_version_no", "profile_id", "version_no", unique=True),)


class InvoiceSnapshot(Base):
    __tablename__ = "invoice_billing_snapshots"
    id = Column(Integer, primary_key=True)
    financial_entry_id = Column(Integer, ForeignKey("financial_entries.id"), nullable=False, unique=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    profile_id = Column(Integer, ForeignKey("customer_billing_profiles.id"), nullable=False)
    version_id = Column(Integer, ForeignKey("customer_billing_versions.id"), nullable=False)
    public_json = Column(Text, nullable=False)
    sensitive_ciphertext = Column(Text, nullable=False)
    key_id = Column(String(32), nullable=False)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class ReportNumberHistory(Base):
    __tablename__ = "report_number_history"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    report_no = Column(String(100), nullable=False, unique=True, index=True)
    is_recycled = Column(Boolean, nullable=False, default=False)
    is_legacy = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now())
    recycled_at = Column(DateTime, nullable=True)

    project = relationship("Project", back_populates="report_number_history")


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


class AppSetting(Base):
    """Small installation-scoped settings such as branding preferences."""
    __tablename__ = "app_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False, default="{}")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class ExportAccessEpoch(Base):
    __tablename__ = 'export_access_epoch'
    id = Column(Integer, primary_key=True)
    value = Column(Integer, nullable=False, default=1)


class ProjectSequence(Base):
    __tablename__='project_sequences'
    fiscal_year=Column(Integer,primary_key=True)
    last_sequence=Column(Integer,nullable=False,default=0)


class ExportJob(Base):
    __tablename__ = 'export_jobs'
    id = Column(String(32), primary_key=True)
    requested_by = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    export_type = Column(String(32), nullable=False)
    filters_json = Column(Text, nullable=False)
    field_set = Column(Text, nullable=False)
    purpose = Column(String(500))
    permission_revision = Column(Integer, nullable=False)
    access_epoch = Column(Integer, nullable=False)
    idempotency_key = Column(String(100), nullable=False)
    payload_hash = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False, default='queued', index=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    expires_at = Column(DateTime)
    row_count = Column(Integer, nullable=False, default=0)
    cancel_requested = Column(Boolean, nullable=False, default=False)
    file_id = Column(String(32))
    file_size = Column(Integer)
    error_code = Column(String(64))
    request_id = Column(String(64))
    __table_args__ = (Index('uq_export_retry','requested_by','idempotency_key',unique=True),)
