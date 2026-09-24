import { createContext, useContext, useState, useCallback, useEffect, ReactNode } from 'react'

interface DirtyContextType {
  isDirty: boolean
  setDirty: (dirty: boolean) => void
  confirmDirty: (callback: () => void) => boolean
}

const DirtyContext = createContext<DirtyContextType | undefined>(undefined)

export function DirtyProvider({ children }: { children: ReactNode }) {
  const [isDirty, setIsDirty] = useState(false)

  // 监听 beforeunload 事件，刷新/关闭页面时弹出提示
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (isDirty) {
        e.preventDefault()
        e.returnValue = '当前有未保存的数据，确定要离开吗？'
        return e.returnValue
      }
    }

    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [isDirty])

  const setDirty = useCallback((dirty: boolean) => {
    setIsDirty(dirty)
  }, [])

  const confirmDirty = useCallback((callback: () => void): boolean => {
    if (isDirty) {
      const confirmed = window.confirm('当前有未保存的数据，确定要离开吗？')
      if (confirmed) {
        setIsDirty(false)
        callback()
        return true
      }
      return false
    }
    callback()
    return true
  }, [isDirty])

  return (
    <DirtyContext.Provider value={{ isDirty, setDirty, confirmDirty }}>
      {children}
    </DirtyContext.Provider>
  )
}

export function useDirty() {
  const context = useContext(DirtyContext)
  if (!context) {
    throw new Error('useDirty must be used within DirtyProvider')
  }
  return context
}
