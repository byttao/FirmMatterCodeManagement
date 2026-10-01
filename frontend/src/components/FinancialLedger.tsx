import { useEffect, useRef, useState } from 'react'
import { billingLabels, billingValue, localDate } from '@/lib/billing'
import { Plus, Ban, Eye, ChevronLeft, ChevronRight } from 'lucide-react'
import { financeApi, projectApi, billingApi, requestKey } from '@/api/auth'
import type { FinanceKind, FinancialEntry, FinancialEntryInput, Project } from '@/types'
import { useAuth } from '@/store/AuthContext'
import { formatCurrency } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { MoneyInput } from '@/components/ui/money-input'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

interface Props {project: Project; canEdit: boolean; onProjectChange: (project: Project) => void}

export function FinancialLedger({project, canEdit, onProjectChange}: Props) {
  const { user } = useAuth()
  const readEntries = !!user?.permissions.includes('finance.read.all')
  const [records, setRecords] = useState<Record<FinanceKind, {items: FinancialEntry[]; total: number}>>({invoices:{items:[],total:0},receipts:{items:[],total:0}})
  const [pages, setPages] = useState({invoices:1,receipts:1})
  const [kind, setKind] = useState<FinanceKind | null>(null)
  const [form, setForm] = useState<FinancialEntryInput>({amount:0,occurred_on:'',expected_project_revision:project.revision})
  const [profiles, setProfiles] = useState<any[]>([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [snapshot, setSnapshot] = useState<any>(null)
  const pending = useRef<{payload: string; key: string} | null>(null)
  const load = async () => {
    const [invoices, receipts] = await Promise.all([financeApi.list(project.id,'invoices',pages.invoices), financeApi.list(project.id,'receipts',pages.receipts)])
    setRecords({invoices:invoices.data,receipts:receipts.data})
  }
  useEffect(()=>{if(readEntries)load().catch((e:any)=>setError(e.response?.data?.detail||'无法加载财务记录'))},[project.id,readEntries,pages])
  const refresh = async () => {await load(); onProjectChange((await projectApi.get(project.id)).data)}
  const open = async (selected: FinanceKind, replacement?: FinancialEntry) => {
    setError(''); pending.current=null
    setForm({amount:replacement?.amount||0, occurred_on:localDate(), reference:'',note:'',expected_project_revision:project.revision,replacement_of_id:replacement?.id})
    if(selected==='invoices') {
      try{setProfiles((await billingApi.profiles(project.customer_id)).data)}catch(e:any){setError(e.response?.data?.detail||'无法加载开票档案')}
    }
    setKind(selected)
  }
  const save = async () => {
    if(!kind || saving || !form.occurred_on || form.amount<=0) return
    setSaving(true)
    try {
      const payload=JSON.stringify(form)
      if(pending.current?.payload!==payload)pending.current={payload,key:requestKey()}
      await financeApi.create(project.id,kind,form,pending.current!.key)
      await refresh(); setKind(null); pending.current=null
    }catch(e:any){setError(e.response?.data?.detail||'登记失败，草稿已保留')}
    finally{setSaving(false)}
  }
  const voidEntry = async (selected: FinanceKind, entry: FinancialEntry) => {
    const reason=window.prompt('登记作废原因（税务平台作废或红冲须另行办理）')
    if(!reason?.trim())return
    try{await financeApi.void(project.id,selected,entry.id,entry.revision,reason); await refresh()}catch(e:any){setError(e.response?.data?.detail||'作废失败')}
  }
  const showSnapshot = async (entry: FinancialEntry) => {
    try{setSnapshot((await financeApi.snapshot(project.id,entry.id)).data)}catch(e:any){setError(e.response?.data?.detail||'无法读取历史快照')}
  }
  return <div className="space-y-5">
    <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-sm">{[['合同金额',project.contract_amount],['已开票',project.invoiced_amount],['未开票',project.uninvoiced_amount],['已收款',project.received_amount],['未收款',project.unreceived_amount]].map(([label,value])=><div key={String(label)}><p className="text-muted-foreground">{label}</p><strong>{formatCurrency(value as number|null)}</strong></div>)}</div>
    {error&&<p role="alert" className="text-sm text-destructive">{error}</p>}
    {readEntries&&(['invoices','receipts'] as FinanceKind[]).map(selected=><section key={selected} className="space-y-2"><div className="flex justify-between items-center"><h3 className="font-medium">{selected==='invoices'?'开票记录':'收款记录'}</h3>{canEdit&&<Button type="button" size="sm" variant="outline" onClick={()=>open(selected)}><Plus className="mr-2 h-4 w-4" />登记</Button>}</div><div className="border rounded-md overflow-x-auto"><Table className="min-w-[640px]"><TableHeader><TableRow><TableHead>日期</TableHead><TableHead>金额</TableHead><TableHead>凭证</TableHead><TableHead>备注 / 作废原因</TableHead><TableHead>状态</TableHead><TableHead>操作</TableHead></TableRow></TableHeader><TableBody>{records[selected].items.map(entry=><TableRow key={entry.id}><TableCell>{entry.occurred_on}</TableCell><TableCell>{formatCurrency(entry.amount)}</TableCell><TableCell>{entry.reference}</TableCell><TableCell>{entry.note}{entry.void_reason&&<p className="text-destructive">{entry.void_reason}</p>}</TableCell><TableCell>{entry.voided_at?'已作废':'有效'}</TableCell><TableCell><div className="flex gap-1">{selected==='invoices'&&<Button type="button" size="icon" title="历史开票快照" variant="ghost" onClick={()=>showSnapshot(entry)}><Eye className="h-4 w-4" /></Button>}{canEdit&&!entry.voided_at&&<Button type="button" size="icon" title="作废登记" variant="ghost" onClick={()=>voidEntry(selected,entry)}><Ban className="h-4 w-4" /></Button>}{canEdit&&entry.voided_at&&<Button type="button" size="icon" title="登记替换记录" variant="ghost" onClick={()=>open(selected,entry)}><Plus className="h-4 w-4" /></Button>}</div></TableCell></TableRow>)}</TableBody></Table></div><div className="flex justify-between items-center text-sm"><span>共 {records[selected].total} 项</span><div className="flex gap-1"><Button type="button" size="icon" title="上一页" variant="ghost" disabled={pages[selected]===1} onClick={()=>setPages({...pages,[selected]:pages[selected]-1})}><ChevronLeft /></Button><Button type="button" size="icon" title="下一页" variant="ghost" disabled={pages[selected]*50>=records[selected].total} onClick={()=>setPages({...pages,[selected]:pages[selected]+1})}><ChevronRight /></Button></div></div></section>)}
    <Dialog open={!!kind} onOpenChange={open=>{if(!open&&window.confirm('关闭未登记草稿？'))setKind(null)}}><DialogContent><DialogHeader><DialogTitle>{kind==='invoices'?'登记开票':'登记收款'}</DialogTitle></DialogHeader><form className="space-y-3" onSubmit={e=>{e.preventDefault();e.stopPropagation();save()}}><div><Label>金额</Label><MoneyInput value={form.amount} onChange={amount=>setForm({...form,amount})} /></div><div><Label>日期</Label><Input type="date" required value={form.occurred_on||''} onChange={e=>setForm({...form,occurred_on:e.target.value})} /></div><div><Label>凭证号</Label><Input maxLength={100} value={form.reference||''} onChange={e=>setForm({...form,reference:e.target.value})} /></div><div><Label>备注</Label><Input maxLength={500} value={form.note||''} onChange={e=>setForm({...form,note:e.target.value})} /></div>{kind==='invoices'&&<div><Label>已确认开票档案</Label><select required className="w-full h-10 border rounded-md bg-white px-2" value={form.billing_profile_id||''} onChange={e=>{const profile=profiles.find(p=>p.id===Number(e.target.value));setForm({...form,billing_profile_id:profile?.id,billing_version_id:profile?.current_verified_version_id,expected_profile_revision:profile?.revision})}}><option value="">选择档案与当前确认版本</option>{profiles.filter(p=>p.is_active&&p.current_verified_version_id).map(p=><option key={p.id} value={p.id}>{p.label} · V{p.versions.find((v:any)=>v.id===p.current_verified_version_id)?.version_no}</option>)}</select></div>}{error&&<p className="text-sm text-destructive">{error}</p>}<DialogFooter><Button disabled={saving||!form.amount||kind==='invoices'&&!form.billing_version_id}>登记</Button></DialogFooter></form></DialogContent></Dialog>
    <Dialog open={!!snapshot} onOpenChange={open=>{if(!open)setSnapshot(null)}}><DialogContent className="max-h-[90vh] overflow-y-auto"><DialogHeader><DialogTitle>历史开票快照 · V{snapshot?.fields.version_no}</DialogTitle></DialogHeader><dl className="space-y-2 text-sm">{snapshot&&Object.entries(snapshot.fields).map(([key,value])=><div key={key} className="grid grid-cols-2 gap-2"><dt className="text-muted-foreground">{billingLabels[key]||'资料'}</dt><dd className="break-all">{billingValue(key,value)}</dd></div>)}</dl></DialogContent></Dialog>
  </div>
}
