export type ErrorDetail = { message?: string; code?: string; category?: string; request_id?: string }
const categories: Record<string, string> = { system_error: '系统故障', access_restriction: '登录或权限限制', business_restriction: '操作条件限制', rate_limit: '频率或资源限制' }
export function errorText(status: number, body?: unknown, headerId = ''): string {
  const detail = (body && typeof body === 'object' && 'detail' in body) ? (body as {detail: unknown}).detail : undefined
  const data = detail && typeof detail === 'object' && !Array.isArray(detail) ? detail as ErrorDetail : {}
  const fallback = status === 0 ? '无法连接服务器，请检查网络、服务器地址和服务是否启动' : status >= 500 ? '服务处理失败，请联系管理员排查' : status === 401 ? '登录已失效或账号密码不正确，请重新登录' : status === 403 ? '无权限执行此操作，请联系管理员' : status === 404 ? '请求的记录或接口不存在，请刷新页面' : status === 429 ? '操作过于频繁或服务器正忙，请稍后重试' : status === 422 ? '输入格式或字段不合法，请检查必填项与格式' : '请求未完成，请检查后重试'
  const raw = typeof detail === 'string' ? detail : data.message
  const message = status < 500 && typeof raw === 'string' && /[\u4e00-\u9fff]/.test(raw) ? raw.slice(0, 500) : fallback
  const group = categories[data.category || ''] || (status >= 500 ? '系统故障' : status === 0 ? '连接异常' : status === 401 || status === 403 ? '登录或权限限制' : '操作条件限制')
  const requestId = data.request_id || headerId
  const id = /^[a-f0-9]{32}$/.test(requestId) ? requestId : ''
  const code = /^[a-z][a-z0-9_]{0,63}$/.test(data.code || '') ? data.code : ''
  return `【${group}】${message}${code ? `；错误代码：${code}` : ''}${id ? `；请求编号：${id}（请提供给管理员）` : status === 0 ? '；请求未获响应，请同时记录操作时间和页面' : ''}`
}
