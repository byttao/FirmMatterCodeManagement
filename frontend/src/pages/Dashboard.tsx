import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { dashboardApi, exportApi } from '@/api/auth'
import { useAuth } from '@/store/AuthContext'
import type { DashboardStats } from '@/types'
import { getUserDisplayName } from '@/types'
import { formatCurrency } from '@/lib/utils'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import {
  Briefcase, CheckCircle, PauseCircle, XCircle,
  TrendingUp, DollarSign, FileText, Download
} from 'lucide-react'

export default function Dashboard() {
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()
  const { user, fiscalYear } = useAuth()

  useEffect(() => {
    loadStats()
  }, [fiscalYear])

  const loadStats = async () => {
    try {
      const res = await dashboardApi.getStats(fiscalYear)
      setStats(res.data)
    } catch (err) {
      console.error('加载看板数据失败', err)
    } finally {
      setLoading(false)
    }
  }

  const handleExport = async () => {
    try {
      const res = await exportApi.exportProjects(fiscalYear)
      const blob = new Blob([res.data], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      })
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `项目列表_${new Date().toISOString().split('T')[0]}.xlsx`
      a.click()
      window.URL.revokeObjectURL(url)
    } catch (err) {
      console.error('导出失败', err)
    }
  }

  if (loading) {
    return <div className="flex items-center justify-center h-64">加载中...</div>
  }

  if (!stats) {
    return <div className="text-center text-muted-foreground">暂无数据</div>
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">数据看板</h1>
          <p className="text-muted-foreground">欢迎回来，{user ? getUserDisplayName(user) : ''}</p>
        </div>
        {user?.role !== 'practitioner' && (
          <Button onClick={handleExport}>
            <Download className="w-4 h-4 mr-2" />
            导出Excel
          </Button>
        )}
      </div>

      {/* 项目统计卡片 */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-5">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">项目总数</CardTitle>
            <Briefcase className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.total_projects}</div>
            <p className="text-xs text-muted-foreground">
              本月新增 {stats.this_month_new} 个
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">进行中</CardTitle>
            <TrendingUp className="h-4 w-4 text-blue-600" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-blue-600">{stats.ongoing_projects}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">已完成</CardTitle>
            <CheckCircle className="h-4 w-4 text-green-600" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-green-600">{stats.completed_projects}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">已暂停</CardTitle>
            <PauseCircle className="h-4 w-4 text-yellow-600" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-yellow-600">{stats.paused_projects}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">已取消</CardTitle>
            <XCircle className="h-4 w-4 text-red-600" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-red-600">{stats.cancelled_projects}</div>
          </CardContent>
        </Card>
      </div>

      {/* 财务统计卡片 */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">合同总金额</CardTitle>
            <DollarSign className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{formatCurrency(stats.total_contract_amount)}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">已收款 / 未收款</CardTitle>
            <FileText className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold text-green-600">
              {formatCurrency(stats.total_received_amount)}
            </div>
            <p className="text-xs text-muted-foreground">
              未收款：{formatCurrency(stats.total_unreceived)}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">已开票 / 未开票</CardTitle>
            <FileText className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-xl font-bold text-blue-600">
              {formatCurrency(stats.total_invoiced_amount)}
            </div>
            <p className="text-xs text-muted-foreground">
              未开票：{formatCurrency(stats.total_uninvoiced)}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* 快捷操作 */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card className="cursor-pointer hover:bg-accent/50 transition-colors" onClick={() => navigate('/projects')}>
          <CardContent className="pt-6">
            <div className="text-center">
              <Briefcase className="w-8 h-8 mx-auto mb-2 text-primary" />
              <h3 className="font-semibold">项目管理</h3>
              <p className="text-sm text-muted-foreground">查看和管理所有项目</p>
            </div>
          </CardContent>
        </Card>

        {user?.role === 'admin' && (
          <Card className="cursor-pointer hover:bg-accent/50 transition-colors" onClick={() => navigate('/users')}>
            <CardContent className="pt-6">
              <div className="text-center">
                <div className="w-8 h-8 mx-auto mb-2 rounded-full bg-primary text-primary-foreground flex items-center justify-center">
                  <span className="text-lg font-bold">+</span>
                </div>
                <h3 className="font-semibold">用户管理</h3>
                <p className="text-sm text-muted-foreground">管理系统用户</p>
              </div>
            </CardContent>
          </Card>
        )}

        {(user?.role === 'admin' || user?.role === 'practitioner') && (
          <Card
            className="cursor-pointer hover:bg-accent/50 transition-colors"
            onClick={() => navigate('/projects/new')}
          >
            <CardContent className="pt-6">
              <div className="text-center">
                <div className="w-8 h-8 mx-auto mb-2 rounded-full bg-green-600 text-white flex items-center justify-center">
                  <span className="text-lg font-bold">+</span>
                </div>
                <h3 className="font-semibold">新建项目</h3>
                <p className="text-sm text-muted-foreground">创建新项目</p>
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}
