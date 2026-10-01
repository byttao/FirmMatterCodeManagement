export const billingLabels: Record<string,string> = {
  title:'开票抬头',tax_id:'税号 / 标识',buyer_type:'主体类型',registered_address:'注册地址',
  registered_phone:'注册电话',bank_name:'开户银行',bank_account:'银行账号',contact_name:'联系人',
  recipient_phone:'收票电话',recipient_email:'收票邮箱',invoice_preference:'发票偏好',note:'备注',
  version_no:'资料版本',verified_by:'核验人',verified_at:'核验时间（北京时间）',
}

export function billingValue(key: string, value: unknown): string {
  if(value===null||value===undefined||value==='')return '-'
  if(key==='verified_at')return new Date(String(value)+'Z').toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})
  const choices: Record<string,string> = {enterprise:'企业',individual:'个人',overseas:'境外',normal:'普通发票',special:'专用发票',other:'其他',unspecified:'未指定'}
  return ['buyer_type','invoice_preference'].includes(key)?choices[String(value)]||String(value):String(value)
}

export function localDate(): string {
  const date=new Date()
  return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`
}
