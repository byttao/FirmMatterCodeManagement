import { useEffect, useRef, useState } from 'react'
import { brandingApi, licenseApi } from '@/api/auth'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

type LicenseState = {
  mode: string
  allowed: boolean
  reason: string
  limits: Record<string, number> | null
  expires_at?: string
  license_id?: string
  customer_name?: string
  max_users?: number | null
  active_users?: number
  max_projects?: number | null
  active_projects?: number
  server_url?: string
  server_connected?: boolean
  server_connection_reason?: string
}

export default function LicenseManagement() {
  const [license, setLicense] = useState<LicenseState>({ mode: 'development', allowed: true, reason: '', limits: null })
  const [branding, setBranding] = useState({ short_name: '', logo_data: '', replace_banner: false, append_title: false })
  const [licenseJson, setLicenseJson] = useState('')
  const [serverUrl, setServerUrl] = useState('')
  const [licenseFileName, setLicenseFileName] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const licenseFileRef = useRef<HTMLInputElement>(null)

  const load = async () => {
    const [licenseRes, brandingRes] = await Promise.all([licenseApi.status(), brandingApi.get()])
    setLicense(licenseRes.data)
    setBranding(brandingRes.data)
    if (brandingRes.data.append_title && brandingRes.data.short_name) document.title = `业码汇 - ${brandingRes.data.short_name}`
  }

  useEffect(() => { load().catch(() => setError('无法读取授权或品牌配置')) }, [])

  const activate = async () => {
    setError(''); setMessage('')
    try {
      if (!serverUrl.trim()) throw new Error('请输入授权服务器地址')
      const parsed = JSON.parse(licenseJson)
      await licenseApi.activate({ license_document: parsed, server_url: serverUrl.trim() })
      setMessage('授权导入成功')
      setLicenseJson('')
      setLicenseFileName('')
      if (licenseFileRef.current) licenseFileRef.current.value = ''
      await load()
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

  const readLogo = (file?: File) => {
    if (!file) return
    if (file.size > 1_000_000) { setError('LOGO 文件不能超过 1 MB'); return }
    const reader = new FileReader()
    reader.onload = () => setBranding(prev => ({ ...prev, logo_data: String(reader.result || '') }))
    reader.readAsDataURL(file)
  }

  const modeLabel = license.mode === 'trial' ? '试用中' : license.mode === 'licensed' ? '已授权' : '开发模式'
  const quotaLabel = (value?: number | null) => value === undefined || value === null || value === 0 ? '不限' : String(value)

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
          {license.expires_at && <div><span className="text-muted-foreground">到期时间：</span>{new Date(license.expires_at).toLocaleString()}</div>}
          <div><span className="text-muted-foreground">执业人员：</span>{license.active_users ?? 0} / {quotaLabel(license.max_users)}（已有 / 授权）</div>
          <div><span className="text-muted-foreground">项目数量：</span>{license.active_projects ?? 0} / {quotaLabel(license.max_projects)}（已有 / 授权）</div>
          <div><span className="text-muted-foreground">服务器连接：</span><strong className={license.server_connected ? 'text-green-700' : 'text-red-600'}>{license.server_connected ? '已连接' : '未连接'}</strong>{license.server_connection_reason && <span className="ml-2 text-muted-foreground">{license.server_connection_reason}</span>}</div>
          {license.server_url && <div className="truncate"><span className="text-muted-foreground">服务器地址：</span>{license.server_url}</div>}
          {license.limits && <div className="sm:col-span-2"><span className="text-muted-foreground">试用上限：</span>编号年度 {license.limits.fiscal_years} 个，执业人员 {license.limits.practitioners} 名，项目 {license.limits.projects} 个</div>}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>导入授权</CardTitle><CardDescription>选择 `.liscence` 文件或粘贴授权中心导出的 JSON；导入前请确认授权文件来自可信来源。</CardDescription></CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-2"><Label htmlFor="serverUrl">授权服务器地址 <span className="text-red-600">*</span></Label><Input id="serverUrl" required value={serverUrl} onChange={e => setServerUrl(e.target.value)} placeholder="https://license.example.com" /></div>
          <div className="space-y-2"><Label htmlFor="licenseFile">授权文件</Label><Input ref={licenseFileRef} id="licenseFile" type="file" accept=".liscence,.json,application/json,text/plain" onChange={e => readLicenseFile(e.target.files?.[0])} className="h-auto py-2" />{licenseFileName && <p className="text-xs text-muted-foreground">已读取：{licenseFileName}</p>}</div>
          <div className="space-y-2"><Label htmlFor="licenseJson">授权 JSON</Label><textarea id="licenseJson" className="min-h-32 w-full rounded-md border bg-background px-3 py-2 text-sm font-mono" value={licenseJson} onChange={e => setLicenseJson(e.target.value)} placeholder="粘贴授权文件内容" /></div>
          <Button onClick={activate} disabled={!licenseJson.trim() || !serverUrl.trim()}>导入并激活</Button>
        </CardContent>
      </Card>
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
