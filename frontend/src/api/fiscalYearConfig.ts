import api from '@/api/auth'

export interface SetupReportType {
  report_type: string
  template: string
  rule_name?: string
}

export interface SetupFirm {
  name: string
  report_types: SetupReportType[]
}

export interface SetupRequest {
  admin_username: string
  admin_password: string
  admin_real_name: string
  fiscal_year: number
  firms: SetupFirm[]
}

// 公开接口（无需认证）
export const publicNumberedYearApi = {
  // 获取已配置的年度列表（无需认证）
  getYears: () => {
    return api.get<{ years: number[] }>('/public/numbered-years')
  },

  getSetupStatus: () => api.get<{ initialized: boolean }>('/setup/status'),
  setup: (data: SetupRequest) => api.post<{ message: string }>('/setup', data),
}

interface NumberedYearOptions {
  years: number[]
  fiscal_year: number
  firms: string[]
  report_types: string[]
}

export const numberedYearOptionsApi = {
  get: (year?: number, firm?: string) =>
    api.get<NumberedYearOptions>('/numbered-years/options', { params: { year, firm } }),
}
