import { type FC } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { reviewApi } from '../services/api';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { EmptyState } from '../components/common/EmptyState';
import { SeverityBadge } from '../components/common/SeverityBadge';
import type { ReviewStats, ReviewListItem } from '../types';

const statConfig = [
  { key: 'total_reviews', label: '审查总数', icon: '📋', color: 'text-blue-600' },
  { key: 'avg_score', label: '平均评分', icon: '⭐', color: 'text-amber-600' },
  { key: 'active_agents', label: '活跃 Agent', icon: '🤖', color: 'text-green-600' },
  { key: 'registered_skills', label: '已注册 Skill', icon: '⚡', color: 'text-purple-600' },
] as const;

export const Dashboard: FC = () => {
  const navigate = useNavigate();

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['review-stats'],
    queryFn: reviewApi.stats,
    refetchInterval: 30000,
  });

  const { data: listData, isLoading: listLoading } = useQuery({
    queryKey: ['review-list', { limit: 10 }],
    queryFn: () => reviewApi.list({ limit: 10 }),
    refetchInterval: 30000,
  });

  const reviews: ReviewListItem[] = listData?.items ?? [];
  const statsData: ReviewStats | undefined = stats;

  const getScoreColor = (score: number) => {
    if (score >= 8) return 'text-green-600';
    if (score >= 6) return 'text-amber-600';
    if (score >= 4) return 'text-orange-600';
    return 'text-red-600';
  };

  const formatDate = (iso: string) => {
    if (!iso) return '';
    try {
      const d = new Date(iso);
      return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
    } catch {
      return iso;
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-800">仪表盘</h1>
        <p className="text-slate-500 mt-1">代码审查工作台概览</p>
      </div>

      {/* Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {statConfig.map((card) => (
          <div key={card.key} className="bg-white rounded-lg shadow-sm border border-slate-200 p-5">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-500">{card.label}</p>
                {statsLoading ? (
                  <div className="h-8 w-16 bg-slate-100 rounded animate-pulse mt-1" />
                ) : (
                  <p className={`text-2xl font-bold mt-1 ${card.color}`}>
                    {statsData ? statsData[card.key] : 0}
                  </p>
                )}
              </div>
              <span className="text-3xl">{card.icon}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Recent Reviews */}
      <div className="bg-white rounded-lg shadow-sm border border-slate-200">
        <div className="px-5 py-4 border-b border-slate-200">
          <h2 className="font-semibold text-slate-800">最近审查</h2>
        </div>
        <div className="p-5">
          {listLoading ? (
            <LoadingSpinner />
          ) : reviews.length === 0 ? (
            <EmptyState
              title="还没有审查记录"
              description='点击左侧"新建审查"开始第一次代码审查'
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-500 border-b border-slate-100">
                    <th className="pb-2 font-medium">文件/仓库</th>
                    <th className="pb-2 font-medium">评分</th>
                    <th className="pb-2 font-medium">问题数</th>
                    <th className="pb-2 font-medium">状态</th>
                    <th className="pb-2 font-medium">时间</th>
                  </tr>
                </thead>
                <tbody>
                  {reviews.map((review) => (
                    <tr
                      key={review.task_id}
                      onClick={() => navigate(`/reviews/${review.task_id}`)}
                      className="border-b border-slate-50 hover:bg-slate-50 cursor-pointer transition-colors"
                    >
                      <td className="py-3">
                        <div className="text-slate-800 font-medium">
                          {review.repo_url || '直接上传文件'}
                        </div>
                        <div className="text-xs text-slate-400">
                          {review.branch || '—'}
                        </div>
                      </td>
                      <td className="py-3">
                        <span className={`font-bold ${getScoreColor(review.score)}`}>
                          {review.score.toFixed(1)}
                        </span>
                      </td>
                      <td className="py-3">
                        <span className="text-slate-600">{review.issues_count}</span>
                      </td>
                      <td className="py-3">
                        <SeverityBadge severity={review.status === 'completed' ? 'low' : 'medium'} />
                        <span className="ml-1 text-xs text-slate-500">
                          {review.status === 'completed' ? '已完成' : review.status}
                        </span>
                      </td>
                      <td className="py-3 text-slate-400 text-xs">
                        {formatDate(review.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
