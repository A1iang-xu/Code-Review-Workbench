import { type FC } from 'react';
import { useLocation } from 'react-router-dom';

const pageTitles: Record<string, string> = {
  '/': '仪表盘',
  '/reviews/new': '新建审查',
  '/skills': 'Skill 管理',
  '/settings': '设置',
};

export const Header: FC = () => {
  const location = useLocation();
  const title =
    pageTitles[location.pathname] ||
    (location.pathname.startsWith('/reviews/') ? '审查详情' : 'Code Review Workbench');

  return (
    <header className="sticky top-0 z-30 bg-white/80 backdrop-blur-sm border-b border-slate-200 px-8 py-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-800">{title}</h2>
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 text-sm font-semibold">
            U
          </div>
        </div>
      </div>
    </header>
  );
};
