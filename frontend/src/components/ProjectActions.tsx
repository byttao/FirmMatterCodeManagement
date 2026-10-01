import { useState } from 'react'
import { projectRequestApi, projectApi, customerApi } from '@/api/auth'
import { useAuth } from '@/store/AuthContext'
import { can, type Project } from '@/types'
import { Button } from '@/components/ui/button'
import { Send, UserRoundCheck, Building2 } from 'lucide-react'

export default function ProjectActions({project,onChange}:{project:Project;onChange:(p:Project)=>void}) {
  const {user}=useAuth()
  const [message,setMessage]=useState('')
  const [busy,setBusy]=useState(false)
  const propose=async(kind:string)=>{
    const target=kind==='transfer'?window.prompt('新负责人账号编号'):null
    if(kind==='transfer'&&(!target||!Number.isInteger(Number(target))||Number(target)<1))return
    const reason=window.prompt(kind==='transfer'?'负责人移交申请原因':'编号作废申请原因')
    if(!reason?.trim())return
    setBusy(true)
    try{await projectRequestApi.propose(project.id,{expected_revision:project.revision,kind,target_leader_id:target?Number(target):undefined,reason});setMessage('申请已提交')}
    catch(e:any){setMessage(e.response?.data?.detail||'申请失败')}
    finally{setBusy(false)}
  }
  const correct=async()=>{
    const target=window.prompt('正确客户档案编号')
    if(!target||!Number.isInteger(Number(target))||Number(target)<1)return
    setBusy(true)
    try{
      const customer=(await customerApi.get(Number(target))).data
      if(!window.confirm(`当前归属客户 #${project.customer_id}，调整为 ${customer.name}（${customer.tax_id||'无税号'}）？历史项目名称和发票快照保留。`))return
      const reason=window.prompt('已核对主体的纠错依据')
      if(!reason?.trim())return
      await projectRequestApi.correctCustomer(project.id,project.revision,customer.id,reason)
      onChange((await projectApi.get(project.id)).data);setMessage('客户归属已更正')
    }catch(e:any){setMessage(e.response?.data?.detail||'纠错失败')}
    finally{setBusy(false)}
  }
  const leader=user?.id===project.leader_id&&can(user,'project.edit.led')
  return <section className="border-t pt-3 space-y-2"><div className="flex flex-wrap gap-2">{leader&&<><Button type="button" variant="outline" disabled={busy} onClick={()=>propose('transfer')}><UserRoundCheck className="h-4 w-4 mr-2" />申请移交</Button>{project.report_no&&project.report_no_status!=='recycled'&&<Button type="button" variant="outline" disabled={busy} onClick={()=>propose('void_number')}><Send className="h-4 w-4 mr-2" />申请作废编号</Button>}</>}{can(user,'customer.correct')&&<Button type="button" variant="outline" disabled={busy} onClick={correct}><Building2 className="h-4 w-4 mr-2" />纠正客户归属</Button>}</div>{message&&<p role="status" className="text-sm">{message}</p>}</section>
}
