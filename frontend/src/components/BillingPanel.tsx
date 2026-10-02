import { useEffect, useRef, useState } from 'react'
import { billingLabels, billingValue } from '@/lib/billing'
import { billingApi } from '@/api/auth'
import { useAuth } from '@/store/AuthContext'
import { can } from '@/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Plus, Pencil, Send, Check, Copy, Eye, Power, Star } from 'lucide-react'

const fields = [
  ['title', '开票抬头', 200], ['tax_id', '税号 / 标识', 50], ['registered_address', '注册地址', 300],
  ['registered_phone', '注册电话', 50], ['bank_name', '开户银行', 200], ['bank_account', '银行账号', 64],
  ['contact_name', '开票联系人', 100], ['recipient_phone', '收票电话', 50], ['recipient_email', '收票邮箱', 254], ['note', '备注', 1000],
] as const
const statusNames: Record<string, string> = {draft: '草稿', submitted: '待核验', verified: '已确认', rejected: '已退回', superseded: '历史版本'}

export default function BillingPanel({customerId}: {customerId: number}) {
  const { user } = useAuth()
  const [profiles, setProfiles] = useState<any[]>([])
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [editor, setEditor] = useState<{profile?: any; version?: any} | null>(null)
  const [form, setForm] = useState<Record<string, any>>({})
  const [label, setLabel] = useState('默认开票资料')
  const [preview, setPreview] = useState<{version: any; profile: any; changes: any[]; fields: any} | null>(null)
  const [note, setNote] = useState('')
  const [copyText, setCopyText] = useState<string | null>(null)
  const copyRef = useRef<HTMLTextAreaElement>(null)
  const manage = can(user, 'billing.manage')
  const load = async () => { setProfiles((await billingApi.profiles(customerId)).data) }
  useEffect(() => {setProfiles([]); setCopyText(null); load().catch((e: any) => setError(e.userMessage || e.response?.data?.detail || '开票资料暂不可读'))}, [customerId, user?.id])
  useEffect(() => {
    const guard = (e: BeforeUnloadEvent) => {if (editor) {e.preventDefault(); e.returnValue=''}}
    window.addEventListener('beforeunload', guard)
    return () => window.removeEventListener('beforeunload', guard)
  }, [editor])
  const openEditor = async (profile?: any, version?: any, clone = false) => {
    setError(''); setCopyText(null)
    try {
      const values = version ? (await billingApi.reveal(version.id)).data.fields : {}
      setForm(values); setLabel(profile?.label || '默认开票资料'); setEditor({profile, version: clone ? undefined : version})
    } catch (e: any) {setError(e.userMessage || e.response?.data?.detail || '无法读取草稿')}
  }
  const save = async () => {
    if (!editor || saving) return
    setSaving(true); setError('')
    try {
      const values = Object.fromEntries(Object.entries(form).map(([key, value]) => [key, typeof value === 'string' && !value.trim() ? null : value]))
            if (editor.version) await billingApi.update(editor.version.id, editor.version.revision, values)
      else if (editor.profile) await billingApi.newVersion(editor.profile.id, editor.profile.revision, values)
      else await billingApi.create(customerId, label, values)
      await load()
      setEditor(null)
    } catch (e: any) {setError(e.userMessage || e.response?.data?.detail || '保存失败，草稿已保留')}
    finally {setSaving(false)}
  }
  const submit = async (version: any) => {
    try {await billingApi.submit(version.id, version.revision); await load()} catch(e: any) {setError(e.userMessage || e.response?.data?.detail || '提交失败')}
  }
  const verifyPreview = async (profile: any, version: any) => {
    try {const res=await billingApi.preview(version.id); setPreview({profile, version, ...res.data}); setNote('')}
    catch(e: any) {setError(e.userMessage || e.response?.data?.detail || '无法核验')}
  }
  const verify = async (decision: string) => {
    if (!preview || !note.trim()) return
    setSaving(true)
    try {await billingApi.verify(preview.version.id, preview.version.revision, preview.profile.revision, decision, note); setPreview(null); await load()}
    catch(e: any) {setError(e.userMessage || e.response?.data?.detail || '核验失败，当前资料已保留')}
    finally {setSaving(false)}
  }
  const reveal = async (version: any) => {
    try {setCopyText((await billingApi.reveal(version.id)).data.copy_text)} catch(e: any) {setError(e.userMessage || e.response?.data?.detail || '无法读取开票资料')}
  }
  const copy = async () => {
    try {
      if (!navigator.clipboard) throw new Error()
      await navigator.clipboard.writeText(copyText || '')
    } catch {copyRef.current?.focus(); copyRef.current?.select(); setError(/Mac/.test(navigator.platform) ? '请按 Command+C 复制选中的资料' : '请按 Ctrl+C 复制选中的资料')}
  }

  return <section className="space-y-3">
    <div className="flex justify-between items-center"><h2 className="text-lg font-semibold">开票资料</h2><Button type="button" size="sm" onClick={() => openEditor()}><Plus className="mr-2 h-4 w-4" />新增档案</Button></div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {profiles.map(profile => <section key={profile.id} className="border-t pt-3 space-y-2">
      <div className="flex flex-wrap justify-between gap-2"><h3 className="font-medium">{profile.label}{profile.is_default && ' · 默认'}{!profile.is_active && ' · 停用'}</h3><div className="flex gap-1">
        <Button type="button" size="sm" variant="outline" onClick={() => openEditor(profile, profile.versions.find((v: any) => v.id === profile.current_verified_version_id), true)}><Plus className="mr-1 h-4 w-4" />新版本</Button>
        {manage && <><Button type="button" size="icon" variant="ghost" title="设为默认" onClick={async()=>{try{await billingApi.configure(profile.id, profile.revision, {is_default:true}); await load()}catch(e:any){setError(e.userMessage || e.response?.data?.detail||'保存失败')}}}><Star className="h-4 w-4" /></Button><Button type="button" size="icon" variant="ghost" title={profile.is_active ? '停用档案' : '启用档案'} onClick={async()=>{try{await billingApi.configure(profile.id, profile.revision, {is_active:!profile.is_active}); await load()}catch(e:any){setError(e.userMessage || e.response?.data?.detail||'保存失败')}}}><Power className="h-4 w-4" /></Button></>}
      </div></div>
      <div className="border rounded-md overflow-x-auto"><Table className="min-w-[640px]"><TableHeader><TableRow><TableHead>版本</TableHead><TableHead>状态</TableHead><TableHead>抬头 / 税号</TableHead><TableHead>银行末四位</TableHead><TableHead>核验</TableHead><TableHead>操作</TableHead></TableRow></TableHeader><TableBody>{profile.versions.map((version: any) => <TableRow key={version.id}><TableCell>V{version.version_no}</TableCell><TableCell>{statusNames[version.status]}</TableCell><TableCell>{version.fields.title}<br />{version.fields.tax_id || '-'}</TableCell><TableCell>{version.bank_last4 ? `****${version.bank_last4}` : '未登记'}</TableCell><TableCell>{version.verified_by || '-'}<br />{version.verification_note}</TableCell><TableCell><div className="flex gap-1">
        <Button type="button" size="icon" variant="ghost" title="查看 / 复制开票资料" onClick={() => reveal(version)}><Eye className="h-4 w-4" /></Button>
        {version.status === 'draft' && (manage || version.submitted_by === user?.id) && <><Button type="button" size="icon" variant="ghost" title="编辑草稿" onClick={() => openEditor(profile, version)}><Pencil className="h-4 w-4" /></Button><Button type="button" size="icon" variant="ghost" title="提交核验" onClick={() => submit(version)}><Send className="h-4 w-4" /></Button></>}
        {manage && ['draft','submitted'].includes(version.status) && <Button type="button" size="icon" variant="ghost" title="核验资料差异" onClick={() => verifyPreview(profile, version)}><Check className="h-4 w-4" /></Button>}
      </div></TableCell></TableRow>)}</TableBody></Table></div>
    </section>)}
    <Dialog open={!!editor} onOpenChange={open=>{if(!open && window.confirm('关闭未保存草稿？')) setEditor(null)}}><DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto"><DialogHeader><DialogTitle>{editor?.version ? '编辑开票草稿' : '新建开票资料版本'}</DialogTitle></DialogHeader><form className="grid grid-cols-1 sm:grid-cols-2 gap-3" onSubmit={e=>{e.preventDefault();save()}}>
      {!editor?.profile && <div><Label>档案名称</Label><Input value={label} maxLength={50} required onChange={e=>setLabel(e.target.value)} /></div>}
      <div><Label>购买方类型</Label><select value={form.buyer_type || ''} className="w-full h-10 border rounded-md bg-white px-2" onChange={e=>setForm({...form,buyer_type:e.target.value || null})}><option value="">随客户主体</option><option value="enterprise">企业</option><option value="individual">个人</option><option value="overseas">境外</option></select></div>
      {fields.map(([key,name,length])=><div key={key}><Label>{name}</Label><Input type={key==='recipient_email'?'email':'text'} maxLength={length} value={form[key] || ''} onChange={e=>setForm({...form,[key]:e.target.value})} /></div>)}
      <div><Label>发票偏好</Label><select value={form.invoice_preference || 'unspecified'} className="w-full h-10 border rounded-md bg-white px-2" onChange={e=>setForm({...form,invoice_preference:e.target.value})}><option value="unspecified">未指定</option><option value="normal">普通发票</option><option value="special">专用发票</option><option value="other">其他</option></select></div>
      {error && <p className="text-sm text-destructive sm:col-span-2">{error}</p>}<DialogFooter className="sm:col-span-2"><Button type="submit" disabled={saving}>保存草稿</Button></DialogFooter>
    </form></DialogContent></Dialog>
    <Dialog open={!!preview} onOpenChange={open=>{if(!open)setPreview(null)}}><DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto"><DialogHeader><DialogTitle>核验开票资料 V{preview?.version.version_no}</DialogTitle></DialogHeader><div className="overflow-x-auto"><Table><TableHeader><TableRow><TableHead>字段</TableHead><TableHead>原资料</TableHead><TableHead>待确认资料</TableHead></TableRow></TableHeader><TableBody>{preview?.changes.map(change=><TableRow key={change.field}><TableCell>{billingLabels[change.field]||'资料'}</TableCell><TableCell className="break-all">{billingValue(change.field,change.before)}</TableCell><TableCell className="break-all">{billingValue(change.field,change.after)}</TableCell></TableRow>)}</TableBody></Table></div><Label>核验依据 / 退回原因</Label><Input value={note} maxLength={500} onChange={e=>setNote(e.target.value)} />{error&&<p className="text-sm text-destructive">{error}</p>}<DialogFooter><Button variant="outline" disabled={saving||!note.trim()} onClick={()=>verify('reject')}>退回</Button><Button disabled={saving||!note.trim()} onClick={()=>verify('approve')}><Check className="mr-2 h-4 w-4" />已核对，确认版本</Button></DialogFooter></DialogContent></Dialog>
    <Dialog open={copyText!==null} onOpenChange={open=>{if(!open)setCopyText(null)}}><DialogContent><DialogHeader><DialogTitle>开票资料</DialogTitle></DialogHeader><textarea ref={copyRef} className="w-full min-h-[240px] border rounded-md p-3 text-sm" value={copyText||''} readOnly />{error&&<p className="text-sm text-destructive">{error}</p>}<DialogFooter><Button onClick={copy}><Copy className="mr-2 h-4 w-4" />复制资料</Button></DialogFooter></DialogContent></Dialog>
  </section>
}
