import { useEffect, useState, useCallback, useRef } from 'react'
import { numberedYearApi, NumberedYear, Firm, ReportRule, ReportType } from '@/api/numberedYear'
import { useAuth } from '@/store/AuthContext'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Plus, Edit, Trash2, Loader2, Settings, ChevronRight, ChevronDown, Folder, FileText, Layers } from 'lucide-react'

// 解析模板中的占位符，用于高亮显示
const parseTemplate = (template: string) => {
  const parts: { text: string; isPlaceholder: boolean }[] = []
  const regex = /(\{yyyy\}|\{yy\}|\{n+\})/g
  let lastIndex = 0
  let match

  while ((match = regex.exec(template)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ text: template.slice(lastIndex, match.index), isPlaceholder: false })
    }
    parts.push({ text: match[0], isPlaceholder: true })
    lastIndex = regex.lastIndex
  }

  if (lastIndex < template.length) {
    parts.push({ text: template.slice(lastIndex), isPlaceholder: false })
  }

  return parts
}

// 从模板解析编号位数
const parseSequenceDigits = (template: string): number => {
  const match = template.match(/\{(n+)\}/)
  return match ? match[1].length : 3
}

// 高亮渲染占位符的纯函数，返回 HTML 字符串（供 innerHTML 使用）
function buildHighlightedHTML(text: string): string {
  const parts = parseTemplate(text)
  return parts
    .map(p =>
      p.isPlaceholder
        ? `<span class="bg-yellow-200 dark:bg-yellow-800 text-yellow-900 dark:text-yellow-100 px-1 rounded font-semibold">${escapeHtml(p.text)}</span>`
        : escapeHtml(p.text)
    )
    .join('')
}

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

// 模板编辑器组件 - contentEditable div 完全由原生 DOM 管理，不放 React 子节点
function TemplateEditor({
  value,
  onChange,
  placeholder,
}: {
  value: string
  onChange: (value: string) => void
  placeholder?: string
}) {
  const editorRef = useRef<HTMLDivElement>(null)
  const [isFocused, setIsFocused] = useState(false)
  const isUpdatingRef = useRef(false)

  // 初始化编辑器内容（仅在挂载时执行一次）
  useEffect(() => {
    const editor = editorRef.current
    if (!editor) return
    editor.textContent = value
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // 外部 value 变化时同步到编辑器（仅在非用户输入时更新）
  useEffect(() => {
    const editor = editorRef.current
    if (!editor) return
    if (isUpdatingRef.current) return // 跳过用户输入触发的更新
    if (editor.textContent !== value) {
      editor.textContent = value
    }
    editor.innerHTML = buildHighlightedHTML(value) || ''
  }, [value])

  // 处理输入事件
  const handleInput = useCallback(() => {
    isUpdatingRef.current = true
    const text = editorRef.current?.textContent || ''
    onChange(text)
    // 短暂延迟后重置标记，让外部更新能正常生效
    setTimeout(() => { isUpdatingRef.current = false }, 50)
  }, [onChange])

  // 计算光标偏移量
  const getTextOffset = (element: HTMLElement, range: Range): number => {
    const treeWalker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT, null)
    let offset = 0
    while (treeWalker.nextNode()) {
      if (treeWalker.currentNode === range.startContainer) {
        return offset + range.startOffset
      }
      offset += treeWalker.currentNode.textContent?.length || 0
    }
    return offset
  }

  // 恢复光标位置（带组件卸载保护）
  const restoreCursor = useCallback((editor: HTMLElement, targetOffset: number) => {
    if (!document.contains(editor)) return
    const selection = window.getSelection()
    if (!selection) return

    const treeWalker = document.createTreeWalker(editor, NodeFilter.SHOW_TEXT, null)
    let currentOffset = 0
    let targetNode: Node | null = null
    let offsetInNode = 0

    while (treeWalker.nextNode()) {
      const nodeLength = treeWalker.currentNode.textContent?.length || 0
      if (currentOffset + nodeLength >= targetOffset) {
        targetNode = treeWalker.currentNode
        offsetInNode = targetOffset - currentOffset
        break
      }
      currentOffset += nodeLength
    }

    if (targetNode) {
      const range = document.createRange()
      range.setStart(targetNode, Math.min(offsetInNode, targetNode.textContent?.length || 0))
      range.collapse(true)
      selection.removeAllRanges()
      selection.addRange(range)
    }
  }, [])

  // 处理快捷键
  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLDivElement>) => {
    const editor = editorRef.current
    if (!editor) return

    const selection = window.getSelection()
    if (!selection || selection.rangeCount === 0) return

    const range = selection.getRangeAt(0)
    const cursorOffset = getTextOffset(editor, range)
    const text = editor.textContent || ''

    if (e.key === 'y' && text[cursorOffset - 1] === '{' && !e.shiftKey) {
      e.preventDefault()
      const newValue = text.slice(0, cursorOffset) + 'yyyy}' + text.slice(cursorOffset)
      // 先更新 DOM，再通知外部
      isUpdatingRef.current = true
      editor.textContent = newValue
      editor.innerHTML = buildHighlightedHTML(newValue)
      onChange(newValue)
      setTimeout(() => {
        isUpdatingRef.current = false
        restoreCursor(editor, cursorOffset + 5)
      }, 0)
      return
    }

    if (e.key === 'n' && text[cursorOffset - 1] === '{') {
      e.preventDefault()
      const newValue = text.slice(0, cursorOffset) + 'nnn}' + text.slice(cursorOffset)
      isUpdatingRef.current = true
      editor.textContent = newValue
      editor.innerHTML = buildHighlightedHTML(newValue)
      onChange(newValue)
      setTimeout(() => {
        isUpdatingRef.current = false
        restoreCursor(editor, cursorOffset + 4)
      }, 0)
      return
    }

    if (e.key === 'Y' && text[cursorOffset - 1] === '{') {
      e.preventDefault()
      const newValue = text.slice(0, cursorOffset) + 'yy}' + text.slice(cursorOffset)
      isUpdatingRef.current = true
      editor.textContent = newValue
      editor.innerHTML = buildHighlightedHTML(newValue)
      onChange(newValue)
      setTimeout(() => {
        isUpdatingRef.current = false
        restoreCursor(editor, cursorOffset + 3)
      }, 0)
      return
    }
  }, [onChange, restoreCursor])

  return (
    <div className="space-y-2">
      <div
        ref={editorRef}
        contentEditable
        suppressContentEditableWarning
        onFocus={() => setIsFocused(true)}
        onBlur={(e) => {
          setIsFocused(false)
          const text = e.currentTarget.textContent || ''
          if (text !== value) onChange(text)
        }}
        onInput={handleInput}
        onKeyDown={handleKeyDown}
        className={`
          min-h-[48px] p-3 border rounded-lg font-mono text-sm
          whitespace-pre-wrap break-words outline-none
          transition-all duration-150 bg-background
          ${isFocused
            ? 'ring-2 ring-ring ring-offset-2 border-primary'
            : 'hover:border-muted-foreground/50 border-input'
          }
        `}
        data-placeholder={placeholder}
      />

      <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          <Badge variant="outline" className="bg-yellow-50 dark:bg-yellow-900/20 text-yellow-700 dark:text-yellow-300 px-1.5 py-0.5 font-mono">{'{yyyy}'}</Badge>
          四位年份
        </span>
        <span className="flex items-center gap-1">
          <Badge variant="outline" className="bg-yellow-50 dark:bg-yellow-900/20 text-yellow-700 dark:text-yellow-300 px-1.5 py-0.5 font-mono">{'{yy}'}</Badge>
          两位年份
        </span>
        <span className="flex items-center gap-1">
          <Badge variant="outline" className="bg-yellow-50 dark:bg-yellow-900/20 text-yellow-700 dark:text-yellow-300 px-1.5 py-0.5 font-mono">{'{nnn}'}</Badge>
          编号（位数=n的个数，如 SD{'{nnn}'}）
        </span>
        <span className="text-muted-foreground/60">提示：输入 {'{'} 后按 y/Y/n 可快速插入占位符</span>
      </div>

      <style>{`
        [contenteditable]:empty:before {
          content: attr(data-placeholder);
          color: var(--muted-foreground);
          opacity: 0.5;
        }
      `}</style>
    </div>
  )
}

export default function FiscalYearConfigPage() {
  const { user } = useAuth()
  const [data, setData] = useState<NumberedYear[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedYears, setExpandedYears] = useState<Set<number>>(new Set())
  const [expandedFirms, setExpandedFirms] = useState<Set<number>>(new Set())

  // 选中状态
  const [selectedYear, setSelectedYear] = useState<NumberedYear | null>(null)
  const [selectedFirm, setSelectedFirm] = useState<Firm | null>(null)
  const [selectedRule, setSelectedRule] = useState<ReportRule | null>(null)
  const [selectedReportType, setSelectedReportType] = useState<ReportType | null>(null)

  // 对话框状态
  const [showYearDialog, setShowYearDialog] = useState(false)
  const [showFirmDialog, setShowFirmDialog] = useState(false)
  const [showRuleDialog, setShowRuleDialog] = useState(false)
  const [showReportTypeDialog, setShowReportTypeDialog] = useState(false)
  const [editingRule, setEditingRule] = useState<ReportRule | null>(null)
  const [editingReportType, setEditingReportType] = useState<ReportType | null>(null)
  const [saving, setSaving] = useState(false)

  // 删除确认
  const [deleteTarget, setDeleteTarget] = useState<{ type: string; id: number; name: string } | null>(null)
  const [deleteLoading, setDeleteLoading] = useState(false)

  // 表单数据
  const [yearForm, setYearForm] = useState({ year: new Date().getFullYear() + 1 })
  const [firmForm, setFirmForm] = useState({ fiscalYearId: 0, firm: '' })
  const [ruleForm, setRuleForm] = useState({
    fiscalYearFirmId: 0,
    ruleName: '',
    template: '',
    sequenceDigits: 3
  })
  // 用 ref 追踪 ruleForm，避免内联 onChange 的闭包问题
  const ruleFormRef = useRef(ruleForm)
  useEffect(() => { ruleFormRef.current = ruleForm }, [ruleForm])
  const [reportTypeForm, setReportTypeForm] = useState({
    fiscalYearFirmId: 0,
    reportType: '',
    ruleId: 0
  })

  const canManage = user?.role === 'admin' || user?.role === 'admin_staff'

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    try {
      const res = await numberedYearApi.list()
      const list = Array.isArray(res.data) ? res.data : []
      setData(list)
      // 默认展开第一个年度
      if (list.length > 0) {
        setExpandedYears(new Set([list[0].id]))
      }
    } catch (err) {
      console.error('加载数据失败', err)
      setData([])
    } finally {
      setLoading(false)
    }
  }

  // 在树形数据中按 ID 查找业务类型
  const findReportTypeById = (years: NumberedYear[], rtId: number): ReportType | null => {
    for (const year of years) {
      for (const firm of year.firms) {
        const found = firm.report_types.find(rt => rt.id === rtId)
        if (found) return found
      }
    }
    return null
  }

  // 展开/折叠
  const toggleYear = (yearId: number) => {
    const newSet = new Set(expandedYears)
    if (newSet.has(yearId)) {
      newSet.delete(yearId)
    } else {
      newSet.add(yearId)
    }
    setExpandedYears(newSet)
  }

  const toggleFirm = (firmId: number) => {
    const newSet = new Set(expandedFirms)
    if (newSet.has(firmId)) {
      newSet.delete(firmId)
    } else {
      newSet.add(firmId)
    }
    setExpandedFirms(newSet)
  }

  // 选中处理
  const selectYear = (year: NumberedYear) => {
    setSelectedYear(year)
    setSelectedFirm(null)
    setSelectedRule(null)
    setSelectedReportType(null)
  }

  const selectFirm = (year: NumberedYear, firm: Firm) => {
    setSelectedYear(year)
    setSelectedFirm(firm)
    setSelectedRule(null)
    setSelectedReportType(null)
  }

  const selectRule = (year: NumberedYear, firm: Firm, rule: ReportRule) => {
    setSelectedYear(year)
    setSelectedFirm(firm)
    setSelectedRule(rule)
    setSelectedReportType(null)
  }

  const selectReportType = (year: NumberedYear, firm: Firm, rt: ReportType) => {
    setSelectedYear(year)
    setSelectedFirm(firm)
    setSelectedRule(null)
    setSelectedReportType(rt)
  }

  // 打开对话框
  const openYearDialog = () => {
    setYearForm({ year: new Date().getFullYear() + 1 })
    setShowYearDialog(true)
  }

  const openFirmDialog = (year: NumberedYear) => {
    setFirmForm({ fiscalYearId: year.id, firm: '' })
    setShowFirmDialog(true)
  }

  const openRuleDialog = (firm: Firm) => {
    setEditingRule(null)
    setRuleForm({
      fiscalYearFirmId: firm.id,
      ruleName: '',
      template: '{yyyy}-{nnn}',
      sequenceDigits: 3
    })
    setShowRuleDialog(true)
  }

  const openEditRuleDialog = (rule: ReportRule) => {
    setEditingRule(rule)
    setRuleForm({
      fiscalYearFirmId: ruleForm.fiscalYearFirmId,
      ruleName: rule.rule_name,
      template: rule.template,
      sequenceDigits: rule.sequence_digits
    })
    setShowRuleDialog(true)
  }

  const openReportTypeDialog = (firm: Firm) => {
    setEditingReportType(null)
    const defaultRuleId = firm.rules[0]?.id || 0
    setReportTypeForm({
      fiscalYearFirmId: firm.id,
      reportType: '',
      ruleId: defaultRuleId
    })
    setShowReportTypeDialog(true)
  }

  const openEditReportTypeDialog = (rt: ReportType, firm: Firm) => {
    setEditingReportType(rt)
    setReportTypeForm({
      fiscalYearFirmId: firm.id,
      reportType: rt.report_type,
      ruleId: rt.rule_id
    })
    setShowReportTypeDialog(true)
  }

  // 提交表单
  const handleCreateYear = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    try {
      await numberedYearApi.createYear(yearForm.year)
      loadData()
      setShowYearDialog(false)
    } catch (err: any) {
      alert(err.response?.data?.detail || '创建失败')
    } finally {
      setSaving(false)
    }
  }

  const handleCreateFirm = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    try {
      await numberedYearApi.createFirm(firmForm.fiscalYearId, firmForm.firm)
      loadData()
      setShowFirmDialog(false)
    } catch (err: any) {
      alert(err.response?.data?.detail || '创建失败')
    } finally {
      setSaving(false)
    }
  }

  const handleCreateRule = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    try {
      const savedRuleId = editingRule?.id
      if (editingRule) {
        await numberedYearApi.updateRule(editingRule.id, {
          rule_name: ruleForm.ruleName,
          template: ruleForm.template,
          sequence_digits: ruleForm.sequenceDigits
        })
      } else {
        await numberedYearApi.createRule({
          fiscal_year_firm_id: ruleForm.fiscalYearFirmId,
          rule_name: ruleForm.ruleName,
          template: ruleForm.template,
          sequence_digits: ruleForm.sequenceDigits,
        })
      }
      // 刷新数据后恢复选中状态
      await loadData()
      setShowRuleDialog(false)
      if (savedRuleId && editingRule && selectedFirm && selectedYear) {
        const updatedRule = selectedFirm.rules.find(r => r.id === savedRuleId)
        if (updatedRule) setSelectedRule(updatedRule)
      } else if (!editingRule) {
        setSelectedRule(null)
      }
    } catch (err: any) {
      alert(err.response?.data?.detail || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleCreateReportType = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    try {
      if (editingReportType) {
        await numberedYearApi.updateReportType(editingReportType.id, {
          report_type: reportTypeForm.reportType,
          rule_id: reportTypeForm.ruleId,
        })
      } else {
        await numberedYearApi.createReportType({
          fiscal_year_firm_id: reportTypeForm.fiscalYearFirmId,
          report_type: reportTypeForm.reportType,
          rule_id: reportTypeForm.ruleId,
        })
      }
      // 刷新数据后，在最新数据中恢复选中状态（编辑时用表单值，创建时清空）
      const savedRtId = editingReportType?.id
      await loadData()
      setShowReportTypeDialog(false)
      if (savedRtId && editingReportType) {
        // 在刷新后的数据中查找已更新的业务类型并重新选中
        const updatedRt = findReportTypeById(data, savedRtId)
        if (updatedRt && selectedFirm && selectedYear) {
          setSelectedReportType(updatedRt)
        }
      } else if (!editingReportType) {
        setSelectedReportType(null)
      }
    } catch (err: any) {
      alert(err.response?.data?.detail || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  // 删除
  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeleteLoading(true)
    try {
      switch (deleteTarget.type) {
        case 'year':
          await numberedYearApi.deleteYear(deleteTarget.id)
          break
        case 'firm':
          await numberedYearApi.deleteFirm(deleteTarget.id)
          break
        case 'rule':
          await numberedYearApi.deleteRule(deleteTarget.id)
          break
        case 'reportType':
          await numberedYearApi.deleteReportType(deleteTarget.id)
          break
      }
      setDeleteTarget(null)
      loadData()
    } catch (err: any) {
      alert(err.response?.data?.detail || '删除失败')
    } finally {
      setDeleteLoading(false)
    }
  }

  // 预览编号
  const previewReportNo = (template: string, year: number) => {
    let preview = template
    const seqDigits = parseSequenceDigits(template)
    const seqStr = '1'.padStart(seqDigits, '0')

    preview = preview.replace(/\{yyyy\}/g, year.toString())
    preview = preview.replace(/\{yy\}/g, year.toString().slice(-2))
    preview = preview.replace(/\{n+\}/g, seqStr)

    return preview
  }

  if (!canManage) {
    return (
      <div className="p-6">
        <h1 className="text-2xl font-bold mb-4">编号年度配置</h1>
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <p className="text-yellow-800">您没有权限访问编号年度配置功能</p>
        </div>
      </div>
    )
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">编号年度配置</h1>
          <p className="text-muted-foreground">管理年度、事务所、业务类型和编号规则</p>
        </div>
        <Button onClick={openYearDialog}>
          <Plus className="w-4 h-4 mr-2" />
          添加年度
        </Button>
      </div>

      <div className="flex gap-6">
        {/* 左侧：树形结构 */}
        <div className="w-80 border rounded-lg bg-card">
          <div className="p-3 border-b bg-muted/50">
            <h3 className="font-medium text-sm">结构树</h3>
          </div>
          <div className="p-2 max-h-[600px] overflow-y-auto">
            {loading ? (
              <div className="flex items-center justify-center h-32">
                <Loader2 className="w-6 h-6 animate-spin" />
              </div>
            ) : data.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                <Folder className="w-8 h-8 mx-auto mb-2 opacity-50" />
                <p className="text-sm">暂无数据</p>
                <p className="text-xs mt-1">点击上方"添加年度"开始</p>
              </div>
            ) : (
              <div className="space-y-1">
                {data.map(year => (
                  <div key={year.id}>
                    {/* 年度节点 */}
                    <div
                      className={`group flex items-center gap-1 p-2 rounded cursor-pointer hover:bg-muted ${selectedYear?.id === year.id && !selectedFirm ? 'bg-muted' : ''}`}
                      onClick={() => selectYear(year)}
                    >
                      <button
                        onClick={(e) => { e.stopPropagation(); toggleYear(year.id) }}
                        className="p-0.5 hover:bg-muted-foreground/20 rounded"
                      >
                        {expandedYears.has(year.id) ?
                          <ChevronDown className="w-4 h-4" /> :
                          <ChevronRight className="w-4 h-4" />
                        }
                      </button>
                      <Layers className="w-4 h-4 text-blue-600" />
                      <span className="font-medium">{year.year} 年</span>
                      <Badge variant="outline" className="ml-auto text-xs">{year.firms.length}</Badge>
                      <button
                        onClick={(e) => { e.stopPropagation(); openFirmDialog(year) }}
                        className="p-1 hover:bg-muted-foreground/20 rounded opacity-0 group-hover:opacity-100"
                        title="添加事务所"
                      >
                        <Plus className="w-3 h-3" />
                      </button>
                    </div>

                    {/* 展开的事务所 */}
                    {expandedYears.has(year.id) && (
                      <div className="ml-6 space-y-1">
                        {year.firms.map(firm => (
                          <div key={firm.id} className="group">
                            {/* 事务所节点 */}
                            <div
                              className={`group flex items-center gap-1 p-2 rounded cursor-pointer hover:bg-muted ${selectedFirm?.id === firm.id && !selectedRule && !selectedReportType ? 'bg-muted' : ''}`}
                              onClick={() => selectFirm(year, firm)}
                            >
                              <button
                                onClick={(e) => { e.stopPropagation(); toggleFirm(firm.id) }}
                                className="p-0.5 hover:bg-muted-foreground/20 rounded"
                              >
                                {expandedFirms.has(firm.id) ?
                                  <ChevronDown className="w-4 h-4" /> :
                                  <ChevronRight className="w-4 h-4" />
                                }
                              </button>
                              <Folder className="w-4 h-4 text-orange-600" />
                              <span>{firm.firm}</span>
                              <button
                                onClick={(e) => { e.stopPropagation(); openRuleDialog(firm) }}
                                className="ml-auto p-1 hover:bg-muted-foreground/20 rounded opacity-0 group-hover:opacity-100"
                                title="添加规则"
                              >
                                <Plus className="w-3 h-3" />
                              </button>
                            </div>

                            {/* 展开的规则和业务类型 */}
                            {expandedFirms.has(firm.id) && (
                              <div className="ml-6 space-y-1">
                                {/* 编号规则 */}
                                {firm.rules.map(rule => (
                                  <div
                                    key={rule.id}
                                    className={`flex items-center gap-1 p-2 rounded cursor-pointer hover:bg-muted text-sm ${selectedRule?.id === rule.id ? 'bg-muted' : ''}`}
                                    onClick={() => selectRule(year, firm, rule)}
                                  >
                                    <FileText className="w-4 h-4 text-green-600" />
                                    <span className="truncate">{rule.rule_name}</span>
                                    <span className="text-xs text-muted-foreground ml-auto">
                                      {rule.current_sequence}
                                    </span>
                                  </div>
                                ))}
                                {/* 业务类型 */}
                                {firm.report_types.map(rt => (
                                  <div
                                    key={rt.id}
                                    className={`flex items-center gap-1 p-2 rounded cursor-pointer hover:bg-muted text-sm ml-4 ${selectedReportType?.id === rt.id ? 'bg-muted' : ''}`}
                                    onClick={() => selectReportType(year, firm, rt)}
                                  >
                                    <span className="w-2 h-2 rounded-full bg-purple-500" />
                                    <span>{rt.report_type}</span>
                                    <Badge variant="outline" className="ml-auto text-xs">
                                      → {rt.rule_name}
                                    </Badge>
                                  </div>
                                ))}
                                {/* 添加业务类型按钮 */}
                                {firm.rules.length > 0 && (
                                  <button
                                    onClick={() => openReportTypeDialog(firm)}
                                    className="flex items-center gap-1 p-2 rounded cursor-pointer hover:bg-muted text-sm text-muted-foreground w-full"
                                  >
                                    <Plus className="w-3 h-3" />
                                    <span>添加业务类型</span>
                                  </button>
                                )}
                              </div>
                            )}
                          </div>
                        ))}
                        {/* 添加事务所按钮 */}
                        <button
                          onClick={() => openFirmDialog(year)}
                          className="flex items-center gap-1 p-2 rounded cursor-pointer hover:bg-muted text-sm text-muted-foreground w-full"
                        >
                          <Plus className="w-3 h-3" />
                          <span>添加事务所</span>
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* 右侧：详情面板 */}
        <div className="flex-1 border rounded-lg bg-card">
          <div className="p-4 border-b bg-muted/50">
            <h3 className="font-medium">
              {selectedReportType ? '业务类型详情' :
               selectedRule ? '编号规则详情' :
               selectedFirm ? '事务所详情' :
               selectedYear ? '年度详情' : '请选择要编辑的项目'}
            </h3>
          </div>
          <div className="p-6">
            {!selectedYear ? (
              <div className="text-center py-12 text-muted-foreground">
                <Settings className="w-12 h-12 mx-auto mb-4 opacity-50" />
                <p>请从左侧选择年度、事务所、业务类型或编号规则</p>
              </div>
            ) : selectedReportType ? (
              // 业务类型详情
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label className="text-muted-foreground">业务类型</Label>
                    <p className="text-lg font-medium">{selectedReportType.report_type}</p>
                  </div>
                  <div>
                    <Label className="text-muted-foreground">关联规则</Label>
                    <p className="text-lg font-medium">{selectedReportType.rule_name}</p>
                  </div>
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      // 找到当前业务类型所属的事务所
                      const firm = selectedYear?.firms.find(f =>
                        f.report_types.some(rt => rt.id === selectedReportType?.id)
                      )
                      if (firm && selectedReportType) openEditReportTypeDialog(selectedReportType, firm)
                    }}
                  >
                    <Edit className="w-4 h-4 mr-2" />
                    编辑
                  </Button>
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => setDeleteTarget({ type: 'reportType', id: selectedReportType.id, name: selectedReportType.report_type })}
                  >
                    <Trash2 className="w-4 h-4 mr-2" />
                    删除业务类型
                  </Button>
                </div>
              </div>
            ) : selectedRule ? (
              // 编号规则详情
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label className="text-muted-foreground">业务类型</Label>
                    <p className="text-lg font-medium">{selectedRule.rule_name}</p>
                  </div>
                  <div>
                    <Label className="text-muted-foreground">编号位数</Label>
                    <p className="text-lg font-medium">{selectedRule.sequence_digits} 位</p>
                  </div>
                </div>
                <div>
                  <Label className="text-muted-foreground">编号模板</Label>
                  <div className="p-3 bg-muted rounded-lg font-mono text-sm mt-1">
                    {parseTemplate(selectedRule.template).map((part, i) =>
                      part.isPlaceholder ? (
                        <span key={i} className="bg-yellow-200 dark:bg-yellow-800 text-yellow-900 dark:text-yellow-100 px-1 rounded font-semibold">
                          {part.text}
                        </span>
                      ) : (
                        <span key={i}>{part.text}</span>
                      )
                    )}
                  </div>
                </div>
                <div>
                  <Label className="text-muted-foreground">编号示例</Label>
                  <p className="font-mono mt-1">{previewReportNo(selectedRule.template, selectedYear.year)}</p>
                </div>
                <div>
                  <Label className="text-muted-foreground">当前序号</Label>
                  <p className="text-2xl font-bold">{selectedRule.current_sequence}</p>
                </div>
                <div className="flex gap-2">
                  <Button variant="outline" onClick={() => openEditRuleDialog(selectedRule)}>
                    <Edit className="w-4 h-4 mr-2" />
                    编辑规则
                  </Button>
                  <Button
                    variant="destructive"
                    onClick={() => setDeleteTarget({ type: 'rule', id: selectedRule.id, name: selectedRule.rule_name })}
                  >
                    <Trash2 className="w-4 h-4 mr-2" />
                    删除规则
                  </Button>
                </div>
              </div>
            ) : selectedFirm ? (
              // 事务所详情
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label className="text-muted-foreground">事务所</Label>
                    <p className="text-lg font-medium">{selectedFirm.firm}</p>
                  </div>
                  <div>
                    <Label className="text-muted-foreground">编号规则数</Label>
                    <p className="text-lg font-medium">{selectedFirm.rules.length}</p>
                  </div>
                </div>
                <div>
                  <Label className="text-muted-foreground">业务类型数</Label>
                  <p className="text-lg font-medium">{selectedFirm.report_types.length}</p>
                </div>
                <div className="flex gap-2">
                  <Button variant="outline" onClick={() => openRuleDialog(selectedFirm)}>
                    <Plus className="w-4 h-4 mr-2" />
                    添加编号规则
                  </Button>
                  {selectedFirm.rules.length > 0 && (
                    <Button variant="outline" onClick={() => openReportTypeDialog(selectedFirm)}>
                      <Plus className="w-4 h-4 mr-2" />
                      添加业务类型
                    </Button>
                  )}
                  <Button
                    variant="destructive"
                    className="ml-auto"
                    onClick={() => setDeleteTarget({ type: 'firm', id: selectedFirm.id, name: selectedFirm.firm })}
                  >
                    <Trash2 className="w-4 h-4 mr-2" />
                    删除事务所
                  </Button>
                </div>
              </div>
            ) : (
              // 年度详情
              <div className="space-y-4">
                <div>
                  <Label className="text-muted-foreground">年度</Label>
                  <p className="text-lg font-medium">{selectedYear.year} 年</p>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label className="text-muted-foreground">事务所数</Label>
                    <p className="text-lg font-medium">{selectedYear.firms.length}</p>
                  </div>
                  <div>
                    <Label className="text-muted-foreground">编号规则数</Label>
                    <p className="text-lg font-medium">
                      {selectedYear.firms.reduce((sum, f) => sum + f.rules.length, 0)}
                    </p>
                  </div>
                </div>
                <div className="flex gap-2">
                  <Button variant="outline" onClick={() => openFirmDialog(selectedYear)}>
                    <Plus className="w-4 h-4 mr-2" />
                    添加事务所
                  </Button>
                  <Button
                    variant="destructive"
                    className="ml-auto"
                    onClick={() => setDeleteTarget({ type: 'year', id: selectedYear.id, name: `${selectedYear.year}年` })}
                  >
                    <Trash2 className="w-4 h-4 mr-2" />
                    删除年度
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 添加年度对话框 */}
      <Dialog open={showYearDialog} onOpenChange={setShowYearDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>添加年度</DialogTitle>
            <DialogDescription>每个年度可配置多个事务所及其编号规则</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleCreateYear} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="year">年度</Label>
              <Input
                id="year"
                type="number"
                value={yearForm.year}
                onChange={(e) => setYearForm({ year: parseInt(e.target.value) })}
                min={2000}
                max={2100}
                required
              />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setShowYearDialog(false)}>取消</Button>
              <Button type="submit" disabled={saving}>
                {saving && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
                创建
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* 添加事务所对话框 */}
      <Dialog open={showFirmDialog} onOpenChange={setShowFirmDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>添加事务所</DialogTitle>
            <DialogDescription>输入当前年度对应的事务所全称</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleCreateFirm} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="firm">事务所名称</Label>
              <Input
                id="firm"
                value={firmForm.firm}
                onChange={(e) => setFirmForm({ ...firmForm, firm: e.target.value })}
                placeholder="请输入事务所名称"
                required
              />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setShowFirmDialog(false)}>取消</Button>
              <Button type="submit" disabled={saving}>
                {saving && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
                创建
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* 添加/编辑规则对话框 */}
      <Dialog open={showRuleDialog} onOpenChange={setShowRuleDialog}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{editingRule ? '编辑编号规则' : '添加编号规则'}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleCreateRule} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="ruleName">业务类型</Label>
              <Input
                id="ruleName"
                value={ruleForm.ruleName}
                onChange={(e) => setRuleForm({ ...ruleForm, ruleName: e.target.value })}
                placeholder="如：年审编号、专项编号"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="template">编号规则</Label>
              <TemplateEditor
                value={ruleForm.template}
                onChange={(template) => setRuleForm({ ...ruleFormRef.current, template })}
                placeholder="输入编号模板，如：{yyyy}-审-{nnn}"
              />
            </div>
            <div className="space-y-2">
              <Label>编号预览</Label>
              <div className="p-3 bg-muted rounded-lg font-mono text-sm">
                {ruleForm.template ? previewReportNo(ruleForm.template, selectedYear?.year || new Date().getFullYear()) : '-'}
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setShowRuleDialog(false)}>取消</Button>
              <Button type="submit" disabled={saving}>
                {saving && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
                {editingRule ? '保存' : '创建'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* 添加业务类型对话框 */}
      <Dialog open={showReportTypeDialog} onOpenChange={setShowReportTypeDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingReportType ? '编辑业务类型' : '添加业务类型'}</DialogTitle>
            <DialogDescription>业务类型关联到编号规则，多个业务类型可以使用同一个编号规则（共享编号序列）</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleCreateReportType} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="reportType">业务类型名称</Label>
              <Input
                id="reportType"
                value={reportTypeForm.reportType}
                onChange={(e) => setReportTypeForm({ ...reportTypeForm, reportType: e.target.value })}
                placeholder="如：年审、专项、验资、咨询"
                required
              />
              {!editingReportType && <p className="text-xs text-muted-foreground">请输入贵所实际使用的业务类型名称</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="ruleId">关联编号规则</Label>
              <Select
                value={reportTypeForm.ruleId.toString()}
                onValueChange={(v) => setReportTypeForm({ ...reportTypeForm, ruleId: parseInt(v) })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {selectedFirm?.rules.map(rule => (
                    <SelectItem key={rule.id} value={rule.id.toString()}>
                      {rule.rule_name}（当前序号：{rule.current_sequence}）
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                提示：选择相同的编号规则可以让多个业务类型共享编号序列
              </p>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setShowReportTypeDialog(false)}>取消</Button>
              <Button type="submit" disabled={saving}>
                {saving && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
                {editingReportType ? '保存' : '创建'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* 删除确认对话框 */}
      <Dialog open={!!deleteTarget} onOpenChange={() => setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认删除</DialogTitle>
          </DialogHeader>
          <p>确定要删除"{deleteTarget?.name}"吗？此操作不可恢复。</p>
          {deleteTarget?.type === 'year' && (
            <p className="text-sm text-destructive">注意：删除年度会同时删除其下的所有事务所、规则和业务类型！</p>
          )}
          {deleteTarget?.type === 'firm' && (
            <p className="text-sm text-destructive">注意：删除事务所会同时删除其下的所有规则和业务类型！</p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setDeleteTarget(null)}>取消</Button>
            <Button type="button" variant="destructive" onClick={handleDelete} disabled={deleteLoading}>
              {deleteLoading && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
