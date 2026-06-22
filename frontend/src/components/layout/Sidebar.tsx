import { type FC } from 'react';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  FilePlus2,
  Puzzle,
  Settings,
  Code2,
} from 'lucide-react';

const navItems = [
  { to: '/', icon: LayoutDashboard, label: '总览' },
  { to: '/reviews/new', icon: FilePlus2, label: '新建审查' },
  { to: '/skills', icon: Puzzle, label: 'Skill 管理' },
  { to: '/settings', icon: Settings, label: '设置' },
];

export const Sidebar: FC = () => (
  <aside className="fixed left-0 top-0 z-40 h-screen w-60 bg-white border-r border-slate-200 flex flex-col">
    {/* Logo */}
    <div className="flex items-center gap-2.5 px-5 py-5 border-b border-slate-100">
      <div className="flex items-center justify-center w-9 h-9 rounded-lg bg-blue-500 text-white">
        <Code2 size={20} />
      </div>
      <div>
        <h1 className="text-sm font-bold text-slate-800 leading-tight">
          Code Review
        </h1>
        <p className="text-[11px] text-slate-400 leading-tight">Workbench</p>
      </div>
    </div>

    {/* Navigation */}
    <nav className="flex-1 px-3 py-4 space-y-1">
      {navItems.map(({ to, icon: Icon, label }) => (
        <NavLink
          key={to}
          to={to}
          end={to === '/'}
          className={({ isActive }) =>
            `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-150 ${
              isActive
                ? 'bg-blue-50 text-blue-600 shadow-sm'
                : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
            }`
          }
        >
          <Icon size={18} />
          {label}
        </NavLink>
      ))}
    </nav>

    {/* Footer */}
    <div className="px-5 py-4 border-t border-slate-100">
      <p className="text-[11px] text-slate-400">Code Review Workbench v0.2</p>
    </div>
  </aside>
);
