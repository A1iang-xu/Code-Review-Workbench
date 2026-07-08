import { type FC } from 'react';
import { CheckCircle2, Circle, Loader2, AlertCircle } from 'lucide-react';
import type { AgentTimelineStep } from '../../types';

const defaultAgents: AgentTimelineStep[] = [
  { agent_type: 'style', display_name: '风格检查', status: 'pending', duration_ms: 0, finding_count: 0 },
  { agent_type: 'security', display_name: '安全审计', status: 'pending', duration_ms: 0, finding_count: 0 },
  { agent_type: 'architecture', display_name: '架构分析', status: 'pending', duration_ms: 0, finding_count: 0 },
  { agent_type: 'performance', display_name: '性能分析', status: 'pending', duration_ms: 0, finding_count: 0 },
  { agent_type: 'refactor', display_name: '重构建议', status: 'pending', duration_ms: 0, finding_count: 0 },
  { agent_type: 'arbitrator', display_name: '仲裁汇总', status: 'pending', duration_ms: 0, finding_count: 0 },
];

const statusIcons: Record<string, typeof CheckCircle2> = {
  completed: CheckCircle2,
  running: Loader2,
  failed: AlertCircle,
  pending: Circle,
};
const statusColors: Record<string, string> = {
  completed: 'text-emerald-500',
  running: 'text-blue-500 pulse-dot',
  failed: 'text-red-500',
  pending: 'text-slate-300',
};

interface Props {
  timeline?: AgentTimelineStep[];
}

export const AgentTimeline: FC<Props> = ({ timeline }) => {
  const agents = timeline && timeline.length > 0 ? timeline : defaultAgents;

  return (
    <div className="space-y-0">
      {agents.map((agent, idx) => {
        const isLast = idx === agents.length - 1;
        const Icon = statusIcons[agent.status] || Circle;
        const colorClass = statusColors[agent.status] || statusColors.pending;
        const isAnimating = agent.status === 'running';

        return (
          <div key={agent.agent_type} className="flex gap-4">
            {/* Timeline dot + line */}
            <div className="flex flex-col items-center">
              <div className={`mt-1 ${colorClass}`}>
                <Icon size={18} className={isAnimating ? 'animate-spin' : ''} />
              </div>
              {!isLast && <div className="w-0.5 flex-1 bg-slate-200 my-1" />}
            </div>

            {/* Content */}
            <div className="pb-5 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-slate-700">
                  {agent.display_name}
                </span>
                {agent.status === 'completed' && agent.duration_ms > 0 && (
                  <span className="text-xs text-slate-400">
                    {agent.duration_ms < 1000
                      ? `${agent.duration_ms}ms`
                      : `${(agent.duration_ms / 1000).toFixed(1)}s`}
                  </span>
                )}
              </div>
              {agent.status === 'completed' && (
                <p className="text-xs text-slate-400 mt-0.5">
                  发现 {agent.finding_count} 个问题
                </p>
              )}
              {agent.status === 'running' && (
                <p className="text-xs text-blue-500 mt-0.5">执行中...</p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
};
