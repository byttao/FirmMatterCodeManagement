import * as React from "react"
import { format } from "date-fns"
import { Calendar as CalendarIcon } from "lucide-react"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Calendar } from "@/components/ui/calendar"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"

interface DatePickerProps {
  value?: string
  onChange: (date: string) => void
  placeholder?: string
  disabled?: boolean
  className?: string
  /** 是否限制不能选未来日期，默认 false */
  disableFuture?: boolean
}

export function DatePicker({
  value,
  onChange,
  placeholder = "选择日期",
  disabled = false,
  className,
  disableFuture = false,
}: DatePickerProps) {
  const [open, setOpen] = React.useState(false)
  const [month, setMonth] = React.useState<Date | undefined>(undefined)

  const selectedDate = value ? new Date(value) : undefined
  const today = new Date()

  // 打开时跳到选中日期所在月，未选时跳到今天
  const handleOpenChange = (o: boolean) => {
    if (o) {
      setMonth(selectedDate ?? today)
    }
    setOpen(o)
  }

  const handleSelect = (date: Date | undefined) => {
    if (date) {
      onChange(format(date, "yyyy-MM-dd"))
    }
    setOpen(false)
  }

  const handleGoToday = () => {
    setMonth(today)
    // 点击"今天"直接选中今天
    onChange(format(today, "yyyy-MM-dd"))
    setOpen(false)
  }

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <Button
          variant={"outline"}
          className={cn(
            "w-full justify-start text-left font-normal h-10 px-3",
            !selectedDate && "text-muted-foreground",
            className
          )}
          disabled={disabled}
        >
          <CalendarIcon className="mr-2 h-4 w-4 shrink-0" />
          {selectedDate ? (
            format(selectedDate, "yyyy-MM-dd")
          ) : (
            <span className="text-muted-foreground">{placeholder}</span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="start">
        <Calendar
          selected={selectedDate}
          onSelect={handleSelect}
          month={month}
          onMonthChange={setMonth}
          disabled={disableFuture ? (date) => date > today : undefined}
          footer={
            <div className="flex justify-center pt-1 pb-1 border-t border-border">
              <button
                onClick={handleGoToday}
                className="text-xs text-primary hover:text-primary/80 hover:underline px-3 py-1 rounded transition-colors"
              >
                回到今天
              </button>
            </div>
          }
        />
      </PopoverContent>
    </Popover>
  )
}
