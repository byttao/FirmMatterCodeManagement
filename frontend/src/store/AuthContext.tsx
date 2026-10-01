import { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import type { User, AuthState } from '@/types'
import { userApi, authApi, csrfToken } from '@/api/auth'

interface AuthContextType extends AuthState {
  login: (token: string, user: User, fiscalYear?: number) => void
  logout: () => void
  loading: boolean
  fiscalYear: number
  setFiscalYear: (year: number) => void
  updateFiscalYear: (year: number) => Promise<void>
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const [fiscalYear, setFiscalYearState] = useState<number>(new Date().getFullYear())
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    const storedFiscalYear = sessionStorage.getItem('fiscalYear')
    if (storedFiscalYear) setFiscalYearState(Number(storedFiscalYear))
    if (!csrfToken()) { setLoading(false); return }
    authApi.getMe().then(({ data }) => { setUser(data); setToken(csrfToken()) })
      .catch(() => { setUser(null); setToken(null) }).finally(() => setLoading(false))
  }, [])

  const login = (newToken: string, newUser: User, newFiscalYear?: number) => {
    setToken(newToken)
    setUser(newUser)
    if (newFiscalYear) {
      sessionStorage.setItem('fiscalYear', newFiscalYear.toString())
      setFiscalYearState(newFiscalYear)
    }
  }

  const logout = async () => {
    await authApi.logout()
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    localStorage.removeItem('fiscalYear')
    sessionStorage.removeItem('fiscalYear')
    setToken(null)
    setUser(null)
    setFiscalYearState(new Date().getFullYear())
  }

  const setFiscalYear = (year: number) => {
    sessionStorage.setItem('fiscalYear', year.toString())
    setFiscalYearState(year)
  }

  const updateFiscalYear = async (year: number) => {
    try {
      await userApi.setFiscalYear(year)
      sessionStorage.setItem('fiscalYear', year.toString())
      setFiscalYearState(year)
    } catch (error) {
      console.error('更新年度失败:', error)
      throw error
    }
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isAuthenticated: !!token,
        login,
        logout,
        loading,
        fiscalYear,
        setFiscalYear,
        updateFiscalYear,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
