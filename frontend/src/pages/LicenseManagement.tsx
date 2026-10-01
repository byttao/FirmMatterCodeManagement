import { useEffect, useRef, useState } from 'react'
import { brandingApi, licenseApi } from '@/api/auth'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { RefreshCw } from 'lucide-react'

type LicenseState = {
  mode: string
  allowed: boolean
  reason: string
  limits: Record<string, number> | null
  expires_at?: string
  lease_until?: string
  license_id?: string
  customer_name?: string
  max_users?: number | null
  active_users?: number
  max_projects?: number | null
  active_projects?: number
  server_url?: string
  server_connected?: boolean
  server_connection_reason?: string
  heartbeat_last_at?: string
  heartbeat_last_success_at?: string
  heartbeat_last_error?: string
}

export default function LicenseManagement() {
  const [license, setLicense] = useState<LicenseState>({ mode: 'development', allowed: true, reason: '', limits: null })
  const [branding, setBranding] = useState({ short_name: '', logo_data: '', replace_banner: false, append_title: false })
  const [licenseJson, setLicenseJson] = useState('')
  const [serverUrl, setServerUrl] = useState('')
  const [recoveryUrl, setRecoveryUrl] = useState('')
  const [licenseFileName, setLicenseFileName] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [heartbeatLoading, setHeartbeatLoading] = useState(false)
  const licenseFileRef = useRef<HTMLInputElement>(null)

  const load = async () => {
    const licenseRes = await licenseApi.status()
    setLicense(licenseRes.data)
    brandingApi.get().then(brandingRes=>{
      setBranding(brandingRes.data)
      if (brandingRes.data.append_title && brandingRes.data.short_name) document.title = `业码汇 - ${brandingRes.data.short_name}`
    }).catch(()=>undefined)
  }

  useEffect(() => { load().catch(() => setError('无法读取授权或品牌配置')) }, [])

  const activate = async () => {
    setError(''); setMessage('')
    try {
      const parsed = JSON.parse(licenseJson)
      await licenseApi.activate({ license_document: parsed })
      setMessage('授权导入成功')
      setLicenseJson('')
      setLicenseFileName('')
      if (licenseFileRef.current) licenseFileRef.current.value = ''
      await load()
      window.dispatchEvent(new Event('license-updated'))
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || '授权导入失败，请确认 JSON 文件和授权服务器地址')
    }
  }

  const readLicenseFile = (file?: File) => {
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => {
      try {
        const text = String(reader.result || '')
        const parsed = JSON.parse(text)
        setLicenseJson(JSON.stringify(parsed, null, 2))
        if (typeof parsed.server_url === 'string' && parsed.server_url.trim()) setServerUrl(parsed.server_url.trim())
        setLicenseFileName(file.name)
        setError('')
      } catch {
        setError('授权文件不是有效的 JSON 文本')
        setLicenseJson('')
        setLicenseFileName('')
      }
    }
    reader.readAsText(file)
  }

  const saveBranding = async () => {
    setError(''); setMessage('')
    try {
      await brandingApi.update(branding)
      setMessage('品牌设置已保存')
      if (branding.append_title && branding.short_name) document.title = `业码汇 - ${branding.short_name}`
    } catch (err: any) {
      setError(err.response?.data?.detail || '品牌设置保存失败')
    }
  }

  const refreshLicense = async () => {
    setError(''); setMessage(''); setHeartbeatLoading(true)
    try {
      await licenseApi.heartbeat()
      setMessage('授权状态已更新')
      await load()
      window.dispatchEvent(new Event('license-updated'))
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || '授权状态更新失败')
      await load().catch(() => undefined)
    } finally {
      setHeartbeatLoading(false)
    }
  }

  const readLogo = (file?: File) => {
    if (!file) return
    if (file.size > 1_000_000) { setError('LOGO 文件不能超过 1 MB'); return }
    const reader = new FileReader()
    reader.onload = () => setBranding(prev => ({ ...prev, logo_data: String(reader.result || '') }))
    reader.readAsDataURL(file)
  }

  const modeLabel = ({trial:'试用中',active:'有效',offline_grace:'有效离线租约内',development:'源码开发',expired_readonly:'到期只读',suspended_readonly:'暂停只读',revoked_readonly:'撤销只读',not_yet_active:'尚未生效',invalid_license:'授权无效',clock_untrusted:'需校时',version_not_allowed:'版本不适用',user_limit_exceeded:'超过人员上限'} as Record<string,string>)[license.mode] || '待核验'
  const quotaLabel = (value?: number | null) => value === undefined || value === null || value === 0 ? '不限' : String(value)
  const formatHeartbeat = (value?: string) => value ? new Date(value).toLocaleString() : '尚未检测'

  return (
    <div className="space-y-6 max-w-4xl">
      <div>
        <h1 className="text-2xl font-bold">授权与品牌</h1>
        <p className="text-sm text-muted-foreground mt-1">查看当前授权状态，导入授权文件并配置事务所展示信息。</p>
      </div>
      {message && <div className="rounded border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700">{message}</div>}
      {error && <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
      <Card>
        <CardHeader><CardTitle>当前授权</CardTitle><CardDescription>授权状态会同时显示在登录页和管理工具中。</CardDescription></CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2 text-sm">
          <div><span className="text-muted-foreground">状态：</span><strong className={license.mode === 'trial' ? 'text-amber-600' : 'text-green-700'}>{modeLabel}</strong></div>
          <div><span className="text-muted-foreground">说明：</span>{license.reason || '正常'}</div>
          <div><span className="text-muted-foreground">签约公司：</span>{license.customer_name || '未绑定公司'}</div>
          {license.license_id && <div><span className="text-muted-foreground">授权编号：</span>{license.license_id}</div>}
          <div><span className="text-muted-foreground">合同截止：</span>{license.expires_at?new Date(license.expires_at).toLocaleString():'永久使用权 / 未签约'}</div>
          {license.lease_until&&<div><span className="text-muted-foreground">离线租约截止：</span>{new Date(license.lease_until).toLocaleString()}</div>}
          <div><span className="text-muted-foreground">执业人员：</span>已有 {license.active_users ?? 0} 人，授权上限 {quotaLabel(license.max_users)} 人</div>
          <div><span className="text-muted-foreground">项目数量：</span>已有 {license.active_projects ?? 0} 个，授权上限 {quotaLabel(license.max_projects)} 个</div>
          <div><span className="text-muted-foreground">最近核验结果：</span><strong className={license.server_connected ? 'text-green-700' : 'text-red-600'}>{license.server_connected ? '成功' : '尚未成功'}</strong>{license.server_connection_reason && <span className="ml-2 text-muted-foreground">{license.server_connection_reason}</span>}</div>
          {license.server_url && <div className="truncate"><span className="text-muted-foreground">服务器地址：</span>{license.server_url}</div>}
          <div><span className="text-muted-foreground">上次心跳检测：</span>{formatHeartbeat(license.heartbeat_last_at)}</div>
          <div><span className="text-muted-foreground">最近成功核验：</span>{formatHeartbeat(license.heartbeat_last_success_at)}</div>
          {license.heartbeat_last_error && <div className="sm:col-span-2 text-red-600"><span className="text-muted-foreground">最近心跳错误：</span>{license.heartbeat_last_error}</div>}
          <div className="sm:col-span-2"><Button variant="outline" size="sm" onClick={refreshLicense} disabled={heartbeatLoading}><RefreshCw className={`mr-2 h-4 w-4 ${heartbeatLoading ? 'animate-spin' : ''}`} />{heartbeatLoading ? '更新中...' : '手动更新授权状态'}</Button></div>
          {license.limits && <div className="sm:col-span-2"><span className="text-muted-foreground">试用上限：</span>编号年度 {license.limits.fiscal_years} 个，执业人员 {license.limits.practitioners} 名，项目 {license.limits.projects} 个</div>}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>导入授权</CardTitle><CardDescription>选择 `.liscence` 文件或粘贴授权中心导出的 JSON；导入前请确认授权文件来自可信来源。</CardDescription></CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">连接地址由签名许可证指定，验签通过后使用。永久授权也需每15天内联网核验。</p>
          {serverUrl&&<div className="space-y-2"><Label htmlFor="serverUrl">文件指定的连接地址</Label><Input id="serverUrl" value={serverUrl} readOnly /></div>}
          <div className="space-y-2"><Label htmlFor="licenseFile">授权文件</Label><Input ref={licenseFileRef} id="licenseFile" type="file" accept=".liscence,.json,application/json,text/plain" onChange={e => readLicenseFile(e.target.files?.[0])} className="h-auto py-2" />{licenseFileName && <p className="text-xs text-muted-foreground">已读取：{licenseFileName}</p>}</div>
          <div className="space-y-2"><Label htmlFor="licenseJson">授权 JSON</Label><textarea id="licenseJson" className="min-h-32 w-full rounded-md border bg-background px-3 py-2 text-sm font-mono" value={licenseJson} onChange={e => setLicenseJson(e.target.value)} placeholder="粘贴授权文件内容" /></div>
          <Button onClick={activate} disabled={!licenseJson.trim()}>导入并激活</Button>
        </CardContent>
      </Card>
      <Card><CardHeader><CardTitle>恢复授权连接地址</CardTitle><CardDescription>旧地址失效时填写新的HTTP IP和端口；只有通过原发行公钥核验的中心响应才会保存。</CardDescription></CardHeader><CardContent className="space-y-3"><Input value={recoveryUrl} onChange={e=>setRecoveryUrl(e.target.value)} placeholder="http://192.168.10.20:8100" /><Button variant="outline" disabled={!license.license_id||!recoveryUrl.trim()} onClick={async()=>{setError('');try{await licenseApi.recoverEndpoint(recoveryUrl);await load();setMessage('新地址已核验并保存');window.dispatchEvent(new Event('license-updated'))}catch(e:any){setError(e.response?.data?.detail||'恢复失败，原地址保留')}}}>核验并保存新地址</Button></CardContent></Card>
      <Card>
        <CardHeader><CardTitle>事务所展示</CardTitle><CardDescription>可将事务所 LOGO 和简称用于登录页及网页标题。</CardDescription></CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2"><Label htmlFor="shortName">事务所简称</Label><Input id="shortName" value={branding.short_name} onChange={e => setBranding(prev => ({ ...prev, short_name: e.target.value }))} maxLength={60} /></div>
          <div className="space-y-2"><Label htmlFor="logo">事务所 LOGO</Label><Input id="logo" type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml" onChange={e => readLogo(e.target.files?.[0])} className="h-auto py-2" />{branding.logo_data && <img src={branding.logo_data} alt="事务所 LOGO 预览" className="h-16 max-w-xs object-contain border rounded p-1" />}</div>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={branding.replace_banner} onChange={e => setBranding(prev => ({ ...prev, replace_banner: e.target.checked }))} />使用 LOGO + 事务所简称替换原 banner</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={branding.append_title} onChange={e => setBranding(prev => ({ ...prev, append_title: e.target.checked }))} />网页标题加上事务所简称</label>
          <Button onClick={saveBranding}>保存品牌设置</Button>
        </CardContent>
      </Card>
    </div>
  )
}
