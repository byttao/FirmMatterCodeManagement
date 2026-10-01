import { useNavigate, Outlet } from 'react-router-dom'
import { useAuth } from '@/store/AuthContext'
import { useDirty } from '@/context/DirtyContext'
import { brandingApi, licenseApi } from '@/api/auth'
import { numberedYearOptionsApi } from '@/api/fiscalYearConfig'
import { ROLE_LABELS, getUserDisplayName, can } from '@/types'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { LayoutDashboard, Briefcase, Users, LogOut, Menu, X, Calendar, PenLine, Settings, ShieldCheck, Building2 } from 'lucide-react'
import { useState, useEffect } from 'react'
import { version as APP_VERSION } from '../../package.json'

export default function Layout() {
  const navigate = useNavigate()
  const { user, logout, fiscalYear, setFiscalYear } = useAuth()
  const { confirmDirty } = useDirty()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [availableYears, setAvailableYears] = useState<number[]>([])
  const [licenseFeatures, setLicenseFeatures] = useState<string[] | null>(null)
  const [license, setLicense] = useState<{ mode: string; reason: string; limits: Record<string, number> | null; expires_at?: string }>({ mode: 'development', reason: '', limits: null })
  const [branding, setBranding] = useState({ short_name: '', logo_data: '', replace_banner: false, append_title: false })

  useEffect(() => {
    // 获取可选的年度列表（从API获取）
    const fetchAvailableYears = async () => {
      try {
        const res = await numberedYearOptionsApi.get()
        setAvailableYears(res.data.years)
        // 如果当前年度不在可选列表中，自动切换到API返回的年度
        if (!res.data.years.includes(fiscalYear)) {
          setFiscalYear(res.data.fiscal_year)
        }
      } catch (error) {
        console.error('获取年度失败:', error)
        // 降级：使用当前年
        const currentYear = new Date().getFullYear()
        setAvailableYears([currentYear])
      }
    }
    fetchAvailableYears()
  }, [])

  useEffect(() => {
    const refresh = () => licenseApi.status().then(licenseRes=>{
      setLicenseFeatures(licenseRes.data.features);setLicense(licenseRes.data)
    }).catch(()=>undefined)
    refresh()
    window.addEventListener('license-updated', refresh)
    brandingApi.public().then(brandingRes=>{
      setBranding(brandingRes.data)
      if (brandingRes.data.append_title && brandingRes.data.short_name) document.title = `业码汇 - ${brandingRes.data.short_name}`
    }).catch(() => undefined)
    return ()=>window.removeEventListener('license-updated', refresh)
  }, [])

  const handleYearChange = async (newYear: string) => {
    const year = parseInt(newYear)
    // 弹出确认框
    const confirmed = window.confirm(`确定要切换到 ${year} 编号年度吗？\n切换后将返回项目列表，并只显示该编号年度的项目。`)
    if (!confirmed) {
      // 用户取消，保持当前年度
      return
    }
    try {
      // 调用 API 设置年度，后端会返回包含新年度的 token
      // 更新本地 token（这样后续请求会使用新的 fiscal_year）
      setFiscalYear(year)
      // 跳转到项目列表
      navigate('/projects')
    } catch (error) {
      console.error('设置年度失败:', error)
      alert('切换年度失败，请重试')
    }
  }

  const handleLogout = async () => {
    try { await logout(); navigate('/login') }
    catch { alert('退出失败，请检查网络后重试') }
  }

  const canUse = (feature: string) => licenseFeatures === null || licenseFeatures.includes(feature)
  const navItems = [
    { path: '/account', label: '账号安全', icon: ShieldCheck, show: true },
    { path: '/exports', label: '导出任务', icon: Briefcase, show: user?.permissions.some(p=>p.startsWith('project.export.')||p==='signer.manage'||p==='billing.export_sensitive') },
    { path: '/system-backup', label: '备份与恢复', icon: ShieldCheck, show: can(user,'system.backup') },
    { path: '/', label: '数据看板', icon: LayoutDashboard, show: true },
    { path: '/customers', label: '客户管理', icon: Building2, show: can(user, 'customer.lookup') },
    { path: '/billing-worklist', label: '开票资料核验', icon: Building2, show: can(user, 'billing.verify') },
    { path: '/audit-events', label: '操作审计', icon: ShieldCheck, show: can(user, 'audit.read') },
    { path: '/project-change-requests', label: '项目申请', icon: Briefcase, show: can(user, 'project.transfer') || can(user, 'project.edit.led') },
    { path: '/projects', label: '项目管理', icon: Briefcase, show: canUse('project_management') },
    { path: '/users', label: '用户管理', icon: Users, show: can(user, 'identity.manage') && canUse('user_management') },
    { path: '/signers', label: '签字人管理', icon: PenLine, show: can(user, 'signer.manage') && canUse('signatory_review') },
    { path: '/fiscal-year-configs', label: '编号年度配置', icon: Settings, show: can(user, 'number.configure') && canUse('fiscal_year_settings') },
    { path: '/license', label: '授权与品牌', icon: ShieldCheck, show: can(user, 'license.manage') },
    { path: '/signed-projects', label: '我签字的项目', icon: PenLine, show: user?.is_practitioner && canUse('signatory_review') },
  ].filter(item => item.show)

  return (
    <div className="min-h-screen bg-gray-50">
      {/* 顶部导航 */}
      <header className="bg-white border-b sticky top-0 z-50">
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex flex-wrap items-center gap-3 min-w-0">
            <Button
              variant="ghost"
              size="icon"
              className="md:hidden"
              onClick={() => setSidebarOpen(!sidebarOpen)}
            >
              {sidebarOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
            </Button>
            {branding.replace_banner && branding.logo_data ? (
              <img src={branding.logo_data} alt={branding.short_name || '业码汇'} className="h-10 w-auto max-w-[180px] object-contain" />
            ) : (
              <img src="/branding/yemahui-banner-small.png" alt="业码汇" className="h-10 w-auto max-w-[180px] object-contain" />
            )}
            {branding.short_name && <span className="text-sm font-medium text-muted-foreground">{branding.short_name}</span>}
          </div>

          <div className="flex flex-wrap items-center gap-3 min-w-0">
            {/* 年度切换器 */}
            <div className="flex items-center gap-2">
              <Calendar className="w-4 h-4 text-muted-foreground" />
              <span className="text-sm text-muted-foreground">编号年度</span>
              <Select value={fiscalYear.toString()} onValueChange={handleYearChange}>
                <SelectTrigger className="w-[120px] h-8">
                  <SelectValue placeholder="选择年度" />
                </SelectTrigger>
                <SelectContent>
                  {availableYears.map((year) => (
                    <SelectItem key={year} value={year.toString()}>
                      {year} 年度
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="text-right max-w-[240px] break-words">
              <p className="text-sm font-medium">{user ? getUserDisplayName(user) : ''}</p>
              <p className="text-xs text-muted-foreground">{user?.roles.map(role => ROLE_LABELS[role]).join('、')}</p>
            </div>
            <Button variant="outline" size="sm" onClick={handleLogout}>
              <LogOut className="w-4 h-4 mr-2" />
              退出
            </Button>
          </div>
        </div>
      </header>

      <div className="flex">
        {/* 侧边栏 */}
        <aside className={`
          fixed inset-y-0 left-0 z-40 w-64 bg-white border-r transform transition-transform duration-200 ease-in-out overflow-y-auto
          md:translate-x-0 md:static md:sticky md:top-[57px] md:h-[calc(100vh-57px)] md:shrink-0
          ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}
        `}>
          <nav className="p-4 space-y-1">
            {navItems.map((item) => (
              <Button
                key={item.path}
                variant="ghost"
                className="w-full justify-start"
                onClick={() => {
                  confirmDirty(() => {
                    navigate(item.path)
                    setSidebarOpen(false)
                  })
                }}
              >
                <item.icon className="w-5 h-5 mr-3" />
                {item.label}
              </Button>
            ))}
          </nav>
          {/* 版本信息 */}
          <div className="absolute bottom-4 left-4 text-xs text-muted-foreground">
            v{APP_VERSION} · 业码汇 · <a className="hover:underline" href="https://github.com/byttao/FirmMatterCodeManagement" target="_blank" rel="noreferrer">GitHub</a>
            {license.mode === 'trial' && <span className="block text-amber-600">试用中</span>}
          </div>
        </aside>

        {/* 主内容 */}
        <main className="flex-1 min-w-0 p-4 md:p-6 overflow-auto">
          <Outlet />
        </main>
      </div>

      {/* 遮罩层（移动端） */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-30 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}
    </div>
  )
}
