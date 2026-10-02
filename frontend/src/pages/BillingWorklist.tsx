import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { billingApi } from '@/api/auth'
import { Button } from '@/components/ui/button'

export default function BillingWorklist() {
  const [status,setStatus]=useState('submitted')
  const [page,setPage]=useState(1)
  const [items,setItems]=useState<any[]>([])
  const [total,setTotal]=useState(0)
  const [error,setError]=useState('')
  useEffect(()=>{billingApi.worklist(status,page).then(r=>{setItems(r.data.items);setTotal(r.data.total)}).catch((e:any)=>setError(e.userMessage || e.response?.data?.detail||'无法加载核验列表'))},[status,page])
  return <div className="max-w-5xl space-y-4"><h1 className="text-2xl font-semibold">开票资料核验</h1><select className="h-10 border rounded-md px-3 bg-white" value={status} onChange={e=>{setStatus(e.target.value);setPage(1)}}><option value="submitted">待核验</option><option value="draft">草稿</option><option value="verified">已确认</option><option value="rejected">已退回</option></select>{error&&<p role="alert" className="text-destructive text-sm">{error}</p>}<div className="divide-y">{items.map(item=><Link key={item.id} className="flex flex-wrap justify-between gap-2 py-3 text-sm" to={`/customers/${item.customer_id}`}><span>{item.fields.title} · V{item.version_no}</span><span className="text-muted-foreground">提交人 #{item.submitted_by} · 银行末四位 {item.bank_last4||'未登记'}</span></Link>)}</div><div className="flex justify-between items-center"><span className="text-sm">共 {total} 项</span><div className="flex gap-2"><Button variant="outline" disabled={page===1} onClick={()=>setPage(page-1)}>上一页</Button><Button variant="outline" disabled={page*20>=total} onClick={()=>setPage(page+1)}>下一页</Button></div></div></div>
}
