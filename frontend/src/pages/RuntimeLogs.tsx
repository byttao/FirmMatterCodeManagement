import { useEffect, useState } from 'react'
import api, {downloadFile} from '@/api/auth'
import {useAuth} from '@/store/AuthContext'
import {can} from '@/types'
async function read<T>(path: string) { return (await api.get<T>(path.replace('/api/', '/'))).data }
async function exportFile(path: string) { return downloadFile(path.replace('/api/', '/'),'POST') }

type Log = { timestamp: string; level: string; event: string; actor_id?: number; category?: string; request_id?: string; route?: string; client_ip?: string; reason_code?: string; status_code?: number; duration_ms?: number; customer_name?: string; customer_id?: number; instance_id?: string; identity_verified?: boolean; exception_type?: string; exception_location?: string }
type Result = { items: Log[]; has_more: boolean; truncated: boolean; next_cursor?: string | null; scan_complete?: boolean; since?: string; until?: string; available_range?: {earliest?:string; latest?:string; index_complete?:boolean}; retention_policy?:string }
const groups: Record<string, string> = { system_error: '系统故障', access_restriction: '登录/权限限制', business_restriction: '操作条件限制', rate_limit: '频率/资源限制', success: '正常' }
const levels: Record<string, string> = { INFO: '信息', WARNING: '受限/警告', ERROR: '系统错误' }
const empty = { request_id: '', actor_id: '', customer_id: '', instance_id: '', since: '', until: '', level: '' }

export default function RuntimeLogs() {
  const {user} = useAuth(); const allowed = can(user, 'diagnostics.read')
  const [draft, setDraft] = useState(empty)
  const [query, setQuery] = useState(() => { const until=new Date();return new URLSearchParams({since:new Date(until.getTime()-86400000).toISOString(),until:until.toISOString()}).toString() })
  const [cursor, setCursor] = useState<string | null>(null)
  const [revision, setRevision] = useState(0)
  const [result, setResult] = useState<Result>({ items: [], has_more: false, truncated: false })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [drops, setDrops] = useState(0)
  const [health, setHealth] = useState<{process_started_at?:string;last_log_failure_at?:string;last_log_failure_code?:string}>({})
  useEffect(() => {
    if (!allowed) return
    let active = true
    setLoading(true); setError('')
    Promise.all([read<Result>(`/api/diagnostics/logs?${query}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`), read<{log_drops: number; process_started_at?:string;last_log_failure_at?:string;last_log_failure_code?:string}>('/api/diagnostics/summary')])
      .then(([value, summary]) => { if (active) { setResult(value); setDrops(summary.log_drops); setHealth(summary) } })
      .catch((e: Error) => { if (active) setError(e.message) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [allowed, query, cursor, revision])
  function search(event: React.FormEvent) {
    event.preventDefault()
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(draft)) if (value.trim()) {
      // The inputs explicitly represent Beijing time regardless of browser locale.
      params.set(key, key === 'since' || key === 'until' ? new Date(value + '+08:00').toISOString() : value.trim())
    }
    const until = params.get('until') || new Date().toISOString(); params.set('until',until);
    if (!params.has('since')) params.set('since',new Date(new Date(until).getTime()-86400000).toISOString());
    setQuery(params.toString()); setCursor(null); setRevision(value => value + 1)
  }
  async function download() {
    setExporting(true); setError('')
    try {
      const blob = await exportFile(`/api/diagnostics/export?${query}`)
      const url = URL.createObjectURL(blob), link = document.createElement('a')
      link.href = url; link.download = 'diagnostics.zip'; link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (e) { setError(e instanceof Error ? e.message : '诊断导出失败') }
    finally { setExporting(false) }
  }
  if (!allowed) return <p role="alert">只有事务所管理员可以查看或导出运行诊断。请把请求编号及操作时间提供给管理员。</p>
  return <section className="space-y-4 [&_button]:border [&_button]:rounded [&_button]:px-3 [&_button]:py-2 [&_button:disabled]:opacity-50 [&_h2]:text-xl [&_p]:text-sm">
    <h2>运行日志与问题排查</h2>
    <p>执业人员无需导出日志：提供请求编号、操作时间和页面，由管理员在这里筛选并导出。权限或操作条件限制不等于系统故障。默认查询最近24小时，时间按北京时间填写。</p>
    <form onSubmit={search} className="grid grid-cols-1 md:grid-cols-3 gap-3 [&_label]:flex [&_label]:flex-col [&_input]:border [&_input]:rounded [&_input]:p-2 [&_select]:p-2">
      <label>请求编号<input value={draft.request_id} maxLength={64} onChange={e => setDraft({...draft, request_id: e.target.value})} /></label>
      <label>操作用户ID<input type="number" min={1} value={draft.actor_id} onChange={e => setDraft({...draft, actor_id: e.target.value})} /></label>
      
      <label>开始时间<input type="datetime-local" value={draft.since} onChange={e => setDraft({...draft, since: e.target.value})} /></label>
      <label>结束时间<input type="datetime-local" value={draft.until} onChange={e => setDraft({...draft, until: e.target.value})} /></label>
      <label>日志级别<select value={draft.level} onChange={e => setDraft({...draft, level: e.target.value})}><option value="">全部</option><option value="INFO">信息</option><option value="WARNING">受限/警告</option><option value="ERROR">系统错误</option></select></label>
      <button disabled={loading || exporting}>查询</button>
    </form>
    <button onClick={download} disabled={loading || exporting}>{exporting ? '正在导出…' : '导出已查询条件的脱敏诊断'}</button>
    <p>日志仅包含排查元数据，不含业务正文、密码、授权文件或银行信息。查询与导出有扫描/条数上限；导出包的 summary.json 标明范围和是否截断。</p>
    <p>本次进程启动：{health.process_started_at || '等待健康状态'}；恢复可写后会尝试记录健康摘要。</p>
    {drops > 0 && <p role="alert">本次进程已有 {drops} 条日志写入失败；最近时间：{health.last_log_failure_at}，原因：{health.last_log_failure_code}。请检查磁盘和目录权限。</p>}
    {error && <p role="alert" className="text-destructive">{error}</p>}
    {result.truncated && <p role="status">本次检索尚未完整。使用“继续检索”查询固定快照中的后续记录；尾部半行须重新查询。</p>}
    <div className="overflow-auto [&_table]:min-w-[1000px] [&_td]:p-3 [&_th]:p-3 [&_td]:border-b [&_th]:text-left [&_table]:text-sm"><table><thead><tr><th>北京时间</th><th>用户 / 授权方</th><th>结果类别</th><th>操作与耗时</th><th>请求编号 / 排查代码</th></tr></thead><tbody>
      {result.items.map((row, index) => <tr key={`${row.timestamp}-${index}`}>
        <td>{new Date(row.timestamp).toLocaleString('zh-CN', {timeZone: 'Asia/Shanghai', hour12: false})}</td>
        <td>{row.actor_id ? `用户 #${row.actor_id}` : '未识别用户'}<br/>{row.identity_verified ? `${row.customer_name || ''}（已核验）` : ''}<br/>{row.instance_id || row.client_ip || '-'}</td>
        <td>{groups[row.category || ''] || levels[row.level] || '运行事件'}<br/>{levels[row.level] || row.level}</td>
        <td>{row.route || row.event}<br/>{row.status_code || ''} · {row.duration_ms ?? '-'} 毫秒</td>
        <td style={{overflowWrap:'anywhere'}}>{row.request_id || '-'}<br/>{row.reason_code || ''}{row.exception_type && <details><summary>故障位置</summary>{row.exception_type}<br/>{row.exception_location}</details>}</td>
      </tr>)}
    </tbody></table></div>
    {!loading && !result.items.length && <p>本次暂未找到匹配记录；有继续检索按钮时不能据此判断全部历史没有记录。未抵达服务器的网络错误不会产生服务器日志。</p>}
    <p>已应用范围：{result.since ? new Date(result.since).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}) : '正在查询'} — {result.until ? new Date(result.until).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}) : ''}；修改输入后须点击查询，导出使用此范围。</p>
    <p>当前保留范围：{result.available_range?.earliest || '尚未发现'} — {result.available_range?.latest || '尚未发现'}。{result.retention_policy}</p>
    {result.scan_complete && <p>已完整检索此次快照中保留的日志。</p>}
    <button disabled={!result.next_cursor || loading || exporting} onClick={() => setCursor(result.next_cursor || null)}>继续检索</button>
  </section>
}
