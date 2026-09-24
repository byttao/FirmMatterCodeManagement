import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Building2, CheckCircle2, Plus, ShieldCheck, Trash2 } from 'lucide-react'
import { publicFiscalYearApi, type SetupFirm, type SetupRequest } from '@/api/fiscalYearConfig'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

const currentYear = new Date().getFullYear()

const newReportType = (template = '') => ({ report_type: '', template, rule_name: '' })

const newFirm = (first = false): SetupFirm => ({
  name: '',
  report_types: [newReportType(first ? '{yyyy}-{nnn}' : '')],
})

export default function SetupWizard() {
  const navigate = useNavigate()
  const [form, setForm] = useState<SetupRequest>({
    admin_username: '',
    admin_password: '',
    admin_real_name: '',
    fiscal_year: currentYear,
    firms: [newFirm(true)],
  })
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    publicFiscalYearApi.getSetupStatus().then((res) => {
      if (res.data.initialized) navigate('/login', { replace: true })
    }).catch(() => setError('无法连接服务器，请确认后端服务已启动'))
      .finally(() => setChecking(false))
  }, [navigate])

  const updateFirm = (firmIndex: number, patch: Partial<SetupFirm>) => {
    setForm((prev) => ({
      ...prev,
      firms: prev.firms.map((firm, index) => index === firmIndex ? { ...firm, ...patch } : firm),
    }))
  }

  const updateReportType = (firmIndex: number, reportIndex: number, field: string, value: string) => {
    setForm((prev) => ({
      ...prev,
      firms: prev.firms.map((firm, index) => index !== firmIndex ? firm : {
        ...firm,
        report_types: firm.report_types.map((report, itemIndex) => itemIndex === reportIndex ? { ...report, [field]: value } : report),
      }),
    }))
  }

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError('')
    if (form.admin_password.length < 8) {
      setError('管理员密码至少需要 8 位')
      return
    }
    if (form.admin_password !== confirmPassword) {
      setError('两次输入的管理员密码不一致')
      return
    }
    if (form.firms.some((firm) => !firm.name.trim() || firm.report_types.some((report) => !report.report_type.trim() || !report.template.trim()))) {
      setError('请完整填写事务所、业务类型和编号模板')
      return
    }
    if (form.firms.some((firm) => firm.report_types.some((report) => {
      const sequenceMatches = report.template.match(/\{n{1,10}\}/g) || []
      return !report.template.includes('{yyyy}') || sequenceMatches.length !== 1
    }))) {
      setError('编号模板必须包含 {yyyy}，并且只能包含一个序号占位符，例如 {nnn}')
      return
    }
    const formats = form.firms.flatMap(firm => firm.report_types.map(report =>
      report.template.replace(/\{yyyy\}/g, String(form.fiscal_year))
        .replace(/\{yy\}/g, String(form.fiscal_year).slice(-2))
        .replace(/\{n{1,10}\}/g, '{sequence}')
    ))
    if (new Set(formats).size !== formats.length) {
      setError('存在重复编号格式，请为不同业务规则设置不同模板')
      return
    }

    setSaving(true)
    try {
      await publicFiscalYearApi.setup(form)
      navigate('/login', { replace: true, state: { setupComplete: true } })
    } catch (err: any) {
      setError(err.response?.data?.detail || '初始化失败，请检查填写内容后重试')
    } finally {
      setSaving(false)
    }
  }

  if (checking) {
    return <div className="min-h-screen flex items-center justify-center text-muted-foreground">正在检查系统状态...</div>
  }

  return (
    <div className="min-h-screen bg-slate-50 py-8 px-4">
      <div className="mx-auto max-w-3xl">
        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <ShieldCheck className="h-6 w-6" />
          </div>
          <div>
            <h1 className="text-2xl font-bold">首次启用向导</h1>
            <p className="text-sm text-muted-foreground">完成一次配置后，系统即可供事务所团队使用</p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6">
          {error && <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}

          <Card>
            <CardHeader>
              <CardTitle className="text-lg">1. 创建管理员</CardTitle>
              <CardDescription>管理员负责后续用户、签字人和编号规则维护，请使用专用密码。</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="admin_username">登录账号</Label>
                <Input id="admin_username" value={form.admin_username} onChange={(e) => setForm({ ...form, admin_username: e.target.value })} placeholder="例如 zhangsan" required />
              </div>
              <div className="space-y-2">
                <Label htmlFor="admin_real_name">管理员姓名</Label>
                <Input id="admin_real_name" value={form.admin_real_name} onChange={(e) => setForm({ ...form, admin_real_name: e.target.value })} placeholder="请输入姓名" required />
              </div>
              <div className="space-y-2">
                <Label htmlFor="admin_password">登录密码</Label>
                <Input id="admin_password" type="password" value={form.admin_password} onChange={(e) => setForm({ ...form, admin_password: e.target.value })} placeholder="至少 8 位" required minLength={8} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="confirm_password">确认密码</Label>
                <Input id="confirm_password" type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} placeholder="再次输入密码" required />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-lg">2. 设置编号年度</CardTitle>
              <CardDescription>年度是报告编号的归属年度，之后可以在“编号年度配置”中继续添加年度。</CardDescription>
            </CardHeader>
            <CardContent className="max-w-xs space-y-2">
              <Label htmlFor="fiscal_year">首次操作年度</Label>
              <Input id="fiscal_year" type="number" min={2000} max={2100} value={form.fiscal_year} onChange={(e) => setForm({ ...form, fiscal_year: Number(e.target.value) })} required />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-lg">3. 配置事务所和编号规则</CardTitle>
              <CardDescription>事务所名称和编号格式由贵所自行填写；同一年度的不同规则须使用不同的完整编号格式。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              {form.firms.map((firm, firmIndex) => (
                <div key={firmIndex} className="rounded-md border bg-white p-4">
                  <div className="mb-4 flex items-center gap-2">
                    <Building2 className="h-5 w-5 text-primary" />
                    <Input className="max-w-sm" value={firm.name} onChange={(e) => updateFirm(firmIndex, { name: e.target.value })} placeholder="事务所名称，例如：XX会计师事务所" required />
                    {form.firms.length > 1 && <Button type="button" variant="ghost" size="icon" onClick={() => setForm({ ...form, firms: form.firms.filter((_, index) => index !== firmIndex) })} aria-label="删除事务所"><Trash2 className="h-4 w-4 text-destructive" /></Button>}
                  </div>
                  <div className="space-y-3">
                    {firm.report_types.map((report, reportIndex) => (
                      <div key={reportIndex} className="grid gap-3 rounded-md bg-slate-50 p-3 sm:grid-cols-[0.8fr_1.4fr_0.8fr_auto] sm:items-end">
                        <div className="space-y-1">
                          <Label>业务类型</Label>
                          <Input value={report.report_type} onChange={(e) => updateReportType(firmIndex, reportIndex, 'report_type', e.target.value)} placeholder="例如：年度审计" required />
                        </div>
                        <div className="space-y-1">
                          <Label>编号模板</Label>
                          <Input value={report.template} onChange={(e) => updateReportType(firmIndex, reportIndex, 'template', e.target.value)} placeholder="例如：{yyyy}-审-{nnn}" required />
                          <p className="text-xs text-muted-foreground">预览：{report.template.replace(/\{yyyy\}/g, String(form.fiscal_year)).replace(/\{yy\}/g, String(form.fiscal_year).slice(-2)).replace(/\{(n+)\}/g, (_, digits: string) => '1'.padStart(digits.length, '0'))}</p>
                        </div>
                        <div className="space-y-1">
                          <Label>规则名称</Label>
                          <Input value={report.rule_name || ''} onChange={(e) => updateReportType(firmIndex, reportIndex, 'rule_name', e.target.value)} placeholder="可选" />
                        </div>
                        <Button type="button" variant="ghost" size="icon" onClick={() => updateFirm(firmIndex, { report_types: firm.report_types.filter((_, index) => index !== reportIndex) })} disabled={firm.report_types.length <= 1} aria-label="删除业务类型"><Trash2 className="h-4 w-4 text-destructive" /></Button>
                      </div>
                    ))}
                  </div>
                  <Button type="button" variant="outline" size="sm" className="mt-3" onClick={() => updateFirm(firmIndex, { report_types: [...firm.report_types, newReportType()] })}><Plus className="mr-2 h-4 w-4" />添加业务类型</Button>
                </div>
              ))}
              <Button type="button" variant="outline" onClick={() => setForm({ ...form, firms: [...form.firms, newFirm()] })}><Plus className="mr-2 h-4 w-4" />添加事务所</Button>
            </CardContent>
          </Card>

          <div className="flex flex-col gap-3 sm:flex-row sm:justify-end">
            <Button type="button" variant="outline" onClick={() => navigate('/login')}>返回登录</Button>
            <Button type="submit" disabled={saving}><CheckCircle2 className="mr-2 h-4 w-4" />{saving ? '正在初始化...' : '完成初始化'}</Button>
          </div>
        </form>
      </div>
    </div>
  )
}
