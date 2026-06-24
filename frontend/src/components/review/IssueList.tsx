import { type FC, useState, useMemo } from 'react';
import { SeverityBadge } from '../common/SeverityBadge';
import type { CodeIssue } from '../../types';
import { ChevronDown, ChevronUp, Filter, Bot } from 'lucide-react';

interface Props {
  issues: CodeIssue[];
}

const severityOrder = ['critical', 'high', 'medium', 'low', 'info'] as const;

const severityLabels: Record<string, string> = {
  critical: '严重',
  high: '高危',
  medium: '中等',
  low: '低危',
  info: '提示',
};

const issueKey = (issue: CodeIssue) =>
  `${issue.file_path}:${issue.line_start}:${issue.title}`;

export const IssueList: FC<Props> = ({ issues }) => {
  const [filter, setFilter] = useState<string>('all');
  const [expandedSet, setExpandedSet] = useState<Set<string>>(new Set());

  const filtered = useMemo(() => {
    if (filter === 'all') return issues;
    return issues.filter((i) => i.severity === filter);
  }, [issues, filter]);

  const toggle = (key: string) => {
    setExpandedSet((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  if (issues.length === 0) {
    return (
      <div className="text-center py-12 text-slate-400">
        <Bot size={32} className="mx-auto mb-2 opacity-50" />
        <p>暂无发现问题</p>
      </div>
    );
  }

  return (
    <div>
      {/* Filter bar */}
      <div className="flex items-center gap-2 mb-4 flex-wrap">
        <Filter size={14} className="text-slate-400" />
        {['all', ...severityOrder].map((s) => (
          <button
            key={s}
            onClick={() => setFilter(s)}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-all ${
              filter === s
                ? 'bg-blue-500 text-white shadow-sm'
                : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
            }`}
          >
            {s === 'all' ? '全部' : severityLabels[s] || s}
          </button>
        ))}
        <span className="ml-auto text-xs text-slate-400">
          {filtered.length} / {issues.length} 条
        </span>
      </div>

      {/* Issue list */}
      <div className="space-y-2">
        {filtered.map((issue) => {
          const key = issueKey(issue);
          const isExpanded = expandedSet.has(key);
          return (
            <div
              key={key}
              className="bg-white border border-slate-200 rounded-lg hover:shadow-sm transition-shadow overflow-hidden"
            >
              {/* Header */}
              <button
                onClick={() => toggle(key)}
                className="w-full text-left px-4 py-3 flex items-start gap-3"
              >
                <SeverityBadge severity={issue.severity} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded">
                      {issue.agent_type}
                    </span>
                    <span className="text-xs text-slate-400">
                      {issue.file_path || '未知文件'}:{issue.line_start || 0}
                    </span>
                  </div>
                  <p className="text-sm font-medium text-slate-800 mt-1 truncate">
                    {issue.title}
                  </p>
                </div>
                {isExpanded ? (
                  <ChevronUp size={16} className="text-slate-400 mt-1 shrink-0" />
                ) : (
                  <ChevronDown size={16} className="text-slate-400 mt-1 shrink-0" />
                )}
              </button>

              {/* Expanded detail */}
              {isExpanded && (
                <div className="px-4 pb-4 border-t border-slate-100 pt-3 space-y-3 fade-in">
                  {issue.description && (
                    <div>
                      <p className="text-xs font-semibold text-slate-500 mb-1">问题描述</p>
                      <p className="text-sm text-slate-700">{issue.description}</p>
                    </div>
                  )}
                  {issue.suggestion && (
                    <div>
                      <p className="text-xs font-semibold text-slate-500 mb-1">修复建议</p>
                      <div className="text-sm text-blue-700 bg-blue-50 rounded-lg p-3 border border-blue-100">
                        {issue.suggestion}
                      </div>
                    </div>
                  )}
                  {issue.code_snippet && (
                    <div>
                      <p className="text-xs font-semibold text-slate-500 mb-1">代码片段</p>
                      <pre className="code-block text-xs">{issue.code_snippet}</pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
