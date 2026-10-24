// เมนูและ breadcrumb ของแต่ละหน้า
export interface NavItem {
  path: string
  label: string
  section: 'MONITOR' | 'ACTIONS' | 'AUDIT'
  crumb: string
  icon: 'grid' | 'box' | 'chef' | 'shield' | 'play' | 'list' | 'check' | 'truck'
}

export const NAV_ITEMS: NavItem[] = [
  { path: '/overview', label: 'Overview', section: 'MONITOR', crumb: 'Dashboard', icon: 'grid' },
  { path: '/inventory', label: 'Inventory', section: 'MONITOR', crumb: 'Monitor', icon: 'box' },
  { path: '/kitchen', label: 'Kitchen', section: 'MONITOR', crumb: 'Monitor', icon: 'chef' },
  { path: '/pickups', label: 'Pickups', section: 'MONITOR', crumb: 'Monitor', icon: 'truck' },
  { path: '/review-queue', label: 'Review queue', section: 'ACTIONS', crumb: 'Actions', icon: 'shield' },
  { path: '/run-demo', label: 'Run demo', section: 'ACTIONS', crumb: 'Actions', icon: 'play' },
  { path: '/task-log', label: 'Task log', section: 'AUDIT', crumb: 'Audit', icon: 'check' },
  { path: '/pipeline-runs', label: 'Pipeline runs', section: 'AUDIT', crumb: 'Audit', icon: 'list' },
]

export const SECTIONS: NavItem['section'][] = ['MONITOR', 'ACTIONS', 'AUDIT']
