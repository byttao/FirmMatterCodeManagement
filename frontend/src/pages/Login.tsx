import { useState, useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '@/store/AuthContext'
import { authApi } from '@/api/auth'
import { publicFiscalYearApi } from '@/api/fiscalYearConfig'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

export default function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [fiscalYear, setFiscalYear] = useState<number>(new Date().getFullYear())
  const [availableYears, setAvailableYears] = useState<number[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [initLoading, setInitLoading] = useState(true)
  const navigate = useNavigate()
  const location = useLocation()
  const { login } = useAuth()

  // 首先确认系统已完成安装，再读取可用年度。
  useEffect(() => {
    const currentYear = new Date().getFullYear()
    publicFiscalYearApi.getSetupStatus().then(statusRes => {
      if (!statusRes.data.initialized) {
        navigate('/setup', { replace: true })
        return null
      }
      return publicFiscalYearApi.getYears().then(res => {
        const sortedYears = [...(res.data.years || [])].sort((a, b) => b - a)
        setAvailableYears(sortedYears)
        if (!sortedYears.includes(fiscalYear)) {
          setFiscalYear(sortedYears[0] || currentYear)
        }
      })
    }).catch(() => {
      setError('无法连接服务器，请确认后端服务已启动')
    }).finally(() => {
      setInitLoading(false)
    })
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const res = await authApi.login({ username, password, fiscal_year: fiscalYear })
      const token = res.data.access_token
      const returnedFiscalYear = res.data.fiscal_year

      // 先存储 token（让 axios 拦截器能读取到）
      localStorage.setItem('token', token)
      if (returnedFiscalYear) {
        localStorage.setItem('fiscalYear', returnedFiscalYear.toString())
      }

      // 获取用户信息
      const userRes = await authApi.getMe()
      login(token, userRes.data, returnedFiscalYear)
      navigate('/')
    } catch (err: any) {
      setError(err.response?.data?.detail || '登录失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 to-indigo-100 p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-1 text-center">
          <CardTitle className="text-2xl font-bold">事务所项目管理系统</CardTitle>
          <CardDescription>请输入账号密码登录</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            {location.state?.setupComplete && (
              <div className="p-3 text-sm text-green-700 bg-green-50 rounded-md">
                初始化完成，请使用刚创建的管理员账号登录。
              </div>
            )}
            {error && (
              <div className="p-3 text-sm text-red-600 bg-red-50 rounded-md">
                {error}
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="username">用户名</Label>
              <Input
                id="username"
                type="text"
                placeholder="请输入用户名"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">密码</Label>
              <Input
                id="password"
                type="password"
                placeholder="请输入密码"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="fiscalYear">当前操作年度</Label>
              {initLoading ? (
                <Input value="加载中..." disabled />
              ) : (
                <Select
                  value={fiscalYear.toString()}
                  onValueChange={(v) => setFiscalYear(parseInt(v))}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="请选择操作年度" />
                  </SelectTrigger>
                  <SelectContent>
                    {availableYears.map((year) => (
                      <SelectItem key={year} value={year.toString()}>
                        {year} 年度
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
              <p className="text-xs text-gray-500">
                {availableYears.length > 0 ? `报告编号将使用 ${fiscalYear} 年度` : '请先完成系统安装'}
              </p>
            </div>
            <Button type="submit" className="w-full" disabled={loading || initLoading}>
              {loading ? '登录中...' : '登录'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
