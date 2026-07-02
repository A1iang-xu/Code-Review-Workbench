import { type FC, useState, useEffect, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { reviewApi, triggerDownload } from '../services/api';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { EmptyState } from '../components/common/EmptyState';
import { SeverityBadge } from '../components/common/SeverityBadge';
import { Search, Filter, Download } from 'lucide-react';
import type { ReviewStats, ReviewListItem } from '../types';

const statConfig = [
  { key: 'total_reviews', label: '审查总数', icon: '📋', color: 'text-blue-600' },
  { key: 'avg_score', label: '平均评分', icon: '⭐', color: 'text-amber-600' },
  { key: 'active_agents', label: '活跃 Agent', icon: '🤖', color: 'text-green-600' },
  { key: 'registered_skills', label: '已注册 Skill', icon: '⚡', color: 'text-purple-600' },
] as const;

const statusOptions = [
  { value: 'all', label: '全部状态' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'running', label: '运行中' },
] as const;

export const Dashboard: FC = () => {
  const navigate = useNavigate();

  // 过滤条件
  const [searchInput, setSearchInput] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [minScore, setMinScore] = useState('');
  const [maxScore, setMaxScore] = useState('');
  const [status, setStatus] = useState('all');
  const [exportingId, setExportingId] = useState<string | null>(null);

  // 搜索防抖（300ms）
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchInput.trim());
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  // 组装查询参数
  const listParams = useMemo(() => {
    const params: {
      limit: number;
      offset: number;
      search?: string;
      repo?: string;
      minScore?: number;
      maxScore?: number;
      status?: string;
    } = { limit: 10, offset: 0 };

    if (debouncedSearch) {
      params.search = debouncedSearch;
      params.repo = debouncedSearch;
    }
    if (minScore !== '') {
      const n = Number(minScore);
      if (!Number.isNaN(n)) params.minScore = n;
    }
    if (maxScore !== '') {
      const n = Number(maxScore);
      if (!Number.isNaN(n)) params.maxScore = n;
    }
    if (status !== 'all') {
      params.status = status;
    }
    return params;
  }, [debouncedSearch, minScore, maxScore, status]);

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['review-stats'],
    queryFn: reviewApi.stats,
    refetchInterval: 30000,
  });

  const { data: listData, isLoading: listLoading } = useQuery({
    queryKey: ['review-list', listParams],
    queryFn: () => reviewApi.list(listParams),
    refetchInterval: 30000,
  });

  const reviews: ReviewListItem[] = listData?.items ?? [];
  const statsData: ReviewStats | undefined = stats;

  const getScoreColor = (score: number | undefined | null) => {
    if (score == null) return 'text-slate-400';
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

  const handleExport = async (taskId: string) => {
    if (exportingId) return;
    setExportingId(taskId);
    try {
      const blob = await reviewApi.export(taskId, 'markdown');
      triggerDownload(blob, `review_${taskId}.md`);
    } catch (err) {
      console.error('导出报告失败:', err);
    } finally {
      setExportingId(null);
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

        {/* Filter Bar */}
        <div className="px-5 py-4 border-b border-slate-100 bg-slate-50/50">
          <div className="flex flex-wrap items-center gap-3">
            {/* 搜索输入 */}
            <div className="relative flex-1 min-w-[240px]">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input
                type="text"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="搜索仓库地址或分支..."
                className="w-full pl-9 pr-3 py-2 text-sm border border-slate-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400 bg-white"
              />
            </div>

            {/* 评分范围 */}
            <div className="flex items-center gap-2">
              <Filter className="w-4 h-4 text-slate-400" />
              <input
                type="number"
                min={0}
                max={10}
                step={0.1}
                value={minScore}
                onChange={(e) => setMinScore(e.target.value)}
                placeholder="最低分"
                className="w-20 px-2 py-2 text-sm border border-slate-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400 bg-white"
              />
              <span className="text-slate-400 text-sm">—</span>
              <input
                type="number"
                min={0}
                max={10}
                step={0.1}
                value={maxScore}
                onChange={(e) => setMaxScore(e.target.value)}
                placeholder="最高分"
                className="w-20 px-2 py-2 text-sm border border-slate-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400 bg-white"
              />
            </div>

            {/* 状态筛选 */}
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="px-3 py-2 text-sm border border-slate-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400 bg-white"
            >
              {statusOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
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
                    <th className="pb-2 font-medium text-right">操作</th>
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
                          {(review.score ?? 0).toFixed(1)}
                        </span>
                      </td>
                      <td className="py-3">
                        <span className="text-slate-600">{review.issues_count ?? 0}</span>
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
                      <td className="py-3 text-right">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            void handleExport(review.task_id);
                          }}
                          disabled={exportingId === review.task_id}
                          title="导出 Markdown 报告"
                          className="inline-flex items-center justify-center w-8 h-8 rounded-md text-slate-500 hover:text-blue-600 hover:bg-blue-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                        >
                          <Download className="w-4 h-4" />
                        </button>
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
