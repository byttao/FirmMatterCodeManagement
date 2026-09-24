import { useNavigate, Outlet } from 'react-router-dom'
import { useAuth } from '@/store/AuthContext'
import { useDirty } from '@/context/DirtyContext'
import { userApi } from '@/api/auth'
import { numberedYearOptionsApi } from '@/api/fiscalYearConfig'
import { ROLE_LABELS, getUserDisplayName } from '@/types'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { LayoutDashboard, Briefcase, Users, LogOut, Menu, X, Calendar, PenLine, Settings } from 'lucide-react'
import { useState, useEffect } from 'react'

export default function Layout() {
  const navigate = useNavigate()
  const { user, logout, fiscalYear, setFiscalYear } = useAuth()
  const { confirmDirty } = useDirty()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [availableYears, setAvailableYears] = useState<number[]>([])

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

  const handleYearChange = async (newYear: string) => {
    const year = parseInt(newYear)
    // 弹出确认框
    const confirmed = window.confirm(`确定要切换到 ${year} 年度吗？\n切换后将返回项目列表，并只显示该年度的项目。`)
    if (!confirmed) {
      // 用户取消，保持当前年度
      return
    }
    try {
      // 调用 API 设置年度，后端会返回包含新年度的 token
      const res = await userApi.setFiscalYear(year)
      // 更新本地 token（这样后续请求会使用新的 fiscal_year）
      localStorage.setItem('token', res.data.access_token)
      setFiscalYear(year)
      // 跳转到项目列表
      navigate('/projects')
    } catch (error) {
      console.error('设置年度失败:', error)
      alert('切换年度失败，请重试')
    }
  }

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const navItems = [
    { path: '/', label: '数据看板', icon: LayoutDashboard, show: true },
    { path: '/projects', label: '项目管理', icon: Briefcase, show: true },
    { path: '/signed-projects', label: '我签字的项目', icon: PenLine, show: user?.role === 'practitioner' },
    { path: '/signers', label: '签字人管理', icon: PenLine, show: user?.role === 'admin' || user?.role === 'admin_staff' },
    { path: '/fiscal-year-configs', label: '编号年度配置', icon: Settings, show: user?.role === 'admin' || user?.role === 'admin_staff' },
    { path: '/users', label: '用户管理', icon: Users, show: user?.role === 'admin' },
  ].filter(item => item.show)

  return (
    <div className="min-h-screen bg-gray-50">
      {/* 顶部导航 */}
      <header className="bg-white border-b sticky top-0 z-50">
        <div className="flex items-center justify-between px-4 py-3">
          <div className="flex items-center gap-4">
            <Button
              variant="ghost"
              size="icon"
              className="md:hidden"
              onClick={() => setSidebarOpen(!sidebarOpen)}
            >
              {sidebarOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
            </Button>
            <h1 className="text-lg font-bold text-primary">事务所项目管理系统</h1>
          </div>

          <div className="flex items-center gap-4">
            {/* 年度切换器 */}
            <div className="flex items-center gap-2">
              <Calendar className="w-4 h-4 text-muted-foreground" />
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

            <div className="text-right">
              <p className="text-sm font-medium">{user ? getUserDisplayName(user) : ''}</p>
              <p className="text-xs text-muted-foreground">{ROLE_LABELS[user?.role || '']}</p>
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
            v0.1.6
          </div>
        </aside>

        {/* 主内容 */}
        <main className="flex-1 p-6 overflow-auto">
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
