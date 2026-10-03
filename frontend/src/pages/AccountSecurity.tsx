import { LOGIN_PASSWORD_HINT, LOGIN_PASSWORD_PATTERN, loginPasswordError } from '@/lib/passwordPolicy'
import { useState } from 'react'
import { KeyRound, LogOut } from 'lucide-react'
import { authApi } from '@/api/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export default function AccountSecurity() {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(event: React.FormEvent) {
    event.preventDefault()
    const passwordError = loginPasswordError(newPassword)
    if (passwordError) { setMessage(passwordError); return }
    setBusy(true); setMessage('')
    try { await authApi.changePassword(currentPassword, newPassword); window.location.assign('/login') }
    catch (error: any) { setMessage(error.userMessage || error.response?.data?.detail || '改密失败'); setBusy(false) }
  }
  async function revokeAll() {
    if (!window.confirm('确定退出所有设备？')) return
    await authApi.logoutAll(); window.location.assign('/login')
  }
  return <div className="space-y-6"><h1 className="text-xl font-semibold">账号安全</h1>
    <form onSubmit={submit} className="max-w-md space-y-4">
      <div className="space-y-2"><Label htmlFor="current-password">原密码</Label><Input id="current-password" type="password" autoComplete="current-password" required value={currentPassword} onChange={event => setCurrentPassword(event.target.value)} /></div>
      <div className="space-y-2"><Label htmlFor="new-password">新密码</Label><Input id="new-password" type="password" autoComplete="new-password" minLength={8} maxLength={72} pattern={LOGIN_PASSWORD_PATTERN} title={LOGIN_PASSWORD_HINT} placeholder={LOGIN_PASSWORD_HINT} required value={newPassword} onChange={event => setNewPassword(event.target.value)} /></div>
      <p className="text-sm text-muted-foreground">{LOGIN_PASSWORD_HINT}</p>
      {message && <p role="alert" className="text-sm text-red-600">{message}</p>}
      <Button disabled={busy}><KeyRound className="mr-2 h-4 w-4" />更改密码并重新登录</Button>
    </form>
    <Button variant="outline" onClick={revokeAll}><LogOut className="mr-2 h-4 w-4" />退出所有设备</Button>
  </div>
}
