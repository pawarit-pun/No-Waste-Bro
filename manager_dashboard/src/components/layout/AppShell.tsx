import type { CSSProperties } from 'react'
import { Outlet } from 'react-router-dom'
import { AGENT_PANEL_WIDTH, AgentPanel } from '../agent/AgentPanel'
import { AgentProvider, useAgent } from '../agent/AgentProvider'
import { Header } from './Header'
import { Sidebar } from './Sidebar'

function Shell() {
  const { open } = useAgent()
  // Drawer (fixed) อ่าน --agent-panel-w เพื่อเปิดข้างแผงแชท ไม่ทับกัน
  const style = { '--agent-panel-w': open ? `${AGENT_PANEL_WIDTH}px` : '0px' } as CSSProperties
  return (
    <div className="flex h-screen overflow-hidden bg-slate-50" style={style}>
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header />
        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
      <AgentPanel />
    </div>
  )
}

export function AppShell() {
  return (
    <AgentProvider>
      <Shell />
    </AgentProvider>
  )
}
