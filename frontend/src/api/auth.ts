import axios from 'axios'
import type {
  LoginRequest, LoginResponse, User,
  Project, ProjectCreate, ProjectUpdate, ProjectListResponse,
  DashboardStats, User as UserType, Signer, SignerCreate, FinanceKind, FinancialEntry, FinancialEntryInput,
  ReportNumberHistory
} from '@/types'

const api = axios.create({
  baseURL: '/api',
})

// 请求拦截器：添加 token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器：处理错误
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

// 认证 API
export const authApi = {
  login: (data: LoginRequest) => api.post<LoginResponse>('/auth/login', data),
  getMe: () => api.get<User>('/auth/me'),
}

// 用户管理 API
export const userApi = {
  list: (include_disabled = false) => api.get<UserType[]>('/users', { params: { include_disabled } }),
  listPractitioners: () => api.get<{ id: number; username: string; real_name: string; role: string }[]>('/users/practitioners'),
  search: (q: string) => api.get<{ id: number; username: string; real_name: string; role: string }[]>('/users/search', { params: { q } }),
  create: (data: { username: string; password: string; real_name: string; role: string }) =>
    api.post<UserType>('/users', data),
  update: (id: number, data: Partial<{ real_name: string; role: string; password: string; is_active: boolean }>) =>
    api.put<UserType>(`/users/${id}`, data),
  delete: (id: number) => api.delete(`/users/${id}`),
  getFiscalYear: () => api.get<{ fiscal_year: number }>('/users/current-fiscal-year'),
  setFiscalYear: (fiscal_year: number) => api.put<{ access_token: string; fiscal_year: number }>('/users/current-fiscal-year', { fiscal_year }),
}

// 项目 API
export const projectApi = {
  list: (params?: {
    page?: number
    page_size?: number
    search?: string
    firm?: string
    report_type?: string
    project_status?: string
    leader_id?: number
    report_year?: number
  }) => api.get<ProjectListResponse>('/projects', { params }),

  signedByMe: (page = 1) => api.get<ProjectListResponse>('/projects/signed-by-me', { params: { page } }),

  get: (id: string | number) => api.get<Project>(`/projects/${id}`),

  reportHistory: (id: string | number) =>
    api.get<ReportNumberHistory[]>(`/projects/${id}/report-number-history`),

  create: (data: ProjectCreate) => api.post<Project>('/projects', data),

  update: (id: string | number, data: ProjectUpdate) => api.put<Project>(`/projects/${id}`, data),

  delete: (id: string | number) => api.delete(`/projects/${id}`),

  generateReportNo: (id: string | number) => api.post<{ report_no: string; message: string }>(`/projects/${id}/generate-report-no`),

  recycleReportNo: (id: string | number) => api.post<{ message: string }>(`/projects/${id}/recycle-report-no`),
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
