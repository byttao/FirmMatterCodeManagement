import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { customerApi, projectApi } from '@/api/auth'
import { useAuth } from '@/store/AuthContext'
import { can, type Project } from '@/types'
import BillingPanel from '@/components/BillingPanel'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ArrowLeft, Merge } from 'lucide-react'

export default function CustomerDetail() {
  const { customerId } = useParams()
  const { user } = useAuth()
  const navigate = useNavigate()
  const [customer, setCustomer] = useState<any>(null)
  const [tab, setTab] = useState('basic')
  const [error, setError] = useState('')
  const [changes, setChanges] = useState<any[]>([])
  const [projects, setProjects] = useState<Project[]>([])
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [mergeOpen, setMergeOpen] = useState(false)
  const [targetId, setTargetId] = useState('')
  const [reason, setReason] = useState('')
  const [checked, setChecked] = useState(false)
  const [preview, setPreview] = useState<any>(null)
  const [saving, setSaving] = useState(false)
  useEffect(()=>{setCustomer(null); customerApi.get(Number(customerId)).then(r=>setCustomer(r.data)).catch((e:any)=>setError(e.response?.data?.detail||'客户不可读'))},[customerId])
  useEffect(()=>{
    if(tab==='changes')customerApi.changes(Number(customerId)).then(r=>setChanges(r.data)).catch((e:any)=>setError(e.response?.data?.detail||'无法加载历史'))
    if(tab==='projects')projectApi.list({customer_id:Number(customerId),page,page_size:20}).then(r=>{setProjects(r.data.items);setTotal(r.data.total)}).catch((e:any)=>setError(e.response?.data?.detail||'无法加载项目'))
  },[tab,customerId,page])
  const merge = async (dryRun: boolean) => {
    setSaving(true);setError('')
    try{
      const target=dryRun ? (await customerApi.get(Number(targetId))).data : preview.target
      const result=await customerApi.merge(customer.id,{target_id:target.id,expected_revision:customer.revision,expected_target_revision:target.revision,reason,identity_checked:checked,dry_run:dryRun})
      if(dryRun)setPreview(result.data)
      else navigate(`/customers/${target.id}`)
    }catch(e:any){setError(e.response?.data?.detail||'合并失败，输入已保留')}
    finally{setSaving(false)}
  }
  return <div className="max-w-6xl space-y-4">
    <Button variant="ghost" onClick={()=>navigate('/customers')}><ArrowLeft className="mr-2 h-4 w-4" />客户目录</Button>
    {error&&<p role="alert" className="text-sm text-destructive">{error}</p>}
    {customer&&<><div className="flex flex-wrap justify-between gap-3"><h1 className="text-2xl font-semibold break-all">{customer.name}</h1>{can(user,'customer.merge')&&customer.is_active&&<Button variant="outline" onClick={()=>setMergeOpen(!mergeOpen)}><Merge className="mr-2 h-4 w-4" />合并主体</Button>}</div>
      <nav className="flex flex-wrap gap-5 border-b text-sm">{[['basic','基础资料'],...(customer.billing_access?[['billing','开票资料']]:[]),...(customer.full_read?[['changes','变更记录'],['projects','可见项目']]:[])].map(([value,label])=><button key={value} className={`py-2 border-b-2 ${tab===value?'border-primary font-medium':'border-transparent'}`} onClick={()=>{setTab(value);setError('')}}>{label}</button>)}</nav>
      {tab==='basic'&&<dl className="grid sm:grid-cols-2 gap-4 text-sm">{[['主体类型',({enterprise:'企业',individual:'个人',overseas:'境外'} as Record<string,string>)[customer.type]],['税号 / 标识',customer.tax_id||'未登记'],['核验状态',customer.identity_status==='confirmed'?'已确认':customer.identity_status==='merged'?'已合并':'待核验'],['使用状态',customer.is_active?'启用':'停用']].map(([label,value])=><div key={label}><dt className="text-muted-foreground">{label}</dt><dd className="mt-1 break-all">{value}</dd></div>)}{customer.merged_into_id&&<Link to={`/customers/${customer.merged_into_id}`}>查看保留主体</Link>}</dl>}
      {tab==='billing'&&customer.billing_access&&<BillingPanel customerId={customer.id} />}
      {tab==='changes'&&<div className="divide-y">{changes.map((item,i)=><div key={i} className="py-3 text-sm"><p>{item.reason||item.action}</p><p className="text-muted-foreground">操作人 #{item.actor_id} · {new Date(item.created_at+'Z').toLocaleString('zh-CN')}</p></div>)}</div>}
      {tab==='projects'&&<><div className="divide-y">{projects.map(p=><Link key={p.id} to={`/projects/${p.id}`} className="block py-3 text-sm">{p.project_id} · {p.report_no||'未编号'} · {p.customer_name}</Link>)}</div><div className="flex justify-between items-center"><span className="text-sm">共 {total} 项</span><div className="flex gap-2"><Button variant="outline" disabled={page===1} onClick={()=>setPage(page-1)}>上一页</Button><Button variant="outline" disabled={page*20>=total} onClick={()=>setPage(page+1)}>下一页</Button></div></div></>}
      {mergeOpen&&<section className="border-t pt-4 space-y-3"><h2 className="font-semibold">合并到保留主体</h2><Label>保留客户编号</Label><Input type="number" min="1" value={targetId} onChange={e=>{setTargetId(e.target.value);setPreview(null)}} /><Label>合并原因</Label><Input maxLength={500} value={reason} onChange={e=>{setReason(e.target.value);setPreview(null)}} /><label className="flex gap-2 text-sm"><input type="checkbox" checked={checked} onChange={e=>{setChecked(e.target.checked);setPreview(null)}} />已核对双方属于同一主体</label>{preview&&<div className="text-sm space-y-1"><p>{preview.source.name}（{preview.source.tax_id||'无税号'}） → {preview.target.name}（{preview.target.tax_id||'无税号'}）</p><p>转移 {preview.project_count} 个项目，保留 {preview.billing_profile_count} 个原开票档案及历史快照。</p></div>}<Button disabled={saving||!checked||!reason.trim()||!targetId} onClick={()=>merge(!preview)}>{preview?'确认执行合并':'预览影响'}</Button></section>}
    </>}
  </div>
}
