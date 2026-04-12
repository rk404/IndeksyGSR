import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import { useTheme } from '../hooks/useTheme';

export default function Layout() {
  const { theme, toggle } = useTheme();

  return (
    <div className="flex min-h-screen bg-sol-base3">
      <Sidebar theme={theme} onToggleTheme={toggle} />
      <main className="flex-1 p-6 lg:p-8 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}
