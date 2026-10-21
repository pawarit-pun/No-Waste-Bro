import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/layout/AppShell'
import { SessionProvider, useSession } from './lib/session'
import { ComingSoonPage } from './pages/ComingSoonPage'
import { LoginPage } from './pages/LoginPage'
import { ReviewQueuePage } from './pages/review/ReviewQueuePage'

function AppRoutes() {
  const { manager } = useSession()
  if (!manager) return <LoginPage />

  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/overview" element={<ComingSoonPage title="Overview" />} />
        <Route path="/risk-monitor" element={<ComingSoonPage title="Risk monitor" />} />
        <Route path="/review-queue" element={<ReviewQueuePage />} />
        <Route path="/agent-log" element={<ComingSoonPage title="Agent log" />} />
        <Route path="*" element={<Navigate to="/review-queue" replace />} />
      </Route>
    </Routes>
  )
}

function App() {
  return (
    <BrowserRouter>
      <SessionProvider>
        <AppRoutes />
      </SessionProvider>
    </BrowserRouter>
  )
}

export default App
