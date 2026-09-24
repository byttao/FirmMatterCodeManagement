import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from '@/store/AuthContext'
import { DirtyProvider } from '@/context/DirtyContext'
import { Toaster } from '@/components/ui/toaster'
import Login from '@/pages/Login'
import Dashboard from '@/pages/Dashboard'
import ProjectList from '@/pages/ProjectList'
import SignedProjects from '@/pages/SignedProjects'
import ProjectForm from '@/pages/ProjectForm'
import UserManagement from '@/pages/UserManagement'
import SignerManagement from '@/pages/SignerManagement'
import FiscalYearConfig from '@/pages/FiscalYearConfig'
import SetupWizard from '@/pages/SetupWizard'

// 布局组件
import Layout from '@/components/Layout'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, loading } = useAuth()

  if (loading) {
    return <div className="flex items-center justify-center h-screen">加载中...</div>
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  return <>{children}</>
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/setup" element={<SetupWizard />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="projects" element={<ProjectList />} />
        <Route path="signed-projects" element={<SignedProjects />} />
        <Route path="projects/new" element={<ProjectForm />} />
        <Route path="projects/:projectId" element={<ProjectForm readonly={true} />} />
        <Route path="projects/:projectId/edit" element={<ProjectForm readonly={false} />} />
        <Route path="signers" element={<SignerManagement />} />
        <Route path="fiscal-year-configs" element={<FiscalYearConfig />} />
        <Route path="users" element={<UserManagement />} />
      </Route>
      <Route path="*" element={<Navigate to="/projects" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <DirtyProvider>
          <AppRoutes />
          <Toaster />
        </DirtyProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}
