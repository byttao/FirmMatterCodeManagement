import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { projectApi, userApi } from '@/api/auth'
import { numberedYearOptionsApi } from '@/api/fiscalYearConfig'
import { useAuth } from '@/store/AuthContext'
import type { Project, Practitioner } from '@/types'
import { getUserDisplayName } from '@/types'
import { formatCurrency } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Plus, Search, Trash2, RotateCcw, Eye, Edit } from 'lucide-react'




export default function ProjectList() {
  const [projects, setProjects] = useState<Project[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [users, setUsers] = useState<Practitioner[]>([])

  // 动态筛选选项
  const [firmOptions, setFirmOptions] = useState<string[]>([])
  const [reportTypeOptions, setReportTypeOptions] = useState<string[]>([])

  // 筛选条件
  const [search, setSearch] = useState('')
  const [firm, setFirm] = useState<string>('all')
  const [reportType, setReportType] = useState<string>('all')
  const [projectStatus, setProjectStatus] = useState<string>('all')
  const [leaderId, setLeaderId] = useState<string>('all')

  // 删除确认
  const [deleteProject, setDeleteProject] = useState<Project | null>(null)
  const [deleting, setDeleting] = useState(false)

  const navigate = useNavigate()
  const { user, fiscalYear } = useAuth()

  const canCreateProject = user?.role !== 'admin_staff'
  const canRecycleNo = user?.role === 'admin' || user?.role === 'admin_staff'

  // 判断用户是否可以删除某个项目
  const canDeleteThisProject = (project: Project) => {
    if (user?.role === 'admin' || user?.role === 'admin_staff') {
      return true
    }
    // 执业人员：只能删除自己负责且未编号的项目
    if (user?.role === 'practitioner') {
      return project.leader_id === user.id && !project.report_no
    }
    return false
  }

  // fiscalYear 变化时重置页码并重新加载
  useEffect(() => {
    setPage(1)
    loadProjects()
    loadFirmOptions()
  }, [fiscalYear])

  useEffect(() => {
    loadProjects()
  }, [page, firm, reportType, projectStatus, leaderId])

  useEffect(() => {
    loadUsers()
    loadFirmOptions()
  }, [])

  // 当事务所筛选变化时，更新业务类型选项
  useEffect(() => {
    if (firm && firm !== 'all') {
      loadReportTypeOptions(firm)
    } else {
      // 全部事务所：汇总所有业务类型
      loadAllReportTypeOptions()
    }
    // 重置业务类型筛选
    setReportType('all')
  }, [firm, fiscalYear])

  const loadProjects = async () => {
    setLoading(true)
    try {
      const res = await projectApi.list({
        page,
        page_size: 20,
        search: search || undefined,
        firm: firm && firm !== 'all' ? firm : undefined,
        report_type: reportType && reportType !== 'all' ? reportType : undefined,
        project_status: projectStatus && projectStatus !== 'all' ? projectStatus : undefined,
        leader_id: leaderId && leaderId !== 'all' ? parseInt(leaderId) : undefined,
      })
      setProjects(res.data.items)
      setTotal(res.data.total)
    } catch (err) {
      console.error('加载项目列表失败', err)
    } finally {
      setLoading(false)
    }
  }

  const loadFirmOptions = async () => {
    try {
      const year = fiscalYear || new Date().getFullYear()
      const res = await numberedYearOptionsApi.get(year)
      setFirmOptions(Array.isArray(res.data?.firms) ? res.data.firms : [])
    } catch (err) {
      console.error('加载事务所列表失败', err)
    }
  }

  const loadReportTypeOptions = async (selectedFirm: string) => {
    try {
      const year = fiscalYear || new Date().getFullYear()
      const res = await numberedYearOptionsApi.get(year, selectedFirm)
      setReportTypeOptions(Array.isArray(res.data?.report_types) ? res.data.report_types : [])
    } catch (err) {
      console.error('加载业务类型失败', err)
    }
  }

  const loadAllReportTypeOptions = async () => {
    try {
      const year = fiscalYear || new Date().getFullYear()
      const firmsRes = await numberedYearOptionsApi.get(year)
      const firms = Array.isArray(firmsRes.data?.firms) ? firmsRes.data.firms : []
      const allTypes = new Set<string>()
      for (const f of firms) {
        const res = await numberedYearOptionsApi.get(year, f)
        const types = Array.isArray(res.data?.report_types) ? res.data.report_types : []
        types.forEach(t => allTypes.add(t))
      }
      setReportTypeOptions(Array.from(allTypes))
    } catch (err) {
      console.error('加载业务类型失败', err)
    }
  }

  const loadUsers = async () => {
    try {
      // 使用执业人员接口，所有已认证用户都可访问
      const res = await userApi.listPractitioners()
      setUsers(res.data)
    } catch (err) {
      console.error('加载用户失败', err)
    }
  }

  const handleSearch = () => {
    setPage(1)
    loadProjects()
  }

  const handleDelete = async () => {
    if (!deleteProject) return
    setDeleting(true)
    try {
      await projectApi.delete(deleteProject.id)
      loadProjects()
      setDeleteProject(null)
    } catch (err: any) {
      alert(err.response?.data?.detail || '删除失败')
    } finally {
      setDeleting(false)
    }
  }

  const handleRecycleNo = async (project: Project) => {
    try {
      await projectApi.recycleReportNo(project.id)
      loadProjects()
    } catch (err: any) {
      alert(err.response?.data?.detail || '回收编号失败')
    }
  }

  const getStatusVariant = (status: string): 'default' | 'secondary' | 'destructive' | 'outline' | 'success' | 'warning' => {
    if (status === 'assigned') return 'success'
    if (status === 'recycled') return 'warning'
    return 'secondary'
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">项目管理</h1>
        {canCreateProject && (
          <Button onClick={() => navigate('/projects/new')}>
            <Plus className="w-4 h-4 mr-2" />
            新建项目
          </Button>
        )}
      </div>

      {/* 筛选栏 */}
      <div className="flex flex-wrap gap-4 p-4 bg-card rounded-lg border">
        <div className="flex-1 min-w-[200px]">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              placeholder="搜索客户名称、项目ID、报告编号..."
              className="pl-10"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            />
          </div>
        </div>
        <Select value={firm} onValueChange={setFirm}>
          <SelectTrigger className="w-[120px]">
            <SelectValue placeholder="事务所" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部事务所</SelectItem>
            {firmOptions.map(f => (
              <SelectItem key={f} value={f}>{f}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={reportType} onValueChange={setReportType}>
          <SelectTrigger className="w-[120px]">
            <SelectValue placeholder="报告类型" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部类型</SelectItem>
            {reportTypeOptions.map(t => (
              <SelectItem key={t} value={t}>{t}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={projectStatus} onValueChange={setProjectStatus}>
          <SelectTrigger className="w-[120px]">
            <SelectValue placeholder="项目状态" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部状态</SelectItem>
            <SelectItem value="进行中">进行中</SelectItem>
            <SelectItem value="已完成">已完成</SelectItem>
            <SelectItem value="已暂停">已暂停</SelectItem>
            <SelectItem value="已取消">已取消</SelectItem>
          </SelectContent>
        </Select>
        <Select value={leaderId} onValueChange={setLeaderId}>
          <SelectTrigger className="w-[140px]">
            <SelectValue placeholder="执业负责人" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部负责人</SelectItem>
            {users.map((u) => (
              <SelectItem key={u.id} value={u.id.toString()}>
                {getUserDisplayName(u)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button variant="outline" onClick={handleSearch}>搜索</Button>
      </div>

      {/* 列表 */}
      <div className="border rounded-lg">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[130px]">项目ID</TableHead>
              <TableHead>客户名称</TableHead>
              <TableHead>事务所</TableHead>
              <TableHead>报告类型</TableHead>
              <TableHead>报告编号</TableHead>
              <TableHead>编号状态</TableHead>
              <TableHead>执业负责人</TableHead>
              <TableHead>项目状态</TableHead>
              <TableHead className="text-right">合同金额</TableHead>
              <TableHead className="w-[150px]">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={10} className="text-center py-8">
                  加载中...
                </TableCell>
              </TableRow>
            ) : projects.length === 0 ? (
              <TableRow>
                <TableCell colSpan={10} className="text-center py-8 text-muted-foreground">
                  暂无项目
                </TableCell>
              </TableRow>
            ) : (
              projects.map((project) => (
                <TableRow key={project.id}>
                  <TableCell className="font-mono text-sm">{project.project_id}</TableCell>
                  <TableCell>{project.customer_name}</TableCell>
                  <TableCell>{project.firm}</TableCell>
                  <TableCell>{project.report_type}</TableCell>
                  <TableCell className="font-mono text-sm">
                    {project.report_no || '-'}
                  </TableCell>
                  <TableCell>
                    <Badge variant={getStatusVariant(project.report_no_status)}>
                      {project.report_no_status === 'pending' ? '待编号' :
                       project.report_no_status === 'assigned' ? '已编号' : '已回收'}
                    </Badge>
                  </TableCell>
                  <TableCell>{project.leader ? getUserDisplayName(project.leader) : '-'}</TableCell>
                  <TableCell>
                    <Badge variant={
                      project.project_status === '进行中' ? 'default' :
                      project.project_status === '已完成' ? 'success' :
                      project.project_status === '已暂停' ? 'warning' : 'destructive'
                    }>
                      {project.project_status}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    {formatCurrency(project.contract_amount)}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => navigate(`/projects/${project.project_id}`)}
                        title="查看详情"
                      >
                        <Eye className="w-4 h-4" />
                      </Button>
                      {(user?.role === 'admin' || (user?.role === 'practitioner' && project.leader_id === user.id)) && (
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => navigate(`/projects/${project.project_id}/edit`)}
                          title="编辑"
                        >
                          <Edit className="w-4 h-4" />
                        </Button>
                      )}
                      {canRecycleNo && project.report_no && (
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleRecycleNo(project)}
                          title="回收编号"
                        >
                          <RotateCcw className="w-4 h-4" />
                        </Button>
                      )}
                      {canDeleteThisProject(project) && (
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => setDeleteProject(project)}
                          title="删除项目"
                          className="text-red-600 hover:text-red-700"
                        >
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* 分页 */}
      {total > 20 && (
        <div className="flex items-center justify-between">
          <p className="text-sm text-muted-foreground">
            共 {total} 条记录，第 {page} 页
          </p>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page === 1}
              onClick={() => setPage(p => p - 1)}
            >
              上一页
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={page * 20 >= total}
              onClick={() => setPage(p => p + 1)}
            >
              下一页
            </Button>
          </div>
        </div>
      )}

      {/* 删除确认弹窗 */}
      <Dialog open={!!deleteProject} onOpenChange={() => setDeleteProject(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认删除</DialogTitle>
            <DialogDescription>
              确定要删除项目「{deleteProject?.customer_name}」吗？删除后报告编号将回收。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteProject(null)}>
              取消
            </Button>
            <Button variant="destructive" onClick={handleDelete} disabled={deleting}>
              {deleting ? '删除中...' : '确认删除'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
