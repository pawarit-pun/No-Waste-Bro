import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/layout/AppShell'
import { SessionProvider, useSession } from './lib/session'
import { OverviewPage } from './pages/overview/OverviewPage'
import { InventoryPage } from './pages/inventory/InventoryPage'
import { KitchenPage } from './pages/kitchen/KitchenPage'
import { PickupsPage } from './pages/pickups/PickupsPage'
import { AgentLogPage } from './pages/agent-log/AgentLogPage'
import { LoginPage } from './pages/LoginPage'
import { ReviewQueuePage } from './pages/review/ReviewQueuePage'
import { RunDemoPage } from './pages/run-demo/RunDemoPage'
import { TaskLogPage } from './pages/task-log/TaskLogPage'

function AppRoutes() {
  const { manager } = useSession()
  if (!manager) return <LoginPage />

  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/overview" element={<OverviewPage />} />
        <Route path="/inventory" element={<InventoryPage />} />
        <Route path="/kitchen" element={<KitchenPage />} />
        <Route path="/pickups" element={<PickupsPage />} />
        <Route path="/review-queue" element={<ReviewQueuePage />} />
        <Route path="/run-demo" element={<RunDemoPage />} />
        <Route path="/task-log" element={<TaskLogPage />} />
        <Route path="/pipeline-runs" element={<AgentLogPage />} />
        <Route path="/agent-log" element={<Navigate to="/pipeline-runs" replace />} />
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
