import { useEffect, useState } from 'react'
import { userApi } from '@/api/auth'
import { useAuth } from '@/store/AuthContext'
import { Navigate } from 'react-router-dom'
import type { User } from '@/types'
import { ROLE_LABELS, getUserDisplayName } from '@/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Plus, Edit, Trash2, Loader2, RotateCcw, Search, X } from 'lucide-react'

export default function UserManagement() {
  const { user } = useAuth()
  const canManage = user?.role === 'admin'

  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(true)
  const [showDialog, setShowDialog] = useState(false)
  const [editingUser, setEditingUser] = useState<User | null>(null)
  const [saving, setSaving] = useState(false)
  const [deletingUser, setDeletingUser] = useState<User | null>(null)
  const [deleteLoading, setDeleteLoading] = useState(false)
  const [showDeleted, setShowDeleted] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')

  const [formData, setFormData] = useState({
    username: '',
    password: '',
    real_name: '',
    role: 'practitioner',
  })

  useEffect(() => {
    if (!canManage) {
      setLoading(false)
      return
    }
    loadUsers()
  }, [showDeleted, canManage])

  const loadUsers = async () => {
    setLoading(true)
    try {
      const res = await userApi.list(showDeleted)
      setUsers(res.data)
    } catch (err) {
      console.error('加载用户失败', err)
    } finally {
      setLoading(false)
    }
  }

  const openCreateDialog = () => {
    setEditingUser(null)
    setFormData({ username: '', password: '', real_name: '', role: 'practitioner' })
    setShowDialog(true)
  }

  const openEditDialog = (user: User) => {
    setEditingUser(user)
    setFormData({ username: user.username, password: '', real_name: user.real_name, role: user.role })
    setShowDialog(true)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)

    try {
      if (editingUser) {
        await userApi.update(editingUser.id, {
          real_name: formData.real_name,
          role: formData.role,
          ...(formData.password ? { password: formData.password } : {}),
        })
      } else {
        await userApi.create(formData)
      }
      loadUsers()
      setShowDialog(false)
    } catch (err: any) {
      alert(err.response?.data?.detail || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!deletingUser) return
    setDeleteLoading(true)
    try {
      await userApi.delete(deletingUser.id)
      loadUsers()
      setDeletingUser(null)
    } catch (err: any) {
      alert(err.response?.data?.detail || '删除失败')
    } finally {
      setDeleteLoading(false)
    }
  }

  const handleRestore = async (user: User) => {
    try {
      await userApi.update(user.id, { is_active: true })
      loadUsers()
    } catch (err: any) {
      alert(err.response?.data?.detail || '恢复失败')
    }
  }

  // 搜索过滤
  const filteredUsers = users.filter(u => {
    if (!searchQuery) return true
    const query = searchQuery.toLowerCase()
    return (
      u.username.toLowerCase().includes(query) ||
      u.real_name.toLowerCase().includes(query)
    )
  })

  // 权限守卫放在所有 Hooks 之后，避免用户状态加载过程中改变 Hooks 顺序。
  if (!canManage) {
    return <Navigate to="/projects" replace />
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">用户管理</h1>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <Switch
              id="show-deleted"
              checked={showDeleted}
              onCheckedChange={setShowDeleted}
            />
            <Label htmlFor="show-deleted" className="cursor-pointer">显示已删除用户</Label>
          </div>
          <Button onClick={openCreateDialog}>
            <Plus className="w-4 h-4 mr-2" />
            添加用户
          </Button>
        </div>
      </div>

      {/* 搜索框 */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
        <Input
          placeholder="搜索用户名或真实姓名..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="pl-9 pr-9"
        />
        {searchQuery && (
          <button
            onClick={() => setSearchQuery('')}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      <div className="border rounded-lg">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>用户名</TableHead>
              <TableHead>真实姓名</TableHead>
              <TableHead>角色</TableHead>
              <TableHead>状态</TableHead>
              <TableHead>创建时间</TableHead>
              <TableHead className="w-[120px]">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={6} className="text-center py-8">
                  加载中...
                </TableCell>
              </TableRow>
            ) : filteredUsers.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
                  {searchQuery ? '未找到匹配的用户' : '暂无用户'}
                </TableCell>
              </TableRow>
            ) : (
              filteredUsers.map((u) => (
                <TableRow key={u.id}>
                  <TableCell className="font-mono">{u.username}</TableCell>
                  <TableCell>{u.real_name}</TableCell>
                  <TableCell>
                    <Badge variant="outline">{ROLE_LABELS[u.role] || u.role}</Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant={u.is_active ? 'success' : 'destructive'}>
                      {u.is_active ? '启用' : '禁用'}
                    </Badge>
                  </TableCell>
                  <TableCell>{new Date(u.created_at).toLocaleDateString('zh-CN')}</TableCell>
                  <TableCell>
                    {u.is_active ? (
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => openEditDialog(u)}
                        >
                          <Edit className="w-4 h-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => setDeletingUser(u)}
                          className="text-red-600 hover:text-red-700"
                        >
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      </div>
                    ) : (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleRestore(u)}
                        className="text-green-600 hover:text-green-700"
                      >
                        <RotateCcw className="w-4 h-4 mr-1" />
                        恢复
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* 新增/编辑弹窗 */}
      <Dialog open={showDialog} onOpenChange={setShowDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingUser ? '编辑用户' : '添加用户'}</DialogTitle>
            <DialogDescription>
              {editingUser ? '修改用户信息' : '创建新的系统用户'}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label>用户名</Label>
              <Input
                value={formData.username}
                onChange={(e) => setFormData(prev => ({ ...prev, username: e.target.value }))}
                disabled={!!editingUser}
                required
              />
            </div>
            <div className="space-y-2">
              <Label>{editingUser ? '新密码（留空不修改）' : '密码'}</Label>
              <Input
                type="password"
                value={formData.password}
                onChange={(e) => setFormData(prev => ({ ...prev, password: e.target.value }))}
                required={!editingUser}
              />
            </div>
            <div className="space-y-2">
              <Label>真实姓名</Label>
              <Input
                value={formData.real_name}
                onChange={(e) => setFormData(prev => ({ ...prev, real_name: e.target.value }))}
                required
              />
            </div>
            <div className="space-y-2">
              <Label>角色</Label>
              <Select
                value={formData.role}
                onValueChange={(v) => setFormData(prev => ({ ...prev, role: v }))}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="admin">管理人员</SelectItem>
                  <SelectItem value="practitioner">执业人员</SelectItem>
                  <SelectItem value="admin_staff">后勤行政</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setShowDialog(false)}>
                取消
              </Button>
              <Button type="submit" disabled={saving}>
                {saving && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
                保存
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* 删除确认弹窗 */}
      <Dialog open={!!deletingUser} onOpenChange={() => setDeletingUser(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认删除</DialogTitle>
            <DialogDescription>
              确定要删除用户「{deletingUser ? getUserDisplayName(deletingUser) : ''}」吗？删除后该用户将无法登录。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeletingUser(null)}>
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
