import { NavLink } from 'react-router-dom';
import { Zap, LayoutDashboard, PlusCircle, BarChart3 } from 'lucide-react';
import './Sidebar.css';

const NAV_LINKS = [
  { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/build',     icon: PlusCircle,      label: 'New Build'  },
  { to: '/stats',     icon: BarChart3,       label: 'Statistics' },
] as const;

export function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar-inner">
        {/* Logo */}
        <NavLink to="/" className="sidebar-logo">
          <div className="sidebar-logo-icon">
            <Zap size={18} color="#fff" strokeWidth={2.5} />
          </div>
          <span className="sidebar-logo-text">AppBuilder</span>
        </NavLink>

        {/* Navigation */}
        <nav className="sidebar-nav">
          <span className="sidebar-section-label">Main</span>
          {NAV_LINKS.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
            >
              <Icon size={17} className="nav-item-icon" />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>

        {/* Footer slot */}
        <div className="sidebar-footer" />
      </div>
    </aside>
  );
}
