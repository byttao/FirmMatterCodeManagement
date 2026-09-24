import { useEffect, useState, useMemo, useRef } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { projectApi, userApi, signerApi } from '@/api/auth'
import { numberedYearOptionsApi } from '@/api/fiscalYearConfig'
import { useAuth } from '@/store/AuthContext'
import { useDirty } from '@/context/DirtyContext'
import type { Project, ProjectCreate, ProjectUpdate, ReportNumberHistory, Signer } from '@/types'
import { getSignerDisplayName, getUserDisplayName } from '@/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { DatePicker } from '@/components/ui/date-picker'
import { MoneyInput } from '@/components/ui/money-input'
import { FinancialLedger } from '@/components/FinancialLedger'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { ArrowLeft, Save, FileText, Users, DollarSign, Loader2, X, Search } from 'lucide-react'

interface Practitioner {
  id: number
  username: string
  real_name: string
  role: string
}

interface ProjectFormProps {
  readonly?: boolean
}

export default function ProjectForm({ readonly = false }: ProjectFormProps) {
  const { projectId } = useParams()
  const navigate = useNavigate()
  const { user, fiscalYear } = useAuth()
  const { isDirty, setDirty, confirmDirty } = useDirty()
  const isPreview = readonly
  const isEdit = !!projectId && projectId !== 'new' && !isPreview

  const [loading, setLoading] = useState(isEdit || isPreview)
  const [saving, setSaving] = useState(false)
  const [generatingNo, setGeneratingNo] = useState(false)
  const [allPractitioners, setAllPractitioners] = useState<Practitioner[]>([])
  const [signers, setSigners] = useState<Signer[]>([])
  const [reportHistory, setReportHistory] = useState<ReportNumberHistory[]>([])

  // 动态事务所和业务类型列表
  const [firmOptions, setFirmOptions] = useState<string[]>([])
  const [reportTypeOptions, setReportTypeOptions] = useState<string[]>([])

  // 预览模式下重置 dirty 状态，避免刷新时弹出提示
  useEffect(() => {
    if (isPreview) {
      setDirty(false)
    }
  }, [isPreview, setDirty])

  // 报告年度可以早于编号年度，保留历史项目选项并覆盖未来配置年度。
  const reportYearOptions = useMemo(() => {
    const years: number[] = []
    for (let y = 1990; y <= 2100; y++) {
      years.push(y)
    }
    return years
  }, [])

  // 默认报告年度为去年
  const currentYear = fiscalYear || new Date().getFullYear()
  const defaultReportYear = currentYear - 1

  const [formData, setFormData] = useState<Partial<ProjectCreate>>({
    firm: '',
    report_type: '',
    report_year: defaultReportYear,
    customer_name: '',
    contract_no: '',
    order_date: new Date().toISOString().split('T')[0], // 今天
    leader_id: isEdit ? undefined : (user?.id ?? undefined),
    member_ids: [],
    project_status: '进行中',
    project_phase: '签约',
    priority: '中',
    scale: '',
    business_source: '',
    contract_amount: 0,
    signer1_id: undefined,
    signer2_id: undefined,
  })


  // 封装的导航函数，有未保存数据时弹窗确认（预览模式下跳过检查）
  const safeNavigate = (to: string, options?: { replace?: boolean }) => {
    if (isPreview) {
      navigate(to, options)
    } else {
      confirmDirty(() => navigate(to, options))
    }
  }


  const [project, setProject] = useState<Project | null>(null)
  const numberingYear = project?.fiscal_year ?? fiscalYear

  // 团队成员搜索状态
  const [memberSearch, setMemberSearch] = useState('')
  const [memberSearchResults, setMemberSearchResults] = useState<Practitioner[]>([])
  const [showMemberDropdown, setShowMemberDropdown] = useState(false)
  const memberSearchRef = useRef<HTMLDivElement>(null)

  // 执业负责人搜索状态
  const [leaderSearch, setLeaderSearch] = useState('')
  const [leaderSearchResults, setLeaderSearchResults] = useState<Practitioner[]>([])
  const [showLeaderDropdown, setShowLeaderDropdown] = useState(false)
  const leaderSearchRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    loadAllPractitioners()
    // 编辑或预览模式都需要加载项目数据
    if (isEdit || isPreview) {
      loadProject()
    } else if (user?.id) {
      // 新建项目时，默认选择当前用户为负责人
      setFormData(prev => ({ ...prev, leader_id: user.id }))
    }
  }, [projectId, user?.id])

  useEffect(() => {
    loadFirms()
  }, [numberingYear])

  useEffect(() => {
    if (formData.firm) {
      loadSignersByFirm(formData.firm)
      loadReportTypesByFirm(formData.firm)
    } else {
      setSigners([])
      setReportTypeOptions([])
    }
  }, [formData.firm, numberingYear])

  // 点击外部关闭搜索下拉
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (memberSearchRef.current && !memberSearchRef.current.contains(e.target as Node)) {
        setShowMemberDropdown(false)
      }
      if (leaderSearchRef.current && !leaderSearchRef.current.contains(e.target as Node)) {
        setShowLeaderDropdown(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // 团队成员搜索
  useEffect(() => {
    if (memberSearch.length > 0) {
      searchMembers(memberSearch)
    } else {
      setMemberSearchResults([])
    }
  }, [memberSearch])

  // 执业负责人搜索
  useEffect(() => {
    if (leaderSearch.length > 0) {
      searchLeader(leaderSearch)
    } else {
      setLeaderSearchResults([])
    }
  }, [leaderSearch])

  const loadAllPractitioners = async () => {
    try {
      const res = await userApi.listPractitioners()
      setAllPractitioners(res.data)
    } catch (err) {
      console.error('加载执业人员失败', err)
    }
  }

  const searchMembers = async (query: string) => {
    try {
      const res = await userApi.search(query)
      // 过滤掉已选的负责人（但不过滤当前登录用户，允许将自己加为成员）
      const filtered = res.data.filter(p =>
        p.id !== formData.leader_id &&
        !formData.member_ids?.includes(p.id)
      )
      setMemberSearchResults(filtered)
    } catch (err) {
      console.error('搜索成员失败', err)
    }
  }

  const searchLeader = async (query: string) => {
    try {
      const res = await userApi.search(query)
      // 过滤掉已选的团队成员（但保留当前负责人）
      const filtered = res.data.filter(p =>
        !formData.member_ids?.includes(p.id)
      )
      setLeaderSearchResults(filtered)
    } catch (err) {
      console.error('搜索负责人失败', err)
    }
  }

  const handleLeaderSearchSelect = (p: Practitioner) => {
    setDirty(true)
    // 从团队成员中移除新的负责人（如果之前是成员）
    setFormData(prev => ({
      ...prev,
      leader_id: p.id,
      member_ids: (prev.member_ids || []).filter(id => id !== p.id)
    }))
    setLeaderSearch('')
    setShowLeaderDropdown(false)
  }

  // 当前用户如果是执业人员，保存其信息用于"选我"按钮
  const currentUserAsPractitioner = useMemo(() => {
    if (user?.role === 'practitioner') {
      return allPractitioners.find(p => p.id === user.id)
    }
    return null
  }, [user, allPractitioners])

  const loadFirms = async () => {
    try {
      const res = await numberedYearOptionsApi.get(numberingYear)
      setFirmOptions(Array.isArray(res.data?.firms) ? res.data.firms : [])
    } catch (err) {
      console.error('加载事务所列表失败', err)
      setFirmOptions([])
    }
  }

  const loadReportTypesByFirm = async (firm: string) => {
    if (!firm) {
      setReportTypeOptions([])
      return
    }
    try {
      const res = await numberedYearOptionsApi.get(numberingYear, firm)
      setReportTypeOptions(Array.isArray(res.data?.report_types) ? res.data.report_types : [])
    } catch (err) {
      console.error('加载业务类型失败', err)
      setReportTypeOptions([])
    }
  }

  const loadSignersByFirm = async (firm: string) => {
    try {
      const res = await signerApi.list(firm, false, true)
      if (Array.isArray(res.data)) {
        setSigners(res.data.filter(s => s && typeof s.id === 'number'))
      } else {
        setSigners([])
      }
    } catch (err) {
      console.error('加载签字人失败', err)
      setSigners([])
    }
  }

  const loadProject = async () => {
    try {
      const [res, history] = await Promise.all([
        projectApi.get(projectId!), projectApi.reportHistory(projectId!),
      ])
      const p = res.data
      setProject(p)
      setReportHistory(history.data)
      setFormData({
        firm: p.firm,
        report_type: p.report_type,
        report_year: p.report_year,
        customer_name: p.customer_name,
        contract_no: p.contract_no || '',
        order_date: p.order_date ? p.order_date.split('T')[0] : '',
        leader_id: p.leader_id,
        member_ids: p.members.map(m => m.user_id),
        project_status: p.project_status,
        project_phase: p.project_phase,
        priority: p.priority,
        scale: p.scale || '',
        business_source: p.business_source || '',
        contract_amount: p.contract_amount,
        signer1_id: p.signer1_id,
        signer2_id: p.signer2_id,
      })
      loadSignersByFirm(p.firm)
      loadReportTypesByFirm(p.firm)
      setLoading(false)
    } catch (err: any) {
      console.error('加载项目失败', err)
      if (err.response?.status === 403) {
        alert('无权访问此项目')
        navigate('/projects')
        return
      }
      alert(err.response?.data?.detail || '加载项目失败')
      setLoading(false)
    }
  }

  const handleInputChange = (field: keyof ProjectCreate, value: any) => {
    setDirty(true)
    setFormData(prev => ({ ...prev, [field]: value }))
    // 切换事务所时重置报告类型，并重新加载业务类型
    if (field === 'firm') {
      setFormData(prev => ({ ...prev, report_type: '', signer1_id: null, signer2_id: null }))
      loadSignersByFirm(value)
      loadReportTypesByFirm(value)
    }
  }

  const handleSigner1Change = (signerId: string) => {
    const id = signerId === '' || signerId === 'none' ? null : parseInt(signerId)
    setDirty(true)
    setFormData(prev => ({ ...prev, signer1_id: id }))
  }

  const handleSigner2Change = (signerId: string) => {
    const id = signerId === '' || signerId === 'none' ? null : parseInt(signerId)
    setDirty(true)
    setFormData(prev => ({ ...prev, signer2_id: id }))
  }

  const handleMemberSearchSelect = (p: Practitioner) => {
    setDirty(true)
    setFormData(prev => ({
      ...prev,
      member_ids: [...(prev.member_ids || []), p.id]
    }))
    setMemberSearch('')
    setShowMemberDropdown(false)
  }

  const handleMemberRemove = (userId: number) => {
    setDirty(true)
    setFormData(prev => ({
      ...prev,
      member_ids: (prev.member_ids || []).filter(id => id !== userId)
    }))
  }

  const canGenerateNo = project?.report_no_status === 'pending' || project?.report_no_status === 'recycled' || !project
  const canEditReportYear = !project?.report_no

  // 已选中的团队成员详情
  const selectedMembers = useMemo(() => {
    return allPractitioners.filter(p => formData.member_ids?.includes(p.id))
  }, [formData.member_ids, allPractitioners])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    // 验证执业负责人必选
    if (!formData.leader_id) {
      alert('请选择执业负责人')
      return
    }

    // 验证业务年度不超过编号年度
    if (formData.report_year && formData.report_year > numberingYear) {
      alert(`业务年度(${formData.report_year}年)不能超过编号年度(${numberingYear}年)`)
      return
    }

    // 验证签字人一和签字人二不能为同一人
    if (formData.signer1_id && formData.signer2_id && formData.signer1_id === formData.signer2_id) {
      alert('签字人一和签字人二不能为同一人')
      return
    }

    setSaving(true)

    try {
      const data = {
        ...formData,
        order_date: formData.order_date ? new Date(formData.order_date).toISOString() : undefined,
      }

      if (isEdit && project) {
        const fullData: ProjectUpdate = { ...data as ProjectUpdate }
        await projectApi.update(project.id, fullData)
        // 保存成功后重新加载项目，刷新服务端计算的字段（未开票金额、未收款金额等）
        await loadProject()
      } else {
        const res = await projectApi.create(data as ProjectCreate)
        setProject(res.data)
        // 保存成功后直接导航，不需要确认
        setDirty(false)
        navigate(`/projects/${res.data.project_id}/edit`, { replace: true })
        return
      }
      alert('保存成功')
      setDirty(false)
    } catch (err: any) {
      alert(err.response?.data?.detail || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleGenerateReportNo = async () => {
    if (!project) return
    if (isDirty) {
      alert('请先保存项目修改，再生成报告编号')
      return
    }
    setGeneratingNo(true)
    try {
      const res = await projectApi.generateReportNo(project.id)
      setProject(prev => prev ? { ...prev, report_no: res.data.report_no, report_no_status: 'assigned' } : null)
      projectApi.reportHistory(project.id).then(history => setReportHistory(history.data)).catch(err => {
        console.error('刷新编号记录失败', err)
      })
      alert('报告编号生成成功：' + res.data.report_no)
    } catch (err: any) {
      alert(err.response?.data?.detail || '生成编号失败')
    } finally {
      setGeneratingNo(false)
    }
  }

  const isFinancialFieldEditable = user?.role === 'admin' || user?.role === 'admin_staff'
  const isBasicFieldEditable = !project || project.leader_id === user?.id || user?.role === 'admin'
  // 预览模式下所有字段不可编辑
  const isFieldDisabled = isPreview || !isBasicFieldEditable

  if (loading) {
    return <div className="flex items-center justify-center h-64">加载中...</div>
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Button variant="ghost" onClick={() => safeNavigate('/projects')}>
          <ArrowLeft className="w-4 h-4 mr-2" />
          返回列表
        </Button>
        <h1 className="text-2xl font-bold">
          {isPreview ? '项目预览' : (isEdit ? '编辑项目' : '新建项目')}
        </h1>
        {project && (
          <Badge variant="outline" className="ml-4">
            {project.project_id}
          </Badge>
        )}
        {isPreview && (
          <Button variant="default" onClick={() => navigate(`/projects/${projectId}/edit`)} className="ml-auto">
            <FileText className="w-4 h-4 mr-2" />
            编辑
          </Button>
        )}
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* 基本信息 */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileText className="w-5 h-5" />
              基本信息
            </CardTitle>
            <CardDescription>
              编号年度为 {numberingYear} 年；业务年度记录审计对象所属年度，报告编号按编号年度的规则和序列生成。
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="space-y-2">
                <Label>事务所</Label>
                <Select
                  value={formData.firm}
                  onValueChange={(v) => handleInputChange('firm', v)}
                  disabled={isFieldDisabled || !!project?.report_no}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="选择事务所" />
                  </SelectTrigger>
                  <SelectContent>
                    {firmOptions.length > 0 ? (
                      firmOptions.map(f => (
                        <SelectItem key={f} value={f}>{f}</SelectItem>
                      ))
                    ) : (
                      <SelectItem value="__none__" disabled>暂无可用事务所（请先配置编号年度）</SelectItem>
                    )}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>报告类型</Label>
                <Select
                  value={formData.report_type}
                  onValueChange={(v) => handleInputChange('report_type', v)}
                  disabled={isFieldDisabled || !!project?.report_no || !formData.firm}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="选择类型" />
                  </SelectTrigger>
                  <SelectContent>
                    {reportTypeOptions.length > 0 ? (
                      reportTypeOptions.map(type => (
                        <SelectItem key={type} value={type}>{type}</SelectItem>
                      ))
                    ) : (
                      <SelectItem value="__none__" disabled>请先选择事务所</SelectItem>
                    )}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>报告年度 <span className="text-xs text-muted-foreground">(业务年度)</span></Label>
                <Select
                  value={formData.report_year?.toString() || defaultReportYear.toString()}
                  onValueChange={(v) => handleInputChange('report_year', parseInt(v))}
                  disabled={isPreview || !canEditReportYear}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="选择年份" />
                  </SelectTrigger>
                  <SelectContent>
                    {reportYearOptions.map(year => (
                      <SelectItem key={year} value={year.toString()}>{year}年</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label>执业负责人 *</Label>
                  {currentUserAsPractitioner && (
                    <Button
                      type="button"
                      variant="link"
                      size="sm"
                      className="h-auto p-0 text-xs text-blue-600"
                      onClick={() => handleLeaderSearchSelect(currentUserAsPractitioner)}
                      disabled={isFieldDisabled}
                    >
                      选我（{getUserDisplayName(currentUserAsPractitioner)}）
                    </Button>
                  )}
                </div>
                <div className="relative" ref={leaderSearchRef}>
                  {formData.leader_id ? (
                    // 已选负责人显示
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="px-2 py-1 flex items-center gap-1 text-sm">
                        {getUserDisplayName(allPractitioners.find(p => p.id === formData.leader_id) || { real_name: '未知', username: '' })}
                        {formData.leader_id === user?.id && <span className="text-xs text-muted-foreground">(自己)</span>}
                      </Badge>
                      {!isFieldDisabled && (
                        <button
                          type="button"
                          onClick={() => setShowLeaderDropdown(true)}
                          className="text-sm text-blue-600 hover:underline"
                        >
                          更换
                        </button>
                      )}
                      {showLeaderDropdown && (
                        <div className="flex-1">
                          <div className="relative">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                            <Input
                              placeholder="搜索执业负责人..."
                              value={leaderSearch}
                              onChange={(e) => {
                                setLeaderSearch(e.target.value)
                                if (e.target.value.length > 0) {
                                  setShowLeaderDropdown(true)
                                }
                              }}
                              onFocus={() => {
                                if (leaderSearch.length > 0 && leaderSearchResults.length > 0) {
                                  setShowLeaderDropdown(true)
                                }
                              }}
                              className="pl-9"
                              autoFocus
                            />
                          </div>
                        </div>
                      )}
                    </div>
                  ) : (
                    // 未选负责人显示搜索框
                    <div className="relative">
                      <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                      <Input
                        placeholder="搜索执业负责人..."
                        value={leaderSearch}
                        onChange={(e) => {
                          setLeaderSearch(e.target.value)
                          if (e.target.value.length > 0) {
                            setShowLeaderDropdown(true)
                          }
                        }}
                        onFocus={() => {
                          if (leaderSearch.length > 0 && leaderSearchResults.length > 0) {
                            setShowLeaderDropdown(true)
                          }
                        }}
                        disabled={isFieldDisabled}
                        className="pl-9"
                      />
                    </div>
                  )}
                  {/* 搜索结果下拉 */}
                  {showLeaderDropdown && leaderSearchResults.length > 0 && (
                    <div className="absolute z-50 w-full mt-1 bg-background border rounded-md shadow-lg max-h-60 overflow-auto">
                      {leaderSearchResults.map(p => (
                        <div
                          key={p.id}
                          className="px-3 py-2 hover:bg-muted cursor-pointer text-sm"
                          onClick={() => handleLeaderSearchSelect(p)}
                        >
                          {getUserDisplayName(p)}
                          {p.id === user?.id && <span className="text-xs text-muted-foreground ml-1">(自己)</span>}
                        </div>
                      ))}
                    </div>
                  )}
                  {showLeaderDropdown && leaderSearch.length > 0 && leaderSearchResults.length === 0 && (
                    <div className="absolute z-50 w-full mt-1 bg-background border rounded-md shadow-lg px-3 py-2 text-sm text-muted-foreground">
                      未找到匹配的执业人员
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>客户名称 *</Label>
                <Input
                  value={formData.customer_name}
                  onChange={(e) => handleInputChange('customer_name', e.target.value)}
                  disabled={isFieldDisabled}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label>合同号</Label>
                <Input
                  value={formData.contract_no}
                  onChange={(e) => handleInputChange('contract_no', e.target.value)}
                  disabled={isFieldDisabled}
                />
              </div>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="space-y-2">
                <Label>下单时间</Label>
                <DatePicker
                  value={formData.order_date || ''}
                  onChange={(date) => handleInputChange('order_date', date)}
                  disabled={isFieldDisabled}
                />
              </div>
              <div className="space-y-2">
                <Label>项目状态</Label>
                <Select
                  value={formData.project_status}
                  onValueChange={(v) => handleInputChange('project_status', v)}
                  disabled={isFieldDisabled}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="进行中">进行中</SelectItem>
                    <SelectItem value="已完成">已完成</SelectItem>
                    <SelectItem value="已暂停">已暂停</SelectItem>
                    <SelectItem value="已取消">已取消</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>项目阶段</Label>
                <Select
                  value={formData.project_phase}
                  onValueChange={(v) => handleInputChange('project_phase', v)}
                  disabled={isFieldDisabled}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="签约">签约</SelectItem>
                    <SelectItem value="进场">进场</SelectItem>
                    <SelectItem value="实施中">实施中</SelectItem>
                    <SelectItem value="报告出具">报告出具</SelectItem>
                    <SelectItem value="归档">归档</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>优先级</Label>
                <Select
                  value={formData.priority}
                  onValueChange={(v) => handleInputChange('priority', v)}
                  disabled={isFieldDisabled}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="高">高</SelectItem>
                    <SelectItem value="中">中</SelectItem>
                    <SelectItem value="低">低</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              <div className="space-y-2">
                <Label>项目规模</Label>
                <Select
                  value={formData.scale || ''}
                  onValueChange={(v) => handleInputChange('scale', v)}
                  disabled={isFieldDisabled}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="选择规模" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="会计准则">会计准则</SelectItem>
                    <SelectItem value="会计制度">会计制度</SelectItem>
                    <SelectItem value="小企业会计准则">小企业会计准则</SelectItem>
                    <SelectItem value="民非">民非</SelectItem>
                    <SelectItem value="高校">高校</SelectItem>
                    <SelectItem value="社团组织">社团组织</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>业务来源</Label>
                <Select
                  value={formData.business_source || ''}
                  onValueChange={(v) => handleInputChange('business_source', v)}
                  disabled={isFieldDisabled}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="选择来源" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="老客户续签">老客户续签</SelectItem>
                    <SelectItem value="老客户转介绍">老客户转介绍</SelectItem>
                    <SelectItem value="新开发">新开发</SelectItem>
                    <SelectItem value="政府指定">政府指定</SelectItem>
                    <SelectItem value="其他">其他</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>合同金额</Label>
                <MoneyInput
                  value={formData.contract_amount ?? 0}
                  onChange={(val) => handleInputChange('contract_amount', val)}
                  disabled={isFieldDisabled}
                />
              </div>
            </div>

            {/* 签字人选择 */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>{formData.firm || '事务所'}签字人一</Label>
                <Select
                  value={formData.signer1_id?.toString() || ''}
                  onValueChange={handleSigner1Change}
                  disabled={isFieldDisabled || !formData.firm}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="选择签字人" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">不选择</SelectItem>
                    {project?.signer1 && !signers.some(s => s.id === project.signer1_id) && (
                      <SelectItem value={String(project.signer1_id)} disabled>
                        {getSignerDisplayName(project.signer1)}（历史记录）
                      </SelectItem>
                    )}
                    {signers.filter(s => s && typeof s.id === 'number').map(s => (
                      <SelectItem
                        key={s.id}
                        value={s.id.toString()}
                        disabled={isFieldDisabled || s.id === formData.signer2_id}
                      >
                        {getSignerDisplayName(s)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>{formData.firm || '事务所'}签字人二</Label>
                <Select
                  value={formData.signer2_id?.toString() || ''}
                  onValueChange={handleSigner2Change}
                  disabled={isFieldDisabled || !formData.firm}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="选择签字人" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">不选择</SelectItem>
                    {project?.signer2 && !signers.some(s => s.id === project.signer2_id) && (
                      <SelectItem value={String(project.signer2_id)} disabled>
                        {getSignerDisplayName(project.signer2)}（历史记录）
                      </SelectItem>
                    )}
                    {signers.filter(s => s && typeof s.id === 'number').map(s => (
                      <SelectItem
                        key={s.id}
                        value={s.id.toString()}
                        disabled={isFieldDisabled || s.id === formData.signer1_id}
                      >
                        {getSignerDisplayName(s)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* 报告编号 */}
            {project && (
              <div className="p-4 bg-muted rounded-lg">
                <div className="flex items-center justify-between">
                  <div>
                    <Label className="text-base">报告编号</Label>
                    <div className="flex items-center gap-2 mt-1">
                      <p className={`text-lg font-mono ${
                        project.report_no_status === 'assigned'
                          ? 'text-green-600'
                          : project.report_no_status === 'recycled'
                          ? 'text-red-500 line-through'
                          : 'text-muted-foreground'
                      }`}>
                        {project.report_no || '待生成'}
                      </p>
                      {project.report_no_status === 'recycled' && (
                        <span className="text-xs bg-red-100 text-red-600 px-2 py-0.5 rounded-full">已回收</span>
                      )}
                    </div>
                  </div>
                  {!isFieldDisabled && canGenerateNo && formData.firm && formData.report_type && formData.customer_name && (
                    <Button
                      type="button"
                      onClick={handleGenerateReportNo}
                      disabled={generatingNo}
                      variant={project.report_no_status === 'recycled' ? 'outline' : 'default'}
                    >
                      {generatingNo ? (
                        <><Loader2 className="w-4 h-4 mr-2 animate-spin" />生成中...</>
                      ) : project.report_no_status === 'recycled' ? (
                        <><FileText className="w-4 h-4 mr-2" />重新申请编号</>
                      ) : (
                        <><FileText className="w-4 h-4 mr-2" />生成编号</>
                      )}
                    </Button>
                  )}
                </div>
                {reportHistory.length > 0 && (
                  <div className="mt-4 border-t pt-3">
                    <Label className="text-sm">编号记录</Label>
                    <ul className="mt-2 space-y-1 text-sm">
                      {reportHistory.map(record => (
                        <li key={record.id} className="flex flex-wrap items-center gap-x-3 gap-y-1">
                          <span className="font-mono">{record.report_no}</span>
                          <span className="text-muted-foreground">
                            {record.is_recycled ? '已回收' : '当前使用'}
                            {record.is_legacy ? ' · 升级补录' : ''}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {/* 团队成员 */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Users className="w-5 h-5" />
              团队成员
            </CardTitle>
            <CardDescription>
              搜索并添加参与此项目的其他执业人员（不包含执业负责人）
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* 左侧：搜索区域 */}
              <div className="space-y-2">
                <Label>添加成员</Label>
                <div className="relative" ref={memberSearchRef}>
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                    <Input
                      placeholder="输入姓名或拼音搜索..."
                      value={memberSearch}
                      onChange={(e) => {
                        const q = e.target.value
                        setMemberSearch(q)
                        if (q.length > 0) {
                          setShowMemberDropdown(true)
                        }
                      }}
                      onFocus={() => {
                        // focus 时如果已有搜索结果，立即显示下拉
                        if (memberSearch.length > 0 && memberSearchResults.length > 0) {
                          setShowMemberDropdown(true)
                        }
                      }}
                      disabled={isFieldDisabled}
                      className="pl-9"
                    />
                  </div>
                  {/* 搜索结果下拉 */}
                  {showMemberDropdown && memberSearchResults.length > 0 && (
                    <div className="absolute z-50 w-full mt-1 bg-background border rounded-md shadow-lg max-h-60 overflow-auto">
                      {memberSearchResults.map(p => (
                        <div
                          key={p.id}
                          className="px-3 py-2 hover:bg-muted cursor-pointer text-sm"
                          onClick={() => handleMemberSearchSelect(p)}
                        >
                          {getUserDisplayName(p)}
                        </div>
                      ))}
                    </div>
                  )}
                  {showMemberDropdown && memberSearch.length > 0 && memberSearchResults.length === 0 && (
                    <div className="absolute z-50 w-full mt-1 bg-background border rounded-md shadow-lg px-3 py-2 text-sm text-muted-foreground">
                      未找到匹配的成员
                    </div>
                  )}
                </div>
              </div>

              {/* 右侧：已选成员 */}
              <div className="space-y-2">
                <Label>已选成员 ({selectedMembers.length})</Label>
                <div className="min-h-[80px] p-3 border rounded-md bg-muted/50">
                  {selectedMembers.length === 0 ? (
                    <p className="text-sm text-muted-foreground text-center py-4">暂无已选成员</p>
                  ) : (
                    <div className="flex flex-wrap gap-2">
                      {selectedMembers.map(p => (
                        <Badge
                          key={p.id}
                          variant="secondary"
                          className="pl-2 pr-1 py-1 flex items-center gap-1"
                        >
                          {getUserDisplayName(p)}
                          {p.id === user?.id && <span className="text-xs">(自己)</span>}
                          {!isFieldDisabled && (
                            <button
                              type="button"
                              onClick={() => handleMemberRemove(p.id)}
                              className="ml-1 hover:bg-muted-foreground/20 rounded p-0.5"
                            >
                              <X className="w-3 h-3" />
                            </button>
                          )}
                        </Badge>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* 财务信息 */}
        {(isEdit || isPreview) && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <DollarSign className="w-5 h-5" />
                财务信息
              </CardTitle>
            </CardHeader>
            <CardContent>{project && <FinancialLedger project={project} canEdit={!isPreview && isFinancialFieldEditable} onProjectChange={setProject} />}</CardContent>
          </Card>
        )}

        {/* 提交按钮 - 预览模式隐藏 */}
        {!isPreview && isBasicFieldEditable && (
          <div className="flex justify-end gap-4">
            <Button type="button" variant="outline" onClick={() => { setDirty(false); navigate('/projects') }}>
              取消
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? (
                <><Loader2 className="w-4 h-4 mr-2 animate-spin" />保存中...</>
              ) : (
                <><Save className="w-4 h-4 mr-2" />保存项目</>
              )}
            </Button>
          </div>
        )}
      </form>
    </div>
  )
}
