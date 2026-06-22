import { type FC } from 'react';
import { Loader2 } from 'lucide-react';

interface Props {
  text?: string;
  size?: number;
}

export const LoadingSpinner: FC<Props> = ({ text = '加载中...', size = 32 }) => (
  <div className="flex flex-col items-center justify-center py-16 gap-3 fade-in">
    <Loader2 className="text-blue-500 animate-spin" size={size} />
    <span className="text-slate-500 text-sm">{text}</span>
  </div>
);
