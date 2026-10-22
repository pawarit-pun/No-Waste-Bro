// เมนูและ breadcrumb ของแต่ละหน้า
export interface NavItem {
  path: string
  label: string
  section: 'MONITOR' | 'ACTIONS' | 'AUDIT'
  crumb: string
  icon: 'grid' | 'alert' | 'shield' | 'play' | 'list'
}

export const NAV_ITEMS: NavItem[] = [
  { path: '/overview', label: 'Overview', section: 'MONITOR', crumb: 'Dashboard', icon: 'grid' },
  { path: '/risk-monitor', label: 'Risk monitor', section: 'MONITOR', crumb: 'Monitor', icon: 'alert' },
  { path: '/review-queue', label: 'Review queue', section: 'ACTIONS', crumb: 'Actions', icon: 'shield' },
  { path: '/run-demo', label: 'Run demo', section: 'ACTIONS', crumb: 'Actions', icon: 'play' },
  { path: '/agent-log', label: 'Agent log', section: 'AUDIT', crumb: 'Audit', icon: 'list' },
]

export const SECTIONS: NavItem['section'][] = ['MONITOR', 'ACTIONS', 'AUDIT']
