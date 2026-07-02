import { type FC, useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { reviewApi, triggerDownload } from '../services/api';
import { useReviewProgress } from '../hooks/useSSE';
import { IssueList } from '../components/review/IssueList';
import { DiffViewer } from '../components/review/DiffViewer';
import { AgentTimeline } from '../components/review/AgentTimeline';
import { ReportPanel } from '../components/review/ReportPanel';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { EmptyState } from '../components/common/EmptyState';
import { Star, AlertTriangle, FileCode, Activity, FileText, Download } from 'lucide-react';
import type { CodeIssue } from '../types';

type TabId = 'issues' | 'diff' | 'timeline' | 'report';

const tabs: { id: TabId; label: string; icon: typeof FileCode }[] = [
  { id: 'issues', label: '问题列表', icon: AlertTriangle },
  { id: 'diff', label: '代码对比', icon: FileCode },
  { id: 'timeline', label: 'Agent 时间线', icon: Activity },
  { id: 'report', label: '完整报告', icon: FileText },
];

// Map technical stage names to user-friendly Chinese display names
const getStageDisplayName = (stage: string): string => {
  const stageMap: Record<string, string> = {
    pending: '等待中',
    parse_code: '代码解析',
    agent_reviews: 'Agent 并行审查',
    arbitrate: '仲裁汇总',
    generate_report: '生成报告',
    done: '完成',
  };
  return stageMap[stage] || stage;
};

// Return the current running agent name based on progress percentage
const getCurrentAgent = (progress: number): string => {
  const pct = progress * 100;
  if (pct < 10) return '代码解析';
  if (pct < 25) return '风格检查 (style)';
  if (pct < 35) return '安全审计 (security)';
  if (pct < 45) return '架构分析 (architecture)';
  if (pct < 55) return '性能分析 (performance)';
  if (pct < 65) return '重构建议 (refactor)';
  if (pct < 90) return '仲裁汇总';
  return '生成报告';
};

export const ReviewDetail: FC = () => {
  const { taskId } = useParams<{ taskId: string }>();
  const [activeTab, setActiveTab] = useState<TabId>('issues');
  const [exporting, setExporting] = useState<'markdown' | 'pdf' | null>(null);

  const handleExport = async (format: 'markdown' | 'pdf') => {
    if (exporting || !taskId) return;
    setExporting(format);
    try {
      const blob = await reviewApi.export(taskId, format);
      const ext = format === 'markdown' ? 'md' : 'html';
      triggerDownload(blob, `review_${taskId}.${ext}`);
    } catch (err) {
      console.error('导出报告失败:', err);
    } finally {
      setExporting(null);
    }
  };

  // Fetch review result
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['review', taskId],
    queryFn: () => reviewApi.get(taskId!),
    enabled: !!taskId,
    // running/pending 状态下每 3 秒轮询兜底（SSE 断开时仍能更新）
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'running' || status === 'pending' ? 3000 : false;
    },
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
              当前阶段: {getStageDisplayName(progress.current_stage)}
            </p>
            <p className="text-xs text-slate-500 mt-1">
              正在执行: {getCurrentAgent(progress.progress)}
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

  // Running / pending: show progress indicator instead of full detail
  if (data.status === 'pending' || data.status === 'running') {
    return (
      <div className="space-y-4">
        <LoadingSpinner text="审查进行中..." />
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
              当前阶段: {getStageDisplayName(progress.current_stage)}
            </p>
            <p className="text-xs text-slate-500 mt-1">
              正在执行: {getCurrentAgent(progress.progress)}
            </p>
          </div>
        )}
      </div>
    );
  }

  // Parse issues from API response
  const issues: CodeIssue[] = data.issues || [];

  // Build diff content from original files
  const originalContent = data.files?.map((f) => {
    const header = `# ============================================================
# File: ${f.path}
# ============================================================\n`;
    return header + f.content;
  }).join('\n\n') || '';

  // Build modified content from issue suggestions (if available)
  const buildModifiedContent = () => {
    if (!data.files || data.files.length === 0) return '';
    const issuesWithSuggestions = issues.filter((i) => i.suggestion);
    // If no issues with suggestions, return original unchanged
    if (issuesWithSuggestions.length === 0) {
      return originalContent;
    }
    // For now, show original with issue annotations as comments
    return data.files.map((f) => {
      const fileIssues = issues.filter((i) => i.file_path === f.path);
      if (fileIssues.length === 0) {
        const header = `# ============================================================
# File: ${f.path} (No issues)
# ============================================================\n`;
        return header + f.content;
      }
      const lines = f.content.split('\n');
      const annotations = new Map<number, string[]>();
      fileIssues.forEach((issue) => {
        const line = issue.line_start || 1;
        const key = line - 1;
        if (!annotations.has(key)) annotations.set(key, []);
        annotations.get(key)!.push(`# [${(issue.severity || 'medium').toUpperCase()}] ${issue.agent_type}: ${issue.title}`);
      });
      const annotated = lines.map((line, idx) => {
        const notes = annotations.get(idx);
        return notes ? notes.join('\n') + '\n' + line : line;
      }).join('\n');
      const header = `# ============================================================
# File: ${f.path} (Annotated with issues)
# ============================================================\n`;
      return header + annotated;
    }).join('\n\n');
  };

  const modifiedContent = buildModifiedContent();

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
          {/* Export buttons */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => handleExport('markdown')}
              disabled={exporting !== null}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 text-xs font-medium text-slate-600 bg-white hover:bg-slate-50 hover:border-slate-300 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Download size={13} />
              {exporting === 'markdown' ? '导出中...' : '导出 Markdown'}
            </button>
            <button
              onClick={() => handleExport('pdf')}
              disabled={exporting !== null}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 text-xs font-medium text-slate-600 bg-white hover:bg-slate-50 hover:border-slate-300 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <FileText size={13} />
              {exporting === 'pdf' ? '导出中...' : '导出 PDF'}
            </button>
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
            <DiffViewer original={originalContent} modified={modifiedContent} />
          )}
          {activeTab === 'timeline' && (
            <AgentTimeline timeline={data.agent_timeline} />
          )}
          {activeTab === 'report' && (
            <ReportPanel html={data.report_html || ''} />
          )}
        </div>
      </div>
    </div>
  );
};
