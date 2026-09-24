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
export const publicFiscalYearApi = {
  // 获取已配置的年度列表（无需认证）
  getYears: () => {
    return api.get<{ years: number[] }>('/public/fiscal-years')
  },

  getSetupStatus: () => api.get<{ initialized: boolean }>('/setup/status'),
  setup: (data: SetupRequest) => api.post<{ message: string }>('/setup', data),
}

export const fiscalYearConfigApi = {
  // 获取已配置的年度列表（从三级结构读取）
  getYears: () => {
    return api.get<{ years: number[] }>('/fiscal-years')
  },

  // 获取指定年度已配置的事务所列表
  getFirms: (year: number) => {
    return api.get<{ firms: string[] }>(
      '/fiscal-years/firms',
      { params: { year } }
    )
  },

  // 获取指定年度+事务所已配置的业务类型列表
  getReportTypes: (year: number, firm: string) => {
    return api.get<{ report_types: string[] }>(
      '/fiscal-years/report-types',
      { params: { year, firm } }
    )
  },
}
