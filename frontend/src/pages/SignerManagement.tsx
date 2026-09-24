import { useEffect, useState, useRef } from 'react'
import { signerApi, userApi } from '@/api/auth'
import { useAuth } from '@/store/AuthContext'
import { Navigate } from 'react-router-dom'
import type { Signer, SignerCreate, Practitioner } from '@/types'
import { getSignerDisplayName, getUserDisplayName, isSignerEligible } from '@/types'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Plus, Edit, Trash2, Loader2, Download, Upload, Power, PowerOff } from 'lucide-react'
import { useToast } from '@/hooks/use-toast'

export default function SignerManagement() {
  const { user } = useAuth()

  // 所有 Hooks 必须在条件语句之前调用（React Hooks 规则）
  const { toast } = useToast()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [signers, setSigners] = useState<Signer[]>([])
  const [practitioners, setPractitioners] = useState<Practitioner[]>([])
  const [firms, setFirms] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [showDialog, setShowDialog] = useState(false)
  const [editingSigner, setEditingSigner] = useState<Signer | null>(null)
  const [saving, setSaving] = useState(false)
  const [deletingSigner, setDeletingSigner] = useState<Signer | null>(null)
  const [deleteLoading, setDeleteLoading] = useState(false)
  const [filterFirm, setFilterFirm] = useState<string>('all')
  const [showDisabled, setShowDisabled] = useState(false)
  const [importing, setImporting] = useState(false)

  const [formData, setFormData] = useState<SignerCreate>({
    user_id: 0,
    signer_type: '',
  })

  // 检查权限：只有管理人员和后勤行政可以访问
  const canManage = user?.role === 'admin' || user?.role === 'admin_staff'
  const canDelete = user?.role === 'admin'  // 只有管理员可以删除

  useEffect(() => {
    loadFirms()
    loadSigners()
    userApi.listPractitioners().then(res => setPractitioners(res.data)).catch(() => {
      toast({ title: '加载执业人员失败', variant: 'destructive' })
    })
  }, [filterFirm, showDisabled])

  const loadFirms = async () => {
    try {
      const res = await signerApi.getFirms()
      setFirms(res.data.firms || [])
    } catch (err) {
      console.error('加载事务所失败', err)
    }
  }

  const loadSigners = async () => {
    try {
      const res = await signerApi.list(
        filterFirm === 'all' ? undefined : filterFirm,
        showDisabled
      )
      setSigners(res.data)
    } catch (err) {
      console.error('加载签字人失败', err)
    } finally {
      setLoading(false)
    }
  }

  const openCreateDialog = () => {
    setEditingSigner(null)
    setFormData({ user_id: 0, signer_type: firms[0] || '' })
    setShowDialog(true)
  }

  const openEditDialog = (signer: Signer) => {
    setEditingSigner(signer)
    setFormData({ user_id: signer.user_id || 0, signer_type: signer.signer_type })
    setShowDialog(true)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!formData.user_id || !formData.signer_type) {
      toast({ title: '请填写完整信息', variant: 'destructive' })
      return
    }
    setSaving(true)

    try {
      if (editingSigner) {
        await signerApi.update(editingSigner.id, formData)
        toast({ title: '修改成功' })
      } else {
        await signerApi.create(formData)
        toast({ title: '添加成功' })
      }
      loadSigners()
      setShowDialog(false)
    } catch (err: any) {
      toast({ title: err.response?.data?.detail || '保存失败', variant: 'destructive' })
    } finally {
      setSaving(false)
    }
  }

  const handleDisable = async (signer: Signer) => {
    try {
      if (signer.is_active) {
        await signerApi.disable(signer.id)
        toast({ title: '已禁用' })
      } else {
        await signerApi.enable(signer.id)
        toast({ title: '已启用' })
      }
      loadSigners()
    } catch (err: any) {
      toast({ title: err.response?.data?.detail || '操作失败', variant: 'destructive' })
    }
  }

  const handleDelete = async () => {
    if (!deletingSigner) return
    setDeleteLoading(true)

    try {
      await signerApi.delete(deletingSigner.id)
      toast({ title: '删除成功' })
      loadSigners()
      setDeletingSigner(null)
    } catch (err: any) {
      toast({ title: err.response?.data?.detail || '删除失败', variant: 'destructive' })
    } finally {
      setDeleteLoading(false)
    }
  }

  const handleExport = async () => {
    try {
      const res = await signerApi.export()
      const blob = new Blob([res.data], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `signers_${new Date().toISOString().slice(0, 10)}.xlsx`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      toast({ title: '导出失败', variant: 'destructive' })
    }
  }

  const handleDownloadTemplate = async () => {
    try {
      const res = await signerApi.downloadTemplate()
      const blob = new Blob([res.data], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'signers_template.xlsx'
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      toast({ title: '下载模板失败', variant: 'destructive' })
    }
  }

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setImporting(true)
    try {
      const res = await signerApi.import(file)
      toast({ title: res.data.message })
      if (res.data.errors?.length) {
        toast({ title: res.data.errors[0], variant: 'destructive' })
      }
      loadSigners()
      loadFirms()
    } catch (err: any) {
      toast({ title: err.response?.data?.detail || '导入失败', variant: 'destructive' })
    } finally {
      setImporting(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  // 按事务所分组显示
  const groupedSigners = signers.reduce((acc, signer) => {
    const firm = signer.signer_type
    if (!acc[firm]) acc[firm] = []
    acc[firm].push(signer)
    return acc
  }, {} as Record<string, Signer[]>)

  if (!canManage) {
    return <Navigate to="/projects" replace />
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">签字人管理</h1>
          <p className="text-muted-foreground">签字人须关联执业人员账号；旧记录需人工确认</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={handleExport}>
            <Download className="w-4 h-4 mr-2" />
            导出
          </Button>
          <Button variant="outline" onClick={handleDownloadTemplate} title="下载导入模板">
            <Download className="w-4 h-4 mr-2" />
            下载模板
          </Button>
          <Button variant="outline" onClick={() => fileInputRef.current?.click()} disabled={importing}>
            {importing ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Upload className="w-4 h-4 mr-2" />}
            导入
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx"
            onChange={handleImport}
            className="hidden"
          />
          <Button onClick={openCreateDialog}>
            <Plus className="w-4 h-4 mr-2" />
            添加签字人
          </Button>
        </div>
      </div>

      {/* 筛选器 */}
      <div className="flex gap-4 items-center">
        <div className="space-y-2">
          <Select value={filterFirm} onValueChange={setFilterFirm}>
            <SelectTrigger className="w-[150px]">
              <SelectValue placeholder="筛选事务所" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部事务所</SelectItem>
              {firms.map(firm => (
                <SelectItem key={firm} value={firm}>{firm}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={showDisabled}
            onChange={(e) => setShowDisabled(e.target.checked)}
            className="rounded border-gray-300"
          />
          显示已禁用
        </label>
        <div className="flex gap-2 ml-auto">
          {firms.map(firm => (
            <Badge key={firm} variant="outline">
              {firm}: {signers.filter(s => s.signer_type === firm && s.is_active).length}条
              {signers.filter(s => s.signer_type === firm && !s.is_active).length > 0 && (
                <span className="text-orange-500 ml-1">
                  ({signers.filter(s => s.signer_type === firm && !s.is_active).length}已禁用)
                </span>
              )}
            </Badge>
          ))}
        </div>
      </div>

      {/* 签字人列表 - 按事务所分组 */}
      {loading ? (
        <div className="flex items-center justify-center h-64">
          <Loader2 className="w-8 h-8 animate-spin" />
        </div>
      ) : Object.keys(groupedSigners).length === 0 ? (
        <div className="border rounded-lg p-8 text-center text-muted-foreground">
          暂无签字人数据
        </div>
      ) : (
        Object.entries(groupedSigners).map(([firm, firmSigners]) => (
          <div key={firm} className="border rounded-lg overflow-hidden">
            <div className="bg-muted/50 px-4 py-2 font-medium">{firm}</div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[80px]">ID</TableHead>
                  <TableHead>签字人（账号）</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>新增日期</TableHead>
                  <TableHead>禁用日期</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {firmSigners.map(signer => (
                  <TableRow key={signer.id} className={!signer.is_active ? 'opacity-60' : ''}>
                    <TableCell className="font-medium">{signer.id}</TableCell>
                    <TableCell>{getSignerDisplayName(signer)}</TableCell>
                    <TableCell>
                      <Badge variant={!signer.user_id ? 'outline' : isSignerEligible(signer) ? 'default' : 'secondary'}>
                        {!signer.user_id ? '待关联' : !signer.is_active ? '禁用' : !signer.user?.is_active || signer.user.role !== 'practitioner' ? '账号不可用' : '启用'}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {new Date(signer.created_at).toLocaleDateString()}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {signer.disabled_at ? new Date(signer.disabled_at).toLocaleDateString() : '-'}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => openEditDialog(signer)}
                          title={signer.user_id ? '编辑事务所' : '关联执业账号'}
                        >
                          <Edit className="w-4 h-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleDisable(signer)}
                          disabled={!signer.user_id && !signer.is_active}
                          title={signer.is_active ? '禁用' : '启用'}
                        >
                          {signer.is_active ? (
                            <PowerOff className="w-4 h-4 text-orange-500" />
                          ) : (
                            <Power className="w-4 h-4 text-green-500" />
                          )}
                        </Button>
                        {canDelete && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setDeletingSigner(signer)}
                            title="删除"
                          >
                            <Trash2 className="w-4 h-4 text-red-500" />
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ))
      )}

      {/* 创建/编辑对话框 */}
      <Dialog open={showDialog} onOpenChange={setShowDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editingSigner ? (editingSigner.user_id ? '编辑签字人' : '关联旧签字人') : '添加签字人'}
            </DialogTitle>
            <DialogDescription>
              {editingSigner?.user_id ? '已关联账号不能改绑；历史签字姓名会保留' : '请选择唯一的执业人员账号'}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label>执业人员账号</Label>
              {editingSigner?.user_id ? (
                <div className="rounded-md border px-3 py-2 text-sm">
                  {editingSigner.user ? getUserDisplayName(editingSigner.user) : `账号 ID ${editingSigner.user_id}`}
                </div>
              ) : <Select
                value={formData.user_id ? String(formData.user_id) : ''}
                onValueChange={value => setFormData(prev => ({ ...prev, user_id: Number(value) }))}
              >
                <SelectTrigger><SelectValue placeholder="选择执业人员" /></SelectTrigger>
                <SelectContent>
                  {practitioners.map(person => (
                    <SelectItem key={person.id} value={String(person.id)}>
                      {getUserDisplayName(person)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="signer_type">事务所</Label>
              <Select
                value={formData.signer_type}
                onValueChange={(v) => setFormData(prev => ({ ...prev, signer_type: v }))}
              >
                <SelectTrigger>
                  <SelectValue placeholder="选择事务所" />
                </SelectTrigger>
                <SelectContent>
                  {firms.map(firm => (
                    <SelectItem key={firm} value={firm}>{firm}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setShowDialog(false)}>
                取消
              </Button>
              <Button type="submit" disabled={saving}>
                {saving && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
                {editingSigner ? '保存' : '创建'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* 删除确认对话框 */}
      <Dialog open={!!deletingSigner} onOpenChange={() => setDeletingSigner(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认删除</DialogTitle>
            <DialogDescription>
              确定要删除签字人 "{deletingSigner?.name}" 吗？此操作不可撤销。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeletingSigner(null)}>
              取消
            </Button>
            <Button variant="destructive" onClick={handleDelete} disabled={deleteLoading}>
              {deleteLoading && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
