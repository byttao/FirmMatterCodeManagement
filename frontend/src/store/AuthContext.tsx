import { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import type { User, AuthState } from '@/types'
import { userApi } from '@/api/auth'

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
    const storedToken = localStorage.getItem('token')
    const storedUser = localStorage.getItem('user')
    const storedFiscalYear = localStorage.getItem('fiscalYear')

    if (storedToken && storedUser) {
      setToken(storedToken)
      setUser(JSON.parse(storedUser))
      if (storedFiscalYear) {
        setFiscalYearState(parseInt(storedFiscalYear))
      }
    }
    setLoading(false)
  }, [])

  const login = (newToken: string, newUser: User, newFiscalYear?: number) => {
    localStorage.setItem('token', newToken)
    localStorage.setItem('user', JSON.stringify(newUser))
    setToken(newToken)
    setUser(newUser)
    if (newFiscalYear) {
      localStorage.setItem('fiscalYear', newFiscalYear.toString())
      setFiscalYearState(newFiscalYear)
    }
  }

  const logout = () => {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    localStorage.removeItem('fiscalYear')
    setToken(null)
    setUser(null)
    setFiscalYearState(new Date().getFullYear())
  }

  const setFiscalYear = (year: number) => {
    localStorage.setItem('fiscalYear', year.toString())
    setFiscalYearState(year)
  }

  const updateFiscalYear = async (year: number) => {
    try {
      const res = await userApi.setFiscalYear(year)
      const newToken = res.data.access_token
      localStorage.setItem('token', newToken)
      setToken(newToken)
      localStorage.setItem('fiscalYear', year.toString())
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
