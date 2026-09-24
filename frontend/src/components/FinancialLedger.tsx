import { useEffect, useState } from 'react'
import { format } from 'date-fns'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import { financeApi, projectApi } from '@/api/auth'
import type { FinanceKind, FinancialEntry, FinancialEntryInput, Project } from '@/types'
import { formatCurrency } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { DatePicker } from '@/components/ui/date-picker'
import { MoneyInput } from '@/components/ui/money-input'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'

interface Props {
  project: Project
  canEdit: boolean
  onProjectChange: (project: Project) => void
}

type Editor = { kind: FinanceKind; entry: FinancialEntry | null } | null

export function FinancialLedger({ project, canEdit, onProjectChange }: Props) {
  const [invoices, setInvoices] = useState<FinancialEntry[]>([])
  const [receipts, setReceipts] = useState<FinancialEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [editor, setEditor] = useState<Editor>(null)
  const [form, setForm] = useState<FinancialEntryInput>({ amount: 0, occurred_on: '', reference: '', note: '' })

  const load = async () => {
    const [invoiceResult, receiptResult] = await Promise.all([
      financeApi.list(project.id, 'invoices'), financeApi.list(project.id, 'receipts'),
    ])
    setInvoices(invoiceResult.data)
    setReceipts(receiptResult.data)
    setLoading(false)
  }

  useEffect(() => {
    load().catch(() => {
      setLoading(false)
      alert('财务记录加载失败')
    })
  }, [project.id])

  const openEditor = (kind: FinanceKind, entry: FinancialEntry | null = null) => {
    setForm({
      amount: entry?.amount ?? 0,
      occurred_on: entry?.occurred_on ?? format(new Date(), 'yyyy-MM-dd'),
      reference: entry?.reference ?? '',
      note: entry?.note ?? '',
    })
    setEditor({ kind, entry })
  }

  const refresh = async () => {
    const [_, current] = await Promise.all([load(), projectApi.get(project.id)])
    onProjectChange(current.data)
  }

  const save = async () => {
    if (!editor || saving) return
    if (!Number.isFinite(form.amount) || form.amount <= 0 || !/^\d+(\.\d{1,2})?$/.test(String(form.amount))) {
      alert('请输入大于零且最多两位小数的金额')
      return
    }
    if (!form.occurred_on && !editor.entry?.is_legacy) {
      alert('请选择日期')
      return
    }
    setSaving(true)
    try {
      if (editor.entry) {
        await financeApi.update(project.id, editor.kind, editor.entry.id, form)
      } else {
        await financeApi.create(project.id, editor.kind, form)
      }
      await refresh()
      setEditor(null)
    } catch (err: any) {
      alert(err.response?.data?.detail || '财务记录保存失败')
    } finally {
      setSaving(false)
    }
  }

  const remove = async (kind: FinanceKind, entry: FinancialEntry) => {
    if (!window.confirm(`确认删除这笔${kind === 'invoices' ? '开票' : '收款'}记录？`)) return
    try {
      await financeApi.delete(project.id, kind, entry.id)
      await refresh()
    } catch (err: any) {
      alert(err.response?.data?.detail || '删除失败')
    }
  }

  const sections: { kind: FinanceKind; title: string; entries: FinancialEntry[]; total: number }[] = [
    { kind: 'invoices', title: '开票记录', entries: invoices, total: project.invoiced_amount },
    { kind: 'receipts', title: '收款记录', entries: receipts, total: project.received_amount },
  ]

  return (
    <div className="space-y-7">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-sm">
        <div><div className="text-muted-foreground">合同金额</div><strong>{formatCurrency(project.contract_amount)}</strong></div>
        <div><div className="text-muted-foreground">已开票</div><strong>{formatCurrency(project.invoiced_amount)}</strong></div>
        <div><div className="text-muted-foreground">未开票</div><strong>{formatCurrency(project.uninvoiced_amount)}</strong></div>
        <div><div className="text-muted-foreground">已收款</div><strong>{formatCurrency(project.received_amount)}</strong></div>
        <div><div className="text-muted-foreground">未收款</div><strong>{formatCurrency(project.unreceived_amount)}</strong></div>
      </div>

      {sections.map(section => (
        <section key={section.kind} className="space-y-2">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold">{section.title} <span className="font-normal text-muted-foreground">合计 {formatCurrency(section.total)}</span></h3>
            {canEdit && <Button type="button" size="sm" variant="outline" onClick={() => openEditor(section.kind)}><Plus className="w-4 h-4 mr-1" />新增</Button>}
          </div>
          <Table>
            <TableHeader><TableRow>
              <TableHead className="w-28">日期</TableHead><TableHead className="w-32">金额</TableHead>
              <TableHead className="w-40">{section.kind === 'invoices' ? '发票号码' : '到账凭证'}</TableHead>
              <TableHead>备注</TableHead>{canEdit && <TableHead className="w-24 text-right">操作</TableHead>}
            </TableRow></TableHeader>
            <TableBody>
              {loading ? <TableRow><TableCell colSpan={canEdit ? 5 : 4}>加载中...</TableCell></TableRow> :
                section.entries.length === 0 ? <TableRow><TableCell colSpan={canEdit ? 5 : 4} className="text-muted-foreground">暂无记录</TableCell></TableRow> :
                section.entries.map(entry => <TableRow key={entry.id}>
                  <TableCell>{entry.occurred_on || '日期未登记'}</TableCell>
                  <TableCell className="font-medium tabular-nums">{formatCurrency(entry.amount)}</TableCell>
                  <TableCell>{entry.reference || '-'}</TableCell>
                  <TableCell>{entry.is_legacy ? `旧版汇总数据${entry.note && entry.note !== '旧版汇总数据' ? ` · ${entry.note}` : ''}` : (entry.note || '-')}</TableCell>
                  {canEdit && <TableCell className="text-right whitespace-nowrap">
                    <Button type="button" size="icon" variant="ghost" title="编辑记录" onClick={() => openEditor(section.kind, entry)}><Pencil className="w-4 h-4" /></Button>
                    <Button type="button" size="icon" variant="ghost" title="删除记录" onClick={() => remove(section.kind, entry)}><Trash2 className="w-4 h-4" /></Button>
                  </TableCell>}
                </TableRow>)}
            </TableBody>
          </Table>
        </section>
      ))}

      <Dialog open={!!editor} onOpenChange={open => { if (!open && !saving) setEditor(null) }}>
        <DialogContent>
          <DialogHeader><DialogTitle>{editor?.entry ? '编辑' : '新增'}{editor?.kind === 'invoices' ? '开票' : '收款'}记录</DialogTitle></DialogHeader>
          <div className="grid gap-4 py-2">
            <div className="space-y-2"><Label>金额</Label><MoneyInput value={form.amount} onChange={amount => setForm(prev => ({ ...prev, amount }))} /></div>
            <div className="space-y-2"><Label>日期</Label><DatePicker value={form.occurred_on || ''} onChange={occurred_on => setForm(prev => ({ ...prev, occurred_on }))} /></div>
            <div className="space-y-2"><Label>{editor?.kind === 'invoices' ? '发票号码' : '到账凭证'}（选填）</Label><Input maxLength={100} value={form.reference || ''} onChange={e => setForm(prev => ({ ...prev, reference: e.target.value }))} /></div>
            <div className="space-y-2"><Label>备注（选填）</Label><Input maxLength={500} value={form.note || ''} onChange={e => setForm(prev => ({ ...prev, note: e.target.value }))} /></div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setEditor(null)} disabled={saving}>取消</Button>
            <Button type="button" onClick={save} disabled={saving}>{saving ? '保存中...' : '保存记录'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
