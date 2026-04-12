import { NavLink } from 'react-router-dom';

const links = [
  { to: '/', label: 'Wyszukiwanie', icon: '🔍' },
  { to: '/search-url', label: 'Wyszukiwanie URL', icon: '🌐' },
  { to: '/bulk', label: 'Wyszukiwanie zbiorcze', icon: '📋' },
  { to: '/proposals', label: 'Propozycje indeksów', icon: '📝' },
];

interface Props {
  theme: 'light' | 'dark';
  onToggleTheme: () => void;
}

export default function Sidebar({ theme, onToggleTheme }: Props) {
  return (
    <aside className="w-64 bg-sol-base2 border-r border-sol-base1/30 flex flex-col shrink-0">
      <div className="p-5 border-b border-sol-base1/30">
        <h1 className="text-lg font-bold text-sol-base02">IndeksyGSR</h1>
        <p className="text-xs text-sol-base1 mt-0.5">Wyszukiwarka indeksów</p>
      </div>
      <nav className="flex-1 p-3 space-y-1">
        {links.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-sol-base3 text-sol-blue shadow-sm'
                  : 'text-sol-base01 hover:bg-sol-base3/60 hover:text-sol-base02'
              }`
            }
          >
            <span>{link.icon}</span>
            {link.label}
          </NavLink>
        ))}
      </nav>
      <div className="p-3 border-t border-sol-base1/30">
        <button
          onClick={onToggleTheme}
          className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium text-sol-base01 hover:bg-sol-base3/60 hover:text-sol-base02 transition-colors"
        >
          <span>{theme === 'light' ? '🌙' : '☀️'}</span>
          {theme === 'light' ? 'Tryb ciemny' : 'Tryb jasny'}
        </button>
      </div>
    </aside>
  );
}
