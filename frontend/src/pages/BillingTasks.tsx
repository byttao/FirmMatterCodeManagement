import { useEffect, useRef, useState } from 'react'
import { billingApi, billingTaskApi, projectApi, requestKey } from '@/api/auth'
import { useAuth } from '@/store/AuthContext'
import { can } from '@/types'
import { billingLabels, billingValue, localDate } from '@/lib/billing'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { MoneyInput } from '@/components/ui/money-input'

const statuses: Record<string,string> = {assigned:'待办理',result_submitted:'待财务确认',completed:'已完成',revoked:'已撤回',needs_review:'需重新核对'}
const message = (e: any) => e.userMessage || e.response?.data?.detail?.message || '未获得响应；写入结果请刷新核对，再决定是否重试'
const writeMessage = (e: any) => !e.response || e.response.status>=500 ? message(e)+'；本次写入结果待核对，请刷新确认，勿盲目重复执行' : message(e)

export default function BillingTasks() {
  const {user} = useAuth()
  const manage = can(user,'billing_task.manage')
  const submit = can(user,'billing_task.submit.assigned')
  const [items,setItems] = useState<any[]>([])
  const [page,setPage] = useState(1)
  const [status,setStatus] = useState('')
  const [total,setTotal] = useState(0)
  const [selected,setSelected] = useState<any>(null)
  const [sensitive,setSensitive] = useState<any>(null)
  const [error,setError] = useState('')
  const [notice,setNotice] = useState('')
  const [busy,setBusy] = useState(false)
  const [assignees,setAssignees] = useState<any[]>([])
  const [search,setSearch] = useState('')
  const [projects,setProjects] = useState<any[]>([])
  const [project,setProject] = useState<any>(null)
  const [profiles,setProfiles] = useState<any[]>([])
  const [reviewProfiles,setReviewProfiles] = useState<any[]>([])
  const [form,setForm] = useState({profile:'',assignee:'',amount:'',note:''})
  const [reason,setReason] = useState('')
  const [newAssignee,setNewAssignee] = useState('')
  const [newProfile,setNewProfile] = useState('')
  const [historical,setHistorical] = useState(false)
  const [existingEntry,setExistingEntry] = useState('')
  const [result,setResult] = useState({invoice_number:'',invoice_date:localDate(),note:''})
  const pending = useRef<{signature:string;key:string}|null>(null)
  const pendingConfirmation = useRef<{signature:string;key:string;data:Record<string,unknown>}|null>(null)
  const selectedRef = useRef<any>(null)
  selectedRef.current = selected
  const keyFor = (value: unknown) => {
    const signature=JSON.stringify(value)
    if(pending.current?.signature!==signature)pending.current={signature,key:requestKey()}
    return pending.current!.key
  }
  const refresh = async () => {
    const response = await billingTaskApi.list(page,status)
    setItems(response.data.items);setTotal(response.data.total)
  }
  useEffect(()=>{
    let active=true
    billingTaskApi.list(page,status).then(r=>{if(active){setItems(r.data.items);setTotal(r.data.total)}}).catch(e=>{if(active)setError(message(e))})
    return()=>{active=false}
  },[page,status])
  useEffect(()=>{
    let active=true
    if(manage)billingTaskApi.assignees().then(r=>{if(active)setAssignees(r.data)}).catch(e=>{if(active)setError(message(e))})
    return()=>{active=false}
  },[manage])
  const selectedId=selected?.id
  useEffect(()=>{
    if(!selectedId)return
    let active=true,inFlight=false
    const check=async()=>{
      if(inFlight || document.hidden)return
      inFlight=true
      try{
        const r=await billingTaskApi.get(selectedId)
        if(active){
          if(selectedRef.current?.revision!==r.data.revision || r.data.status!=='assigned')setSensitive(null)
          setSelected(r.data)
        }
      }catch(e){if(active){setSensitive(null);setSelected(null);setError(message(e))}}
      finally{inFlight=false}
    }
    const timer=window.setInterval(check,5000)
    return()=>{active=false;window.clearInterval(timer)}
  },[selectedId])
  const choose=async(item: any)=>{
    setBusy(true);setSensitive(null);setError('');setNotice('');setHistorical(false);setExistingEntry('');setReason('')
    try{
      const r=await billingTaskApi.get(item.id);setSelected(r.data)
      setResult({invoice_number:'',invoice_date:localDate(),note:''})
      if(manage){const p=await projectApi.get(r.data.project_id);setReviewProfiles((await billingApi.profiles(p.data.customer_id!)).data)}
    }catch(e){setSelected(null);setError(message(e))}finally{setBusy(false)}
  }
  const run=async(action: string, data: Record<string,unknown>, keyed=false)=>{
    if(!selected || busy)return
    setBusy(true);setError('');setNotice('');setSensitive(null)
    try{
      const r=await billingTaskApi.action(selected.id,action,data,keyed ? keyFor([selected.id,action,data]) : undefined)
      if(action==='reveal')setSensitive(r.data)
      else{setSelected(r.data);pending.current=null;setNotice(action==='submit-result'?'已提交，待财务确认；尚未登记流水':'操作已完成');await refresh().catch(e=>setError('操作已完成，但列表刷新失败：'+message(e)))}
    }catch(e){setError(action==='reveal'?message(e):writeMessage(e))}finally{setBusy(false)}
  }
  const findProject=async()=>{
    setBusy(true);setError('')
    try{setProjects((await projectApi.list({search,page_size:20})).data.items)}catch(e){setError(message(e))}finally{setBusy(false)}
  }
  const selectProject=async(id: string)=>{
    setBusy(true);setError('')
    try{
      const p=projects.find(p=>String(p.id)===id);setProject(p);setForm({...form,profile:''})
      setProfiles(p?.customer_id ? (await billingApi.profiles(p.customer_id)).data : [])
    }catch(e){setError(message(e))}finally{setBusy(false)}
  }
  const create=async()=>{
    const profile=profiles.find(p=>String(p.id)===form.profile)
    if(!project || !profile)return
    const data={project_id:project.id,customer_id:project.customer_id,billing_profile_id:profile.id,billing_version_id:profile.current_verified_version_id,assignee_id:Number(form.assignee),amount:form.amount,note:form.note}
    setBusy(true);setError('')
    try{const r=await billingTaskApi.create(data,keyFor(['create',data]));pending.current=null;setSelected(r.data);setSensitive(null);setNotice('已分配开票办理任务');await refresh().catch(e=>setError('任务已创建，但列表刷新失败：'+message(e)))}catch(e){setError(writeMessage(e))}finally{setBusy(false)}
  }
  const confirm=async()=>{
    if(!selected || !reason.trim() || busy)return
    setBusy(true);setError('');setSensitive(null)
    try{
      const signature=JSON.stringify([selected.id,selected.revision,reason,historical,existingEntry])
      if(pendingConfirmation.current?.signature!==signature){
        const p=await projectApi.get(selected.project_id)
        const data={expected_revision:selected.revision,expected_project_revision:p.data.revision,reason,confirm_historical:historical,financial_entry_id:existingEntry ? Number(existingEntry) : null}
        pendingConfirmation.current={signature,key:requestKey(),data}
      }
      const action=pendingConfirmation.current!
      const r=await billingTaskApi.action(selected.id,'confirm',action.data,action.key)
      setSelected(r.data);pendingConfirmation.current=null;setNotice('财务已确认，任务与流水已关联');await refresh().catch(e=>setError('财务已确认，但列表刷新失败：'+message(e)))
    }catch(e){setError(writeMessage(e))}finally{setBusy(false)}
  }
  const copy=async()=>{
    try{if(!navigator.clipboard)throw new Error();await navigator.clipboard.writeText(sensitive.copy_text);setNotice('已复制')}
    catch{setNotice('浏览器未完成自动复制，请选中下方文本并使用 Ctrl+C 手动复制')}
  }
  if(!can(user,'billing_task.read.all') && !can(user,'billing_task.read.assigned'))return <p>无权查看开票办理任务。</p>
  return <div className="max-w-6xl space-y-4">
    <h1 className="text-2xl font-semibold">{manage?'开票办理任务':'我的开票任务'}</h1>
    <p className="text-sm text-muted-foreground">按任务办理开票，提交结果后由财务确认。资料核验请使用“开票资料核验”。</p>
    {error&&<p role="alert" className="text-destructive">{error}</p>}{notice&&<p role="status" className="text-sm">{notice}</p>}
    {manage&&<details className="border rounded-md p-4"><summary>创建并分配办理任务</summary><div className="space-y-3 pt-3">
      <Label>搜索项目</Label><div className="flex gap-2"><Input value={search} onChange={e=>setSearch(e.target.value)} placeholder="项目或客户关键词"/><Button disabled={busy} onClick={findProject}>搜索</Button></div>
      <select aria-label="选择项目" className="w-full border rounded p-2" disabled={busy} onChange={e=>selectProject(e.target.value)} value={project?.id||''}><option value="">选择项目</option>{projects.map(p=><option key={p.id} value={p.id}>{p.report_no||p.project_id} · {p.customer_name}</option>)}</select>
      <select aria-label="选择核验档案" className="w-full border rounded p-2" value={form.profile} onChange={e=>setForm({...form,profile:e.target.value})}><option value="">选择当前已核验档案</option>{profiles.filter(p=>p.is_active&&p.current_verified_version_id).map(p=><option key={p.id} value={p.id}>{p.label} · 版本 #{p.current_verified_version_id}</option>)}</select>
      <select aria-label="选择办理人" className="w-full border rounded p-2" value={form.assignee} onChange={e=>setForm({...form,assignee:e.target.value})}><option value="">选择启用后勤</option>{assignees.map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select>
      <Label>本次拟开票金额</Label><MoneyInput value={Number(form.amount)||0} onChange={amount=>setForm({...form,amount:String(amount)})}/><Input maxLength={500} placeholder="分配说明" value={form.note} onChange={e=>setForm({...form,note:e.target.value})}/>
      <Button disabled={busy||!project||!form.profile||!form.assignee||!form.amount} onClick={create}>分配任务</Button>
    </div></details>}
    <div className="flex flex-wrap gap-2"><select aria-label="任务状态" className="border rounded p-2" value={status} onChange={e=>{setStatus(e.target.value);setPage(1)}}><option value="">全部状态</option>{Object.entries(statuses).map(([v,label])=><option key={v} value={v}>{label}</option>)}</select><Button variant="outline" disabled={busy} onClick={()=>{refresh().catch(e=>setError(message(e)));if(selected)choose(selected)}}>刷新核对</Button></div>
    <div className="grid gap-4 lg:grid-cols-2"><div className="space-y-2">{items.map(task=><button key={task.id} disabled={busy} onClick={()=>choose(task)} className="w-full text-left border rounded-md p-3 space-y-1 hover:bg-gray-50"><p>{task.project_number} · {task.customer_name}</p><p className="text-sm">{task.title} · {task.tax_id||'无税号'} · 本次 {task.amount} 元</p><p className="text-sm text-muted-foreground">{statuses[task.status]} · V{task.version_no} · 银行末四位 {task.bank_last4||'未登记'}</p></button>)}<div className="flex justify-between items-center"><span>共 {total} 项</span><div className="flex gap-2"><Button variant="outline" disabled={page===1} onClick={()=>setPage(page-1)}>上一页</Button><Button variant="outline" disabled={page*20>=total} onClick={()=>setPage(page+1)}>下一页</Button></div></div></div>
    {selected&&<section className="border rounded-md p-4 space-y-3"><div className="flex justify-between"><h2 className="font-medium">{statuses[selected.status]} · 修订 {selected.revision}</h2><Button variant="ghost" disabled={busy} onClick={()=>{setSelected(null);setSensitive(null)}}>关闭</Button></div>
      <p>{selected.project_number} · {selected.title} · 本次 {selected.amount} 元</p><p className="text-sm">使用资料 V{selected.version_no}（#{selected.billing_version_id}） · 当前核验版本 #{selected.current_version_id||'无'}</p>
      {selected.note&&<p className="text-sm">分配说明：{selected.note}</p>}{selected.historical_difference&&<p className="text-amber-700 text-sm">资料或所属关系发生变化，须财务明确核对。不会自动替换银行资料。</p>}
      {selected.status==='assigned'&&<Button disabled={busy} onClick={()=>run('reveal',{purpose:'核对本次任务开票资料'})}>查看开票资料</Button>}
      {sensitive&&<div className="space-y-2"><dl className="text-sm">{Object.entries(sensitive.fields).map(([key,value])=><div key={key} className="grid grid-cols-2 gap-2 py-1"><dt>{billingLabels[key]||key}</dt><dd className="break-all">{billingValue(key,value)}</dd></div>)}</dl><p className="text-sm">资料缺项：{sensitive.missing_fields.join('、')||'主体必需字段齐全；仍需核对实际票种要求'}</p><textarea aria-label="可手动复制的开票资料" readOnly className="w-full border rounded p-2 h-40" value={sensitive.copy_text}/><Button onClick={copy}>复制资料</Button><p className="text-xs text-muted-foreground">HTTP浏览器可能需手动复制。撤回仅阻止后续读取，已复制内容无法远程清除。</p></div>}
      {submit&&selected.assignee_id===user?.id&&selected.status==='assigned'&&<div className="space-y-2"><Input aria-label="发票号码" maxLength={100} placeholder="发票号码" value={result.invoice_number} onChange={e=>setResult({...result,invoice_number:e.target.value})}/><Input aria-label="开票日期" type="date" value={result.invoice_date} onChange={e=>setResult({...result,invoice_date:e.target.value})}/><Input placeholder="办理结果说明" maxLength={500} value={result.note} onChange={e=>setResult({...result,note:e.target.value})}/><Button disabled={busy||!result.invoice_number||!result.invoice_date} onClick={()=>run('submit-result',{expected_revision:selected.revision,amount:selected.amount,...result},true)}>提交结果，待财务确认</Button></div>}
      {selected.result&&<div className="bg-gray-50 p-3 text-sm"><p>已提交票号：{selected.result.invoice_number}</p><p>{selected.result.invoice_date} · {selected.result.amount} 元 · 使用版本 #{selected.result.billing_version_id}</p></div>}
      {manage&&['assigned','needs_review','result_submitted'].includes(selected.status)&&<div className="space-y-2"><Input aria-label="管理操作原因" maxLength={500} placeholder="必填：核对、退回或撤回原因" value={reason} onChange={e=>setReason(e.target.value)}/>
        {selected.status==='result_submitted'?<><label className="flex gap-2 text-sm"><input type="checkbox" checked={historical} onChange={e=>setHistorical(e.target.checked)}/>已明确核对使用历史版本的实际开票</label><Input placeholder="可选：关联已有流水ID（项目/金额/票号/版本须相符）" value={existingEntry} onChange={e=>setExistingEntry(e.target.value)}/><div className="flex gap-2"><Button disabled={busy||!reason.trim()} onClick={confirm}>财务确认</Button><Button variant="outline" disabled={busy||!reason.trim()} onClick={()=>run('return',{expected_revision:selected.revision,reason})}>退回重办</Button></div></>:<><select aria-label="新办理人" className="w-full border rounded p-2" value={newAssignee} onChange={e=>setNewAssignee(e.target.value)}><option value="">选择转派办理人</option>{assignees.map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select><Button variant="outline" disabled={busy||!reason.trim()||!newAssignee} onClick={()=>run('reassign',{expected_revision:selected.revision,reason,assignee_id:Number(newAssignee)})}>转派</Button>{selected.status==='needs_review'&&<><select aria-label="重新核对版本" className="w-full border rounded p-2" value={newProfile} onChange={e=>setNewProfile(e.target.value)}><option value="">选择当前核验档案</option>{reviewProfiles.filter(p=>p.is_active&&p.current_verified_version_id).map(p=><option key={p.id} value={p.id}>{p.label} · #{p.current_verified_version_id}</option>)}</select><Button disabled={busy||!reason.trim()||!newProfile} onClick={()=>{const p=reviewProfiles.find(p=>String(p.id)===newProfile);run('revalidate',{expected_revision:selected.revision,reason,billing_profile_id:p.id,billing_version_id:p.current_verified_version_id})}}>明确重新核对版本</Button></>}</>}
        <Button variant="outline" disabled={busy||!reason.trim()} onClick={()=>{if(window.confirm('撤回本任务？已提交结果会保留，已复制内容无法收回。'))run('revoke',{expected_revision:selected.revision,reason})}}>撤回任务</Button>
      </div>}
      {selected.financial_entry_id&&<p>已关联财务流水 #{selected.financial_entry_id}</p>}
      {manage&&selected.result_history?.length>0&&<details><summary>办理结果历史（{selected.result_history.length}）</summary>{selected.result_history.map((r:any)=><p key={r.id} className="text-sm">修订 {r.task_revision} · 票号 {r.invoice_number} · {r.amount}元 · 使用版本 #{r.billing_version_id}</p>)}</details>}
    </section>}</div>
  </div>
}
