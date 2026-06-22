import { type FC, type ReactNode } from 'react';
import { Inbox } from 'lucide-react';

interface Props {
  icon?: ReactNode;
  title: string;
  description?: string;
}

export const EmptyState: FC<Props> = ({ icon, title, description }) => (
  <div className="flex flex-col items-center justify-center py-16 gap-2 fade-in">
    <div className="text-slate-300 mb-2">{icon || <Inbox size={48} />}</div>
    <h3 className="text-lg font-medium text-slate-500">{title}</h3>
    {description && <p className="text-sm text-slate-400">{description}</p>}
  </div>
);
