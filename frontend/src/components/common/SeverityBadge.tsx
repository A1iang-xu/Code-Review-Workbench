import { type FC } from 'react';

const severityLabels: Record<string, string> = {
  critical: '严重',
  high: '高危',
  medium: '中危',
  low: '低危',
  info: '信息',
};

const severityColors: Record<string, string> = {
  critical: 'severity-critical',
  high: 'severity-high',
  medium: 'severity-medium',
  low: 'severity-low',
  info: 'severity-info',
};

interface Props {
  severity: string;
  className?: string;
}

export const SeverityBadge: FC<Props> = ({ severity, className = '' }) => {
  const colorClass = severityColors[severity] || severityColors.info;
  const label = severityLabels[severity] || severity;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ${colorClass} ${className}`}
    >
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{ backgroundColor: 'currentColor' }}
      />
      {label}
    </span>
  );
};
