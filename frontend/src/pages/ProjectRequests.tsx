import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { projectRequestApi } from '@/api/auth'
import { useAuth } from '@/store/AuthContext'
import { can } from '@/types'
import { Button } from '@/components/ui/button'
import { Check, X } from 'lucide-react'

export default function ProjectRequests(){
  const {user}=useAuth()
  const [page,setPage]=useState(1)
  const [items,setItems]=useState<any[]>([])
  const [total,setTotal]=useState(0)
  const [error,setError]=useState('')
  const load=async()=>{const r=await projectRequestApi.list(page);setItems(r.data.items);setTotal(r.data.total)}
  useEffect(()=>{load().catch((e:any)=>setError(e.userMessage || e.response?.data?.detail||'无法加载申请'))},[page])
  const review=async(item:any,decision:string)=>{
    const reason=window.prompt('审核依据 / 拒绝原因')
    if(!reason?.trim())return
    try{await projectRequestApi.review(item.id,item.revision,decision,reason);await load()}
    catch(e:any){setError(e.userMessage || e.response?.data?.detail||'审核失败')}
  }
  return <div className="max-w-5xl space-y-4"><h1 className="text-2xl font-semibold">项目申请</h1>{error&&<p role="alert" className="text-destructive text-sm">{error}</p>}<div className="divide-y">{items.map(item=><div key={item.id} className="py-3 flex flex-wrap justify-between gap-3 text-sm"><div><Link className="text-primary" to={`/projects/${item.project_id}`}>项目 #{item.project_id}</Link><p>{item.kind==='transfer'?`移交至账号 #${item.target_leader_id}`:'作废报告编号'} · {({submitted:'待审核',approved:'已通过',rejected:'已拒绝'} as Record<string,string>)[item.status]}</p><p>{item.reason}</p>{item.review_reason&&<p className="text-muted-foreground">{item.review_reason}</p>}</div>{can(user,'project.transfer')&&item.status==='submitted'&&<div className="flex gap-2"><Button variant="outline" size="icon" title="通过并执行" onClick={()=>review(item,'approve')}><Check /></Button><Button variant="outline" size="icon" title="拒绝申请" onClick={()=>review(item,'reject')}><X /></Button></div>}</div>)}</div><div className="flex justify-between"><span className="text-sm">共 {total} 项</span><div className="flex gap-2"><Button disabled={page===1} onClick={()=>setPage(page-1)}>上一页</Button><Button disabled={page*20>=total} onClick={()=>setPage(page+1)}>下一页</Button></div></div></div>
}
