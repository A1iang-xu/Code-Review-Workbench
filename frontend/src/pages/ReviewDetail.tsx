import { type FC, useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { reviewApi } from '../services/api';
import { useReviewProgress } from '../hooks/useSSE';
import { IssueList } from '../components/review/IssueList';
import { DiffViewer } from '../components/review/DiffViewer';
import { AgentTimeline } from '../components/review/AgentTimeline';
import { ReportPanel } from '../components/review/ReportPanel';
import { SeverityBadge } from '../components/common/SeverityBadge';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { EmptyState } from '../components/common/EmptyState';
import { Star, AlertTriangle, FileCode, Activity, FileText } from 'lucide-react';
import type { CodeIssue } from '../types';

type TabId = 'issues' | 'diff' | 'timeline' | 'report';

const tabs: { id: TabId; label: string; icon: typeof FileCode }[] = [
  { id: 'issues', label: '问题列表', icon: AlertTriangle },
  { id: 'diff', label: '代码对比', icon: FileCode },
  { id: 'timeline', label: 'Agent 时间线', icon: Activity },
  { id: 'report', label: '完整报告', icon: FileText },
];

export const ReviewDetail: FC = () => {
  const { taskId } = useParams<{ taskId: string }>();
  const [activeTab, setActiveTab] = useState<TabId>('issues');

  // Fetch review result
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['review', taskId],
    queryFn: () => reviewApi.get(taskId!),
    enabled: !!taskId,
    refetchInterval: false,
  });

  // SSE progress
  const { progress, isComplete } = useReviewProgress(taskId);

  // Refetch when SSE indicates completion
  useEffect(() => {
    if (isComplete) refetch();
  }, [isComplete, refetch]);

  // Loading
  if (isLoading) {
    return (
      <div className="space-y-4">
        <LoadingSpinner text="正在加载审查结果..." />
        {progress && (
          <div className="max-w-md mx-auto bg-white rounded-xl border border-slate-200 p-5">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-slate-500">审查进度</span>
              <span className="text-xs font-semibold text-blue-600">
                {Math.round(progress.progress * 100)}%
              </span>
            </div>
            <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 rounded-full transition-all duration-500"
                style={{ width: `${progress.progress * 100}%` }}
              />
            </div>
            <p className="text-xs text-slate-400 mt-2">
              当前阶段: {progress.current_stage}
            </p>
          </div>
        )}
      </div>
    );
  }

  // Error
  if (isError || !data) {
    return <EmptyState title="未找到审查记录" description="该任务可能不存在或尚未完成" />;
  }

  // Parse issues from report_html or use empty
  const issues: CodeIssue[] = []; // Issues extracted from report_html if needed

  const scoreColor =
    (data.score || 0) >= 8 ? 'text-emerald-500' : (data.score || 0) >= 6 ? 'text-amber-500' : 'text-red-500';

  return (
    <div className="space-y-6 fade-in max-w-6xl">
      {/* Score summary */}
      <div className="bg-white rounded-xl border border-slate-200 p-6">
        <div className="flex items-start gap-6">
          <div className="text-center">
            <div className={`text-5xl font-bold ${scoreColor}`}>
              {data.score ?? '—'}
            </div>
            <p className="text-xs text-slate-400 mt-1">/10</p>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm text-slate-600 leading-relaxed">
              {data.summary || '审查完成'}
            </p>
            <div className="flex items-center gap-2 mt-3 flex-wrap">
              {data.stats &&
                Object.entries(data.stats).map(([agent, count]) => (
                  <span
                    key={agent}
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-slate-100 text-xs text-slate-600"
                  >
                    <Star size={10} />
                    {agent}: {count}
                  </span>
                ))}
              {data.issues_count !== undefined && (
                <span className="text-xs text-slate-400">
                  共 {data.issues_count} 个问题
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <div className="flex border-b border-slate-200 bg-slate-50/50">
          {tabs.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              className={`flex items-center gap-2 px-5 py-3 text-sm font-medium transition-all border-b-2 -mb-px ${
                activeTab === id
                  ? 'border-blue-500 text-blue-600 bg-white'
                  : 'border-transparent text-slate-500 hover:text-slate-700'
              }`}
            >
              <Icon size={15} />
              {label}
            </button>
          ))}
        </div>

        <div className="p-5">
          {activeTab === 'issues' && (
            <IssueList issues={issues} />
          )}
          {activeTab === 'diff' && (
            <DiffViewer original="" modified="" />
          )}
          {activeTab === 'timeline' && (
            <AgentTimeline timeline={undefined} />
          )}
          {activeTab === 'report' && (
            <ReportPanel html={data.report_html || ''} />
          )}
        </div>
      </div>
    </div>
  );
};
