import { useEffect, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { Eye } from 'lucide-react'
import { projectApi } from '@/api/auth'
import { useAuth } from '@/store/AuthContext'
import type { Project } from '@/types'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

export default function SignedProjects() {
  const { user, fiscalYear } = useAuth()
  const navigate = useNavigate()
  const [items, setItems] = useState<Project[]>([])
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => setPage(1), [fiscalYear])
  useEffect(() => {
    if (user?.role !== 'practitioner') return
    setLoading(true)
    projectApi.signedByMe(page).then(response => {
      setItems(response.data.items)
      setTotal(response.data.total)
      setError('')
    }).catch(() => setError('签字项目加载失败')).finally(() => setLoading(false))
  }, [page, fiscalYear, user?.role])

  if (user?.role !== 'practitioner') return <Navigate to="/projects" replace />

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between gap-4">
        <h1 className="text-2xl font-bold">我签字的项目</h1>
        <span className="text-sm text-muted-foreground">{fiscalYear} 年度 · 共 {total} 项</span>
      </div>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <div className="overflow-x-auto border rounded-md">
        <Table>
          <TableHeader><TableRow>
            <TableHead>项目编号</TableHead><TableHead>客户</TableHead><TableHead>事务所</TableHead>
            <TableHead>业务类型</TableHead><TableHead>报告编号</TableHead><TableHead>项目状态</TableHead>
            <TableHead className="w-16">查看</TableHead>
          </TableRow></TableHeader>
          <TableBody>
            {loading ? <TableRow><TableCell colSpan={7} className="text-center py-8">加载中...</TableCell></TableRow>
              : items.length === 0 ? <TableRow><TableCell colSpan={7} className="text-center py-8 text-muted-foreground">暂无签字项目</TableCell></TableRow>
              : items.map(project => <TableRow key={project.id}>
                <TableCell className="font-mono">{project.project_id}</TableCell>
                <TableCell>{project.customer_name}</TableCell><TableCell>{project.firm}</TableCell>
                <TableCell>{project.report_type}</TableCell><TableCell>{project.report_no || '-'}</TableCell>
                <TableCell>{project.project_status}</TableCell>
                <TableCell><Button variant="ghost" size="icon" title="查看详情" onClick={() => navigate(`/projects/${project.project_id}`)}><Eye className="w-4 h-4" /></Button></TableCell>
              </TableRow>)}
          </TableBody>
        </Table>
      </div>
      {total > 20 && <div className="flex items-center justify-between text-sm">
        <span>第 {page} / {Math.ceil(total / 20)} 页</span>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" disabled={page === 1} onClick={() => setPage(page - 1)}>上一页</Button>
          <Button variant="outline" size="sm" disabled={page * 20 >= total} onClick={() => setPage(page + 1)}>下一页</Button>
        </div>
      </div>}
    </div>
  )
}
