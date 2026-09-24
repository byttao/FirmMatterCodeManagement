import * as React from "react"
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from "lucide-react"
import { cn } from "@/lib/utils"
import { buttonVariants } from "@/components/ui/button"

// 中文星期标题（周一开始）
const WEEK_DAYS = ["一", "二", "三", "四", "五", "六", "日"]

// 中文月份
const MONTH_NAMES = ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"]

function getDaysInMonth(year: number, month: number) {
  return new Date(year, month + 1, 0).getDate()
}

// 获取某月1日是周几（0=周日,...,6=周六），转换为周一=0的偏移
function getFirstDayOffset(year: number, month: number) {
  const day = new Date(year, month, 1).getDay() // 0=周日
  // 转为周一=0
  return (day + 6) % 7
}

function isSameDay(a: Date, b: Date) {
  return a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
}




interface CalendarProps {
  selected?: Date
  onSelect?: (date: Date) => void
  disabled?: (date: Date) => boolean
  month?: Date
  onMonthChange?: (month: Date) => void
  className?: string
  footer?: React.ReactNode
}

function Calendar({
  selected,
  onSelect,
  disabled,
  month,
  onMonthChange,
  className,
  footer,
}: CalendarProps) {
  const today = new Date()

  const [viewYear, setViewYear] = React.useState(
    month?.getFullYear() ?? selected?.getFullYear() ?? today.getFullYear()
  )
  const [viewMonth, setViewMonth] = React.useState(
    month?.getMonth() ?? selected?.getMonth() ?? today.getMonth()
  )

  // 同步外部 month prop
  React.useEffect(() => {
    if (month) {
      setViewYear(month.getFullYear())
      setViewMonth(month.getMonth())
    }
  }, [month])

  const goToPrevMonth = () => {
    if (viewMonth === 0) {
      setViewYear(y => y - 1)
      setViewMonth(11)
      onMonthChange?.(new Date(viewYear - 1, 11, 1))
    } else {
      setViewMonth(m => m - 1)
      onMonthChange?.(new Date(viewYear, viewMonth - 1, 1))
    }
  }

  const goToNextMonth = () => {
    if (viewMonth === 11) {
      setViewYear(y => y + 1)
      setViewMonth(0)
      onMonthChange?.(new Date(viewYear + 1, 0, 1))
    } else {
      setViewMonth(m => m + 1)
      onMonthChange?.(new Date(viewYear, viewMonth + 1, 1))
    }
  }

  const goToPrevYear = () => {
    setViewYear(y => y - 1)
    onMonthChange?.(new Date(viewYear - 1, viewMonth, 1))
  }

  const goToNextYear = () => {
    setViewYear(y => y + 1)
    onMonthChange?.(new Date(viewYear + 1, viewMonth, 1))
  }

  const daysInMonth = getDaysInMonth(viewYear, viewMonth)
  const firstOffset = getFirstDayOffset(viewYear, viewMonth)

  // 上个月天数
  const prevMonthDays = getDaysInMonth(
    viewMonth === 0 ? viewYear - 1 : viewYear,
    viewMonth === 0 ? 11 : viewMonth - 1
  )

  // 构建日期格子（6行7列=42格）
  const cells: { date: Date; isCurrentMonth: boolean }[] = []

  // 上个月末尾几天
  for (let i = firstOffset - 1; i >= 0; i--) {
    const d = prevMonthDays - i
    const m = viewMonth === 0 ? 11 : viewMonth - 1
    const y = viewMonth === 0 ? viewYear - 1 : viewYear
    cells.push({ date: new Date(y, m, d), isCurrentMonth: false })
  }

  // 当月
  for (let d = 1; d <= daysInMonth; d++) {
    cells.push({ date: new Date(viewYear, viewMonth, d), isCurrentMonth: true })
  }

  // 下个月开头几天
  const remaining = 42 - cells.length
  const nextM = viewMonth === 11 ? 0 : viewMonth + 1
  const nextY = viewMonth === 11 ? viewYear + 1 : viewYear
  for (let d = 1; d <= remaining; d++) {
    cells.push({ date: new Date(nextY, nextM, d), isCurrentMonth: false })
  }

  const navBtnClass = cn(
    buttonVariants({ variant: "outline" }),
    "h-7 w-7 bg-transparent p-0 opacity-60 hover:opacity-100"
  )

  return (
    <div className={cn("p-3 select-none", className)}>
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        {/* 上一年 */}
        <button className={navBtnClass} onClick={goToPrevYear} title="上一年">
          <ChevronsLeft className="h-4 w-4" />
        </button>
        {/* 上一月 */}
        <button className={navBtnClass} onClick={goToPrevMonth} title="上一月">
          <ChevronLeft className="h-4 w-4" />
        </button>

        {/* 年月标题 */}
        <span className="text-sm font-medium flex-1 text-center">
          {viewYear}年 {MONTH_NAMES[viewMonth]}
        </span>

        {/* 下一月 */}
        <button className={navBtnClass} onClick={goToNextMonth} title="下一月">
          <ChevronRight className="h-4 w-4" />
        </button>
        {/* 下一年 */}
        <button className={navBtnClass} onClick={goToNextYear} title="下一年">
          <ChevronsRight className="h-4 w-4" />
        </button>
      </div>

      {/* 星期标题（周一到周日） */}
      <div className="grid grid-cols-7 mb-1">
        {WEEK_DAYS.map((wd) => (
          <div
            key={wd}
            className="h-9 w-9 flex items-center justify-center text-[0.75rem] text-muted-foreground font-normal"
          >
            {wd}
          </div>
        ))}
      </div>

      {/* 日期格子 */}
      <div className="grid grid-cols-7">
        {cells.map(({ date, isCurrentMonth }, idx) => {
          const isToday = isSameDay(date, today)
          const isSelected = selected ? isSameDay(date, selected) : false
          const isDisabled = disabled ? disabled(date) : false

          return (
            <button
              key={idx}
              onClick={() => !isDisabled && onSelect?.(date)}
              disabled={isDisabled}
              className={cn(
                "h-9 w-9 rounded-md text-sm flex items-center justify-center transition-colors",
                "hover:bg-accent hover:text-accent-foreground",
                isDisabled && "opacity-30 cursor-not-allowed hover:bg-transparent",
                !isCurrentMonth && "text-muted-foreground opacity-40",
                isToday && !isSelected && "bg-accent text-accent-foreground font-medium",
                isSelected && "bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground font-medium",
              )}
            >
              {date.getDate()}
            </button>
          )
        })}
      </div>

      {/* Footer slot */}
      {footer && <div className="mt-2">{footer}</div>}
    </div>
  )
}

Calendar.displayName = "Calendar"

export { Calendar }
export type { CalendarProps }
