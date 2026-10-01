// 用户类型
export type UserRole = 'office_admin' | 'number_manager' | 'finance' | 'practitioner' | 'clerk'

export interface User {
  id: number
  username: string
  phone: string | null
  real_name: string
  roles: UserRole[]
  permissions: string[]
  special_grants: string[]
  is_practitioner: boolean
  permission_revision: number
  fiscal_year: number
  is_active: boolean
  created_at: string
}

export interface Practitioner {
  id: number
  username: string
  phone?: string | null
  real_name: string
  is_practitioner: boolean
  is_active?: boolean
}

// 签字人类型
export interface Signer {
  id: number
  name: string
  signer_type: string  // 关联的事务所名称
  user_id: number | null
  user: Practitioner | null
  is_active: boolean
  disabled_at: string | null
  created_at: string
}

export interface SignerCreate {
  user_id: number
  signer_type: string
}

export const getSignerDisplayName = (signer: Signer) =>
  signer.user ? `${signer.name} (${signer.user.username})` : `${signer.name} (待关联)`

export const isSignerEligible = (signer: Signer) =>
  !!signer.user_id && !!signer.user?.is_active && signer.user.is_practitioner && signer.is_active

export interface LoginRequest {
  username: string
  password: string
  fiscal_year?: number
}

export interface BrandingSettings {
  short_name: string
  logo_data: string
  replace_banner: boolean
  append_title: boolean
}

export interface Customer {
  id: number
  tax_id: string | null
  name: string
  type: 'enterprise' | 'individual' | 'overseas'
  identity_status: string
  revision: number
  merged_into_id: number | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
  fiscal_year: number
}

export interface AuthState {
  user: User | null
  token: string | null
  isAuthenticated: boolean
}

// 项目类型
export type ReportStatus = 'pending' | 'assigned' | 'recycled'

export interface ProjectMember {
  id: number
  user_id: number
  user?: Practitioner
}

export interface Project {
  id: number
  project_id: string
  fiscal_year: number
  revision: number
  firm: string
  report_type: string
  report_year: number
  report_no: string | null
  report_no_status: ReportStatus
  customer_name: string
  customer_id: number
  customer_tax_id: string | null
  contract_no: string | null
  order_date: string | null
  leader_id: number
  leader?: Practitioner
  members: ProjectMember[]
  project_status: string
  project_phase: string
  priority: string
  scale: string | null
  business_source: string | null
  contract_amount: number | null
  invoiced_amount: number | null
  invoice_date: string | null
  received_amount: number | null
  receive_date: string | null
  uninvoiced_amount: number | null
  unreceived_amount: number | null
  signer1_id: number | null
  signer2_id: number | null
  signer1: Signer | null
  signer2: Signer | null
  is_deleted: boolean
  created_at: string
  updated_at: string
}

export interface ProjectCreate {
  fiscal_year: number
  firm: string
  report_type: string
  report_year: number
  customer_name: string
  customer_tax_id?: string | null
  customer_id?: number | null
  contract_no?: string
  order_date?: string
  leader_id: number
  member_ids?: number[]
  project_status?: string
  project_phase?: string
  priority?: string
  scale?: string
  business_source?: string
  contract_amount?: number | null
  signer1_id?: number | null
  signer2_id?: number | null
}

export interface ProjectUpdate {
  expected_revision: number
  reason?: string
  firm?: string
  report_type?: string
  report_year?: number
  customer_name?: string
  customer_tax_id?: string | null
  customer_id?: number | null
  contract_no?: string
  order_date?: string
  leader_id?: number
  member_ids?: number[]
  project_status?: string
  project_phase?: string
  priority?: string
  scale?: string
  business_source?: string
  contract_amount?: number | null
  signer1_id?: number | null
  signer2_id?: number | null
}

export type FinanceKind = 'invoices' | 'receipts'

export interface FinancialEntry {
  id: number
  amount: number
  occurred_on: string | null
  reference: string | null
  note: string | null
  is_legacy: boolean
  created_at: string
}

export interface FinancialEntryInput {
  amount: number
  occurred_on: string | null
  reference?: string | null
  note?: string | null
}

export interface ProjectListResponse {
  items: Project[]
  total: number
  page: number
  page_size: number
}

export interface ReportNumberHistory {
  id: number
  report_no: string
  is_recycled: boolean
  is_legacy: boolean
  created_at: string
  recycled_at: string | null
}

// 看板统计
export interface DashboardStats {
  total_projects: number
  ongoing_projects: number
  completed_projects: number
  paused_projects: number
  cancelled_projects: number
  this_month_new: number
  total_contract_amount: number | null
  total_invoiced_amount: number | null
  total_received_amount: number | null
  total_uninvoiced: number | null
  total_unreceived: number | null
}

// 项目状态字典。事务所和业务类型由首次安装及年度配置维护。
export const PROJECT_STATUS_OPTIONS = ['进行中', '已完成', '已暂停', '已取消']
export const PROJECT_PHASE_OPTIONS = ['签约', '进场', '实施中', '报告出具', '归档']
export const PRIORITY_OPTIONS = ['高', '中', '低']
export const SCALE_OPTIONS = ['会计准则', '会计制度', '小企业会计准则', '民非', '高校', '社团组织']
export const BUSINESS_SOURCE_OPTIONS = ['老客户续签', '老客户转介绍', '新开发', '政府指定', '其他']
export const REPORT_STATUS_OPTIONS = ['pending', 'assigned', 'recycled']
export const REPORT_STATUS_LABELS: Record<string, string> = {
  pending: '待编号',
  assigned: '已编号',
  recycled: '已回收',
}
export const ROLE_LABELS: Record<string, string> = {
  office_admin: '事务所管理员',
  number_manager: '编号管理员',
  finance: '财务后勤',
  practitioner: '执业人员',
  clerk: '普通行政',
}

export const can = (user: User | null | undefined, permission: string) => !!user?.permissions.includes(permission)

// 用户显示名称（姓名+用户名，用于区分重名）
export const getUserDisplayName = (user: { real_name: string; username: string }) => {
  return `${user.real_name} (${user.username})`
}
