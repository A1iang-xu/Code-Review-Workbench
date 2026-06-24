import { type FC } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  BarChart3,
  Star,
  Bot,
  Puzzle,
  TrendingUp,
  Clock,
  ArrowRight,
} from 'lucide-react';

// 模拟的统计数据（后续接入真实 API）
const mockStats = {
  totalReviews: 12,
  avgScore: 7.8,
  activeAgents: 5,
  registeredSkills: 2,
};

const recentReviews = [
  { task_id: 'd1', repo_url: 'my-project/backend', score: 8.5, status: 'completed', created_at: '2026-06-22T10:00:00Z', issues_count: 23 },
  { task_id: 'd2', repo_url: 'team-frontend/app', score: 7.2, status: 'completed', created_at: '2026-06-21T14:30:00Z', issues_count: 41 },
  { task_id: 'd3', repo_url: 'lib-crypto/utils', score: 9.1, status: 'completed', created_at: '2026-06-20T09:00:00Z', issues_count: 5 },
];

const statCards = [
  { label: '审查次数', value: mockStats.totalReviews, icon: BarChart3, color: 'text-blue-500', bg: 'bg-blue-50' },
  { label: '平均评分', value: mockStats.avgScore + '/10', icon: Star, color: 'text-emerald-500', bg: 'bg-emerald-50' },
  { label: '活跃 Agent', value: mockStats.activeAgents, icon: Bot, color: 'text-purple-500', bg: 'bg-purple-50' },
  { label: '已注册 Skill', value: mockStats.registeredSkills, icon: Puzzle, color: 'text-orange-500', bg: 'bg-orange-50' },
];

export const Dashboard: FC = () => {
  const navigate = useNavigate();

  return (
    <div className="space-y-6 fade-in">
      {/* Stat cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {statCards.map(({ label, value, icon: Icon, color, bg }) => (
          <div
            key={label}
            className="bg-white rounded-xl border border-slate-200 p-5 hover:shadow-md transition-shadow"
          >
            <div className="flex items-center gap-3">
              <div className={`w-10 h-10 rounded-lg ${bg} flex items-center justify-center ${color}`}>
                <Icon size={20} />
              </div>
              <div>
                <p className="text-2xl font-bold text-slate-800">{value}</p>
                <p className="text-xs text-slate-500">{label}</p>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Trend + Recent */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Trend chart placeholder */}
        <div className="lg:col-span-2 bg-white rounded-xl border border-slate-200 p-5">
          <div className="flex items-center gap-2 mb-4">
            <TrendingUp size={16} className="text-slate-500" />
            <h3 className="text-sm font-semibold text-slate-700">审查质量趋势</h3>
          </div>
          <div className="h-48 flex items-center justify-center bg-slate-50 rounded-lg border border-dashed border-slate-200">
            <div className="text-center text-slate-400">
              <BarChart3 size={32} className="mx-auto mb-1 opacity-40" />
              <p className="text-sm">审查数据将在完成后显示</p>
              <p className="text-xs mt-0.5 opacity-60">持续积累审查记录后启用趋势图</p>
            </div>
          </div>
        </div>

        {/* Recent reviews */}
        <div className="bg-white rounded-xl border border-slate-200 p-5">
          <div className="flex items-center gap-2 mb-4">
            <Clock size={16} className="text-slate-500" />
            <h3 className="text-sm font-semibold text-slate-700">最近审查</h3>
          </div>
          <div className="space-y-3">
            {recentReviews.map((r) => (
              <button
                key={r.task_id}
                onClick={() => navigate(`/reviews/${r.task_id}`)}
                className="w-full text-left p-3 rounded-lg border border-slate-100 hover:border-blue-200 hover:bg-blue-50/50 transition-all group"
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-slate-700 truncate max-w-[140px]">
                    {r.repo_url}
                  </span>
                  <span className="text-xs font-semibold text-blue-600">
                    {r.score}/10
                  </span>
                </div>
                <div className="flex items-center justify-between mt-1">
                  <span className="text-xs text-slate-400">
                    {r.created_at.slice(0, 10)} · {r.issues_count} 个问题
                  </span>
                  <ArrowRight size={12} className="text-slate-300 group-hover:text-blue-500 transition-colors" />
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
