import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { customerApi } from '@/api/auth'
import { can, type Customer } from '@/types'
import { useAuth } from '@/store/AuthContext'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Plus, Edit, Check, X, ChevronLeft, ChevronRight, Power } from 'lucide-react'

export default function CustomerManagement() {
  const { user } = useAuth()
  const manage = can(user, 'customer.manage')
  const [customers, setCustomers] = useState<(Partial<Customer> & {id: number; name: string; tax_id_masked?: string | null})[]>([])
  const [requests, setRequests] = useState<any[]>([])
  const [search, setSearch] = useState('')
  const [taxId, setTaxId] = useState('')
  const [name, setName] = useState('')
  const [type, setType] = useState<Customer['type']>('enterprise')
  const [reason, setReason] = useState('')
  const [editing, setEditing] = useState<Customer | null>(null)
  const [error, setError] = useState('')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [cursor, setCursor] = useState(0)
  const [nextCursor, setNextCursor] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)
  const [view, setView] = useState('directory')

  const load = async () => {
    if (can(user, 'customer.read.all')) {
      const response = await customerApi.list(search || undefined, page, true)
      setCustomers(response.data.items); setTotal(response.data.total)
    } else if (search.trim().length >= 2) {
      const response = await customerApi.lookup(search.trim(), cursor)
      setCustomers(response.data.items); setNextCursor(response.data.next_cursor)
    } else { setCustomers([]); setNextCursor(null) }
  }
  useEffect(() => {
    const timeout = window.setTimeout(() => { load().catch((e: any) => setError(e.userMessage || e.response?.data?.detail || '无法加载客户')) }, 300)
    return () => window.clearTimeout(timeout)
  }, [search, page, cursor, user?.id])
  useEffect(() => { customerApi.requests().then(res => setRequests(res.data.items)).catch(() => undefined) }, [view])
  useEffect(() => {
    const guard = (e: BeforeUnloadEvent) => { if (name || taxId) { e.preventDefault(); e.returnValue = '' } }
    window.addEventListener('beforeunload', guard)
    return () => window.removeEventListener('beforeunload', guard)
  }, [name, taxId])

  const clear = () => { setEditing(null); setTaxId(''); setName(''); setReason('') }
  const save = async (event: React.FormEvent) => {
    event.preventDefault(); setError(''); setSaving(true)
    try {
      if (manage && editing) await customerApi.update(editing.id, { name: name.trim(), tax_id: taxId.trim() || null, expected_revision: editing.revision, reason })
      else if (manage) await customerApi.create({ tax_id: taxId.trim() || null, name: name.trim(), type })
      else await customerApi.propose({kind: editing ? 'update' : 'create', customer_id: editing?.id, expected_customer_revision: editing?.revision, proposal: {name: name.trim(), tax_id: taxId.trim() || null, type}, reason})
      clear(); await load()
    } catch (err: any) { setError(err.userMessage || err.response?.data?.detail || '保存失败，草稿已保留') }
    finally { setSaving(false) }
  }
  const confirm = async (customer: Customer) => {
    const note = window.prompt('主体核验依据')
    if (!note?.trim()) return
    try {
      const proposed = await customerApi.propose({kind: 'confirm', customer_id: customer.id, expected_customer_revision: customer.revision, proposal: {name: customer.name, tax_id: customer.tax_id, type: customer.type}, reason: note})
      await customerApi.review(proposed.data.id, proposed.data.revision, 'approve', note)
      await load()
    } catch (err: any) { setError(err.userMessage || err.response?.data?.detail || '核验失败') }
  }
  const review = async (item: any, decision: string) => {
    const note = window.prompt('审核说明')
    if (!note?.trim()) return
    try { await customerApi.review(item.id, item.revision, decision, note); setRequests((await customerApi.requests()).data.items); await load() }
    catch (err: any) { setError(err.userMessage || err.response?.data?.detail || '审核失败') }
  }

  return <div className="space-y-4 max-w-5xl">
    <h1 className="text-2xl font-bold">客户管理</h1>
    <div className="flex gap-4 border-b text-sm"><button className="py-2" onClick={() => setView('directory')}>客户目录</button><button className="py-2" onClick={() => setView('requests')}>主体申请</button></div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <form onSubmit={save} className="grid gap-3 border-b pb-4 md:grid-cols-2">
      <div className="space-y-1"><Label>主体类型</Label><select className="h-10 w-full border rounded-md bg-white px-3" value={type} disabled={!!editing} onChange={e => setType(e.target.value as Customer['type'])}><option value="enterprise">企业</option><option value="individual">个人</option><option value="overseas">境外</option></select></div>
      <div className="space-y-1"><Label>客户名称</Label><Input maxLength={200} value={name} onChange={e => setName(e.target.value)} required /></div>
      <div className="space-y-1"><Label>税号 / 标识</Label><Input maxLength={50} value={taxId} disabled={!!editing && !can(user, 'customer.correct')} onChange={e => setTaxId(e.target.value)} /></div>
      <div className="space-y-1"><Label>申请 / 变更原因</Label><Input maxLength={500} value={reason} onChange={e => setReason(e.target.value)} required={!manage || !!editing} /></div>
      <div className="flex gap-2"><Button disabled={saving}><Plus className="mr-2 h-4 w-4" />{editing ? '保存变更' : manage ? '新增待核验客户' : '提交主体申请'}</Button>{editing && <Button type="button" variant="outline" onClick={clear}>取消</Button>}</div>
    </form>
    {view === 'directory' ? <>
      <Input placeholder="按客户名称搜索" value={search} onChange={e => {setSearch(e.target.value); setPage(1); setCursor(0)}} />
      <div className="overflow-x-auto border rounded-md"><Table className="min-w-[640px]"><TableHeader><TableRow><TableHead>客户名称</TableHead><TableHead>税号 / 标识</TableHead><TableHead>主体状态</TableHead><TableHead>操作</TableHead></TableRow></TableHeader><TableBody>{customers.map(customer => <TableRow key={customer.id}><TableCell><Link className="text-primary hover:underline" to={`/customers/${customer.id}`}>{customer.name}</Link></TableCell><TableCell className="font-mono">{customer.tax_id_masked ?? customer.tax_id ?? '-'}</TableCell><TableCell>{customer.identity_status === 'confirmed' ? '已确认' : customer.identity_status === 'merged' ? '已合并' : '待核验'}{customer.is_active === false && ' / 停用'}</TableCell><TableCell><div className="flex gap-1">{manage && <>
        <Button size="icon" variant="ghost" title="编辑客户" onClick={() => {const c = customer as Customer; setEditing(c); setTaxId(c.tax_id || ''); setName(c.name); setType(c.type)}}><Edit className="h-4 w-4" /></Button>
        {customer.identity_status === 'pending' && <Button size="icon" variant="ghost" title="确认主体" onClick={() => confirm(customer as Customer)}><Check className="h-4 w-4" /></Button>}
        <Button size="icon" variant="ghost" title={customer.is_active ? '停用客户' : '启用客户'} onClick={async () => {try {await customerApi.update(customer.id, {is_active: !customer.is_active, expected_revision: customer.revision!}); await load()} catch(e: any) {setError(e.userMessage || e.response?.data?.detail || '操作失败')}}}><Power className="h-4 w-4" /></Button>
      </>}</div></TableCell></TableRow>)}</TableBody></Table></div>
      <div className="flex items-center justify-between">{can(user, 'customer.read.all') ? <><span className="text-sm">共 {total} 项</span><div className="flex gap-2"><Button title="上一页" size="icon" variant="outline" disabled={page === 1} onClick={() => setPage(page-1)}><ChevronLeft /></Button><Button title="下一页" size="icon" variant="outline" disabled={page*20 >= total} onClick={() => setPage(page+1)}><ChevronRight /></Button></div></> : nextCursor && <Button onClick={() => setCursor(nextCursor)}>下一页<ChevronRight className="ml-2 h-4 w-4" /></Button>}</div>
    </> : <div className="overflow-x-auto border rounded-md"><Table className="min-w-[640px]"><TableHeader><TableRow><TableHead>申请编号</TableHead><TableHead>客户</TableHead><TableHead>状态</TableHead><TableHead>原因</TableHead><TableHead>审核</TableHead></TableRow></TableHeader><TableBody>{requests.map(item => <TableRow key={item.id}><TableCell>{item.id}</TableCell><TableCell>{item.customer_id ? <Link className="text-primary hover:underline" to={`/customers/${item.customer_id}`}>{item.proposal.name}</Link> : item.proposal.name}</TableCell><TableCell>{item.status}</TableCell><TableCell>{item.reason}</TableCell><TableCell>{manage && item.status === 'submitted' && <div className="flex gap-1"><Button title="通过" size="icon" variant="ghost" onClick={() => review(item, 'approve')}><Check /></Button><Button title="拒绝" size="icon" variant="ghost" onClick={() => review(item, 'reject')}><X /></Button></div>}</TableCell></TableRow>)}</TableBody></Table></div>}
  </div>
}
