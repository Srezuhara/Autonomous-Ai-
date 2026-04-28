import { Routes, Route, NavLink, useLocation } from 'react-router-dom';
import { LayoutDashboard, PlusCircle, Activity, BarChart3, Zap } from 'lucide-react';
import { useHealth } from './hooks/useHealth';
import './App.css';

// Placeholder imports for pages we are about to build
import Landing from './pages/Landing';
import Dashboard from './pages/Dashboard';
import NewBuild from './pages/NewBuild';
import BuildProgress from './pages/BuildProgress';
import ProjectDetail from './pages/ProjectDetail';
import Statistics from './pages/Statistics';

function Sidebar() {
  return (
    <aside className="sidebar">
      <NavLink to="/" className="sidebar-logo">
        <Zap className="icon" size={28} strokeWidth={2.5} />
        <span>AI App Builder</span>
      </NavLink>

      <nav className="nav-links">
        <NavLink to="/dashboard" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
          <LayoutDashboard size={20} />
          <span>Dashboard</span>
        </NavLink>
        <NavLink to="/build" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
          <PlusCircle size={20} />
          <span>New Build</span>
        </NavLink>
        <NavLink to="/stats" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
          <BarChart3 size={20} />
          <span>Statistics</span>
        </NavLink>
      </nav>
    </aside>
  );
}

function FloatingStatus() {
  const health = useHealth();
  const llmStatus = health?.llm?.status || 'unknown';
  const isHealthy = llmStatus === 'healthy';

  return (
    <div className="fixed bottom-6 right-6 z-50 flex items-center gap-3 px-5 py-3 rounded-full bg-[#1a0f0a]/60 backdrop-blur-md border border-[#FF8C42]/20 shadow-xl shadow-black/40">
      <div className={`w-2.5 h-2.5 rounded-full ${isHealthy ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]' : 'bg-yellow-400 shadow-[0_0_8px_rgba(250,204,21,0.8)]'} animate-pulse`} />
      <div className="flex flex-col">
        <span className="text-xs font-semibold text-[#FFE4B5]">
          Backend {health ? 'Online' : 'Connecting...'}
        </span>
        {health && (
          <span className="text-[10px] text-[#FFE4B5]/70 flex items-center gap-1 mt-0.5">
            <Activity size={10} />
            LLM: {llmStatus} ({health.worker_pool?.running || 0} active)
          </span>
        )}
      </div>
    </div>
  );
}

function App() {
  const location = useLocation();
  const isLanding = location.pathname === '/';

  return (
    <div className="layout-container">
      {!isLanding && <Sidebar />}
      <main className="main-content" style={{ padding: isLanding ? 0 : undefined, flexGrow: 1 }}>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/build" element={<NewBuild />} />
          <Route path="/build/:id" element={<BuildProgress />} />
          <Route path="/projects/:id" element={<ProjectDetail />} />
          <Route path="/stats" element={<Statistics />} />
        </Routes>
      </main>
      <FloatingStatus />
    </div>
  );
}

export default App;
