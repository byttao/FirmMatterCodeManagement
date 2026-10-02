import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { lazy, Suspense } from 'react'
import { AuthProvider, useAuth } from '@/store/AuthContext'
import { DirtyProvider } from '@/context/DirtyContext'
import { Toaster } from '@/components/ui/toaster'
import Login from '@/pages/Login'
const Dashboard = lazy(() => import('@/pages/Dashboard'))
const ProjectList = lazy(() => import('@/pages/ProjectList'))
const SignedProjects = lazy(() => import('@/pages/SignedProjects'))
const ProjectForm = lazy(() => import('@/pages/ProjectForm'))
const UserManagement = lazy(() => import('@/pages/UserManagement'))
const SignerManagement = lazy(() => import('@/pages/SignerManagement'))
const FiscalYearConfig = lazy(() => import('@/pages/FiscalYearConfig'))
import SetupWizard from '@/pages/SetupWizard'
const LicenseManagement = lazy(() => import('@/pages/LicenseManagement'))
const CustomerManagement = lazy(() => import('@/pages/CustomerManagement'))
const CustomerDetail = lazy(() => import('@/pages/CustomerDetail'))
const BillingWorklist = lazy(() => import('@/pages/BillingWorklist'))
const BillingTasks = lazy(() => import('@/pages/BillingTasks'))
const AuditEvents = lazy(() => import('@/pages/AuditEvents'))
const ProjectRequests = lazy(() => import('@/pages/ProjectRequests'))
const AccountSecurity = lazy(() => import('@/pages/AccountSecurity'))
const ExportJobs = lazy(() => import('@/pages/ExportJobs'))
const RuntimeLogs = lazy(() => import('@/pages/RuntimeLogs'))
const SystemBackup = lazy(() => import('@/pages/SystemBackup'))

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
    <Suspense fallback={<div className="p-4">加载中...</div>}><Routes>
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
        <Route path="license" element={<LicenseManagement />} />
        <Route path="customers" element={<CustomerManagement />} />
        <Route path="customers/:customerId" element={<CustomerDetail />} />
        <Route path="billing-worklist" element={<BillingWorklist />} />
        <Route path="billing-tasks" element={<BillingTasks />} />
        <Route path="audit-events" element={<AuditEvents />} />
        <Route path="project-change-requests" element={<ProjectRequests />} />
        <Route path="account" element={<AccountSecurity />} />
        <Route path="exports" element={<ExportJobs />} />
        <Route path="runtime-logs" element={<RuntimeLogs />} />
        <Route path="system-backup" element={<SystemBackup />} />
      </Route>
      <Route path="*" element={<Navigate to="/projects" replace />} />
    </Routes></Suspense>
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
