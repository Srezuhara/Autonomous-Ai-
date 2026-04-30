import { Routes, Route, useLocation } from 'react-router-dom';
import { Sidebar } from './components/layout/Sidebar';
import { FloatingStatus } from './components/layout/FloatingStatus';

// Pages
import Landing       from './pages/Landing';
import Dashboard     from './pages/Dashboard';
import NewBuild      from './pages/NewBuild';
import BuildProgress from './pages/BuildProgress';
import ProjectDetail from './pages/ProjectDetail';
import Statistics    from './pages/Statistics';

export default function App() {
  const location = useLocation();
  const isLanding = location.pathname === '/';

  return (
    <div className="layout-container">
      {!isLanding && <Sidebar />}
      <main className="main-content" style={isLanding ? { padding: 0 } : undefined}>
        <Routes>
          <Route path="/"            element={<Landing />}       />
          <Route path="/dashboard"   element={<Dashboard />}     />
          <Route path="/build"       element={<NewBuild />}      />
          <Route path="/build/:id"   element={<BuildProgress />} />
          <Route path="/projects/:id" element={<ProjectDetail />} />
          <Route path="/stats"       element={<Statistics />}    />
        </Routes>
      </main>
      <FloatingStatus />
    </div>
  );
}
