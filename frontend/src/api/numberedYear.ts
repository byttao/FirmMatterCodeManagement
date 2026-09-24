import api from '@/api/auth'

const BASE_URL = '/numbered-years'

// 类型定义
export interface ReportRule {
  id: number
  rule_name: string
  template: string
  sequence_digits: number
  current_sequence: number
  is_active: boolean
}

export interface ReportType {
  id: number
  report_type: string
  rule_id: number
  rule_name: string
  created_at: string | null
}

export interface Firm {
  id: number
  firm: string
  rules: ReportRule[]
  report_types: ReportType[]
}

export interface NumberedYear {
  id: number
  year: number
  is_active: boolean
  firms: Firm[]
}

// API
export const numberedYearApi = {
  // 获取树形结构数据
  list: () => api.get<NumberedYear[]>(BASE_URL),

  // 年度管理
  createYear: (year: number) => api.post(BASE_URL, { year }),

  deleteYear: (yearId: number) => api.delete(`${BASE_URL}/${yearId}`),

  // 事务所管理
  createFirm: (fiscalYearId: number, firm: string) =>
    api.post(`${BASE_URL}/firms`, { fiscal_year_id: fiscalYearId, firm }),

  deleteFirm: (firmId: number) => api.delete(`${BASE_URL}/firms/${firmId}`),

  // 编号规则管理
  createRule: (data: {
    fiscal_year_firm_id: number
    rule_name: string
    template: string
    sequence_digits: number
  }) => api.post(`${BASE_URL}/rules`, data),

  updateRule: (ruleId: number, data: {
    rule_name?: string
    template?: string
    sequence_digits?: number
    is_active?: boolean
  }) => api.put(`${BASE_URL}/rules/${ruleId}`, data),

  deleteRule: (ruleId: number) => api.delete(`${BASE_URL}/rules/${ruleId}`),

  // 业务类型管理
  createReportType: (data: {
    fiscal_year_firm_id: number
    report_type: string
    rule_id: number
  }) => api.post(`${BASE_URL}/report-types`, data),

  updateReportType: (rtId: number, data: {
    report_type?: string
    rule_id?: number
  }) => api.put(`${BASE_URL}/report-types/${rtId}`, data),

  deleteReportType: (rtId: number) => api.delete(`${BASE_URL}/report-types/${rtId}`),
}
