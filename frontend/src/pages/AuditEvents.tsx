import { useEffect, useState } from 'react'
import { auditApi } from '@/api/auth'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

export default function AuditEvents() {
  const [page,setPage]=useState(1)
  const [items,setItems]=useState<any[]>([])
  const [total,setTotal]=useState(0)
  const [error,setError]=useState('')
  useEffect(()=>{auditApi.list(page).then(r=>{setItems(r.data.items);setTotal(r.data.total)}).catch((e:any)=>setError(e.userMessage || e.response?.data?.detail||'无法读取审计'))},[page])
  return <div className="space-y-4"><h1 className="text-2xl font-semibold">操作审计</h1>{error&&<p role="alert" className="text-destructive text-sm">{error}</p>}<div className="overflow-x-auto border rounded-md"><Table className="min-w-[800px]"><TableHeader><TableRow><TableHead>时间（北京时间）</TableHead><TableHead>操作人</TableHead><TableHead>动作 / 对象</TableHead><TableHead>原因</TableHead><TableHead>请求编号</TableHead></TableRow></TableHeader><TableBody>{items.map(item=><TableRow key={item.id}><TableCell>{new Date(item.created_at+'Z').toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})}</TableCell><TableCell>#{item.actor_id}</TableCell><TableCell>{item.action}<br />{item.target_type} #{item.target_id}</TableCell><TableCell>{item.reason||'-'}</TableCell><TableCell className="font-mono text-xs">{item.request_id}</TableCell></TableRow>)}</TableBody></Table></div><div className="flex justify-between items-center"><span className="text-sm">共 {total} 项</span><div className="flex gap-2"><Button variant="outline" disabled={page===1} onClick={()=>setPage(page-1)}>上一页</Button><Button variant="outline" disabled={page*50>=total} onClick={()=>setPage(page+1)}>下一页</Button></div></div></div>
}
