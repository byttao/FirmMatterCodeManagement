import axios from 'axios'
import type {
  LoginRequest, LoginResponse, User,
  Project, ProjectCreate, ProjectUpdate, ProjectListResponse,
  DashboardStats, User as UserType, Signer, SignerCreate, FinanceKind, FinancialEntry, FinancialEntryInput,
  ReportNumberHistory
  , BrandingSettings, Customer, Practitioner
} from '@/types'

const api = axios.create({
  baseURL: '/api',
})

export function requestKey() {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('')
}

export const csrfToken = () => document.cookie.split('; ').find(value => value.startsWith('firm_csrf='))?.split('=')[1] || ''

api.interceptors.request.use((config) => {
  config.headers['X-CSRF-Token'] = csrfToken()
  if (['/projects', '/projects/signed-by-me', '/dashboard', '/export/projects'].includes(config.url || '') && (config.method || 'get') === 'get') {
    config.params = { fiscal_year: Number(sessionStorage.getItem('fiscalYear')), ...config.params }
  }
  return config
})

// 响应拦截器：处理错误
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.data?.detail?.message) error.response.data.detail = error.response.data.detail.message
    if (error.response?.status === 401) {
      document.cookie = 'firm_csrf=; Max-Age=0; Path=/; SameSite=Lax'
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      if (window.location.pathname !== '/login') window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

// 认证 API
export const authApi = {
  login: (data: LoginRequest) => api.post<LoginResponse>('/auth/login', data),
  getMe: () => api.get<User>('/auth/me'),
  logout: () => api.post('/auth/logout'),
  logoutAll: () => api.post('/auth/logout-all'),
  changePassword: (current_password: string, new_password: string) => api.post('/auth/change-password', { current_password, new_password }),
}

export const licenseApi = {
  status: () => api.get<{ required: boolean; allowed: boolean; reason: string; mode: string; limits: Record<string, number> | null; expires_at?: string; license_id?: string; license_type?: string; customer_name?: string; max_users?: number | null; active_users?: number; max_projects?: number | null; active_projects?: number; server_url?: string; server_connected?: boolean; server_connection_reason?: string; heartbeat_last_at?: string; heartbeat_last_success_at?: string; heartbeat_last_error?: string; features: string[] | null }>('/license/status'),
  activate: (data: { license_document: Record<string, unknown>; server_url?: string; instance_name?: string }) => api.post('/license/activate', data),
  heartbeat: () => api.post('/license/heartbeat'),
}

export const brandingApi = {
  public: () => api.get<BrandingSettings>('/public/branding'),
  get: () => api.get<BrandingSettings>('/settings/branding'),
  update: (data: BrandingSettings) => api.put<BrandingSettings>('/settings/branding', data),
}

export const customerApi = {
  list: (search?: string, page = 1, include_disabled = false) => api.get<{items: Customer[]; total: number}>('/customers', { params: { search, page, include_disabled } }),
  lookup: (q: string, cursor = 0) => api.get<{items: {id: number; name: string; tax_id_masked: string | null; identity_status: string}[]; next_cursor: number | null}>('/customers/lookup', {params: {q, cursor}}),
  match: (tax_id: string) => api.post('/customers/match', {tax_id}),
  create: (data: { tax_id: string | null; name: string; type: Customer['type'] }) => api.post<Customer>('/customers', data),
  update: (id: number, data: { name?: string; tax_id?: string | null; is_active?: boolean; expected_revision: number; reason?: string }) => api.patch<Customer>(`/customers/${id}`, data),
  propose: (data: {kind: string; customer_id?: number; expected_customer_revision?: number; proposal: {name: string; tax_id: string | null; type: Customer['type']}; reason: string}) => api.post('/customer-change-requests', data),
  requests: (page = 1) => api.get('/customer-change-requests', {params: {page}}),
  review: (id: number, expected_revision: number, decision: string, reason: string) => api.post(`/customer-change-requests/${id}/review`, {expected_revision, decision, reason}),
}

// 用户管理 API
export const userApi = {
  list: (include_disabled = false) => api.get<UserType[]>('/users', { params: { include_disabled } }),
  listPractitioners: () => api.get<Practitioner[]>('/users/practitioners'),
  search: (q: string) => api.get<Practitioner[]>('/users/search', { params: { q } }),
  create: (data: { username: string; phone?: string; password: string; real_name: string; roles: string[]; is_practitioner: boolean; special_grants: string[] }) =>
    api.post<UserType>('/users', data),
  update: (id: number, data: Partial<{ real_name: string; phone: string | null; roles: string[]; is_practitioner: boolean; special_grants: string[]; password: string; is_active: boolean }> & {expected_revision: number}) =>
    api.put<UserType>(`/users/${id}`, data),
  delete: (id: number) => api.delete(`/users/${id}`),
  getFiscalYear: () => api.get<{ fiscal_year: number }>('/users/current-fiscal-year'),
  setFiscalYear: (fiscal_year: number) => api.put<{ access_token: string; fiscal_year: number }>('/users/current-fiscal-year', { fiscal_year }),
}

// 项目 API
export const projectApi = {
  list: (params?: {
    page?: number
    fiscal_year?: number
    page_size?: number
    search?: string
    firm?: string
    report_type?: string
    project_status?: string
    leader_id?: number
    report_year?: number
    sort_by?: string
    sort_order?: 'asc' | 'desc'
    sort?: string
  }) => api.get<ProjectListResponse>('/projects', { params }),

  signedByMe: (page = 1) => api.get<ProjectListResponse>('/projects/signed-by-me', { params: { page } }),

  get: (id: string | number) => api.get<Project>(`/projects/${id}`),

  reportHistory: (id: string | number) =>
    api.get<ReportNumberHistory[]>(`/projects/${id}/report-number-history`),

  create: (data: ProjectCreate) => api.post<Project>('/projects', data),

  update: (id: string | number, data: ProjectUpdate) => api.put<Project>(`/projects/${id}`, data),

  delete: (id: string | number, expected_revision: number) => api.delete(`/projects/${id}`, {params: {expected_revision}}),

  generateReportNo: (id: string | number, expected_revision: number, key: string) => api.post<{ report_no: string; revision: number; message: string }>(`/projects/${id}/generate-report-no`, {expected_revision}, {headers: {'Idempotency-Key': key}}),

  recycleReportNo: (id: string | number, expected_revision: number, reason: string) => api.post<{ message: string }>(`/projects/${id}/void-report-no`, {expected_revision, reason}),
}

export const financeApi = {
  list: (projectId: number, kind: FinanceKind) =>
    api.get<FinancialEntry[]>(`/projects/${projectId}/finance/${kind}`),
  create: (projectId: number, kind: FinanceKind, data: FinancialEntryInput) =>
    api.post<FinancialEntry>(`/projects/${projectId}/finance/${kind}`, data),
  update: (projectId: number, kind: FinanceKind, entryId: number, data: FinancialEntryInput) =>
    api.put<FinancialEntry>(`/projects/${projectId}/finance/${kind}/${entryId}`, data),
  delete: (projectId: number, kind: FinanceKind, entryId: number) =>
    api.delete(`/projects/${projectId}/finance/${kind}/${entryId}`),
}

// 看板 API
export const dashboardApi = {
  getStats: (fiscal_year?: number) => api.get<DashboardStats>('/dashboard', { params: { fiscal_year } }),
}

// Excel 导出
export const exportApi = {
  exportProjects: (fiscal_year?: number) => api.get('/export/projects', { params: { fiscal_year }, responseType: 'blob' }),
}

// 签字人 API
export const signerApi = {
  // 获取签字人列表
  list: (signer_type?: string, include_disabled?: boolean, eligible_only?: boolean) =>
    api.get<Signer[]>('/signers', { params: { signer_type, include_disabled, eligible_only } }),

  create: (data: SignerCreate) =>
    api.post<Signer>('/signers', data),

  update: (id: number, data: Partial<SignerCreate>) =>
    api.put<Signer>(`/signers/${id}`, data),

  // 禁用签字人
  disable: (id: number) =>
    api.post(`/signers/${id}/disable`),

  // 启用签字人
  enable: (id: number) =>
    api.post(`/signers/${id}/enable`),

  // 删除签字人
  delete: (id: number) =>
    api.delete(`/signers/${id}`),

  // 导入签字人
  import: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post('/signers/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  // 导出签字人
  export: () => api.get('/signers/export', { responseType: 'blob' }),

  // 下载导入模板
  downloadTemplate: () => api.get('/signers/template', { responseType: 'blob' }),
}

export default api
