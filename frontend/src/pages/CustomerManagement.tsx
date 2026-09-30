import { useEffect, useState } from 'react'
import { customerApi } from '@/api/auth'
import type { Customer } from '@/types'
import { useAuth } from '@/store/AuthContext'
import { Navigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Plus, Edit } from 'lucide-react'

export default function CustomerManagement() {
  const { user } = useAuth()
  const [customers, setCustomers] = useState<Customer[]>([])
  const [search, setSearch] = useState('')
  const [taxId, setTaxId] = useState('')
  const [name, setName] = useState('')
  const [editing, setEditing] = useState<Customer | null>(null)
  const [error, setError] = useState('')

  const load = async () => {
    const response = await customerApi.list(search || undefined)
    setCustomers(response.data)
  }
  useEffect(() => { load().catch(() => setError('无法加载客户')) }, [])

  if (user?.role !== 'admin') return <Navigate to="/projects" replace />

  const save = async (event: React.FormEvent) => {
    event.preventDefault(); setError('')
    try {
      if (editing) await customerApi.update(editing.id, { name: name.trim() })
      else await customerApi.create({ tax_id: taxId.trim(), name: name.trim() })
      setEditing(null); setTaxId(''); setName(''); await load()
    } catch (err: any) { setError(err.response?.data?.detail || '保存失败') }
  }

  return <div className="space-y-4 max-w-5xl">
    <div><h1 className="text-2xl font-bold">客户管理</h1><p className="text-sm text-muted-foreground mt-1">以统一社会信用代码或税号锁定客户主体，名称变更会保留历史项目名称。</p></div>
    {error && <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
    <form onSubmit={save} className="grid gap-3 rounded-lg border bg-card p-4 md:grid-cols-[1fr_1fr_auto]">
      <div className="space-y-1"><Label>税号</Label><Input value={taxId} disabled={!!editing} onChange={e => setTaxId(e.target.value)} required={!editing} /></div>
      <div className="space-y-1"><Label>公司名称</Label><Input value={name} onChange={e => setName(e.target.value)} required /></div>
      <div className="flex items-end gap-2"><Button type="submit">{editing ? '保存更名' : <><Plus className="mr-2 h-4 w-4" />新增客户</>}</Button>{editing && <Button type="button" variant="outline" onClick={() => { setEditing(null); setTaxId(''); setName('') }}>取消</Button>}</div>
    </form>
    <div className="flex gap-2"><Input placeholder="搜索公司名称或税号" value={search} onChange={e => setSearch(e.target.value)} onKeyDown={e => e.key === 'Enter' && load()} /><Button variant="outline" onClick={load}>搜索</Button></div>
    <div className="rounded-lg border"><Table><TableHeader><TableRow><TableHead>税号</TableHead><TableHead>当前公司名称</TableHead><TableHead>操作</TableHead></TableRow></TableHeader><TableBody>{customers.map(customer => <TableRow key={customer.id}><TableCell className="font-mono">{customer.tax_id}</TableCell><TableCell>{customer.name}</TableCell><TableCell><Button size="icon" variant="ghost" title="修改名称" onClick={() => { setEditing(customer); setTaxId(customer.tax_id); setName(customer.name) }}><Edit className="h-4 w-4" /></Button></TableCell></TableRow>)}</TableBody></Table></div>
  </div>
}
