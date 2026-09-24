import * as React from "react"
import { cn } from "@/lib/utils"

interface MoneyInputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange'> {
  value: number
  onChange: (value: number) => void
  /** 显示的前缀，如 "¥" */
  prefix?: string
}

function formatWithSeparator(value: number): string {
  if (value === 0) return ''
  return value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function parseFormatted(raw: string): number {
  // 移除所有千分位逗号和非数字字符
  const cleaned = raw.replace(/[^\d.]/g, '')
  const parsed = parseFloat(cleaned)
  return isNaN(parsed) ? 0 : parsed
}

const MoneyInput = React.forwardRef<HTMLInputElement, MoneyInputProps>(
  ({ className, value, onChange, prefix, disabled, ...props }, ref) => {
    // 内部显示用的字符串（带千分位）
    const [displayValue, setDisplayValue] = React.useState(() => formatWithSeparator(value))
    // 是否正在编辑（focus 状态）
    const [editing, setEditing] = React.useState(false)

    // 外部 value 变化时（保存后重置等），同步显示
    React.useEffect(() => {
      if (!editing) {
        setDisplayValue(formatWithSeparator(value))
      }
    }, [value, editing])

    const handleFocus = (e: React.FocusEvent<HTMLInputElement>) => {
      setEditing(true)
      // focus 时显示原始数字（不带逗号），方便修改
      setDisplayValue(value === 0 ? '' : value.toString())
      // 全选
      e.target.select()
      props.onFocus?.(e)
    }

    const handleBlur = (e: React.FocusEvent<HTMLInputElement>) => {
      setEditing(false)
      const parsed = parseFormatted(displayValue)
      setDisplayValue(formatWithSeparator(parsed))
      onChange(parsed)
      props.onBlur?.(e)
    }

    const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      const raw = e.target.value
      // 允许输入：数字、一个小数点
      if (/^[\d.]*$/.test(raw)) {
        // 防止多个小数点
        const parts = raw.split('.')
        const sanitized = parts.length > 2
          ? parts[0] + '.' + parts.slice(1).join('')
          : raw
        setDisplayValue(sanitized)
      }
    }

    return (
      <div className="relative">
        {prefix && (
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground text-sm pointer-events-none">
            {prefix}
          </span>
        )}
        <input
          type="text"
          inputMode="decimal"
          className={cn(
            "flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background",
            "placeholder:text-muted-foreground",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
            "disabled:cursor-not-allowed disabled:opacity-50",
            // 隐藏浏览器原生增减按钮
            "[appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none",
            prefix && "pl-7",
            className
          )}
          value={displayValue}
          onChange={handleChange}
          onFocus={handleFocus}
          onBlur={handleBlur}
          disabled={disabled}
          ref={ref}
          {...props}
        />
      </div>
    )
  }
)
MoneyInput.displayName = "MoneyInput"

export { MoneyInput }
