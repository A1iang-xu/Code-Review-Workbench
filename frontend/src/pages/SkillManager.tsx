import { type FC, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { skillApi } from '../services/api';
import Editor from '@monaco-editor/react';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { EmptyState } from '../components/common/EmptyState';
import { Puzzle, Play, RefreshCw, Tag, Code2, CheckCircle2, XCircle } from 'lucide-react';
import type { SkillMeta, SkillExecuteResponse } from '../types';

const categoryColors: Record<string, string> = {
  static_analysis: 'bg-blue-50 text-blue-600',
  pattern_match: 'bg-purple-50 text-purple-600',
  security: 'bg-red-50 text-red-600',
  architecture: 'bg-indigo-50 text-indigo-600',
  performance: 'bg-amber-50 text-amber-600',
  style: 'bg-teal-50 text-teal-600',
  utility: 'bg-slate-100 text-slate-600',
};

const categoryLabels: Record<string, string> = {
  static_analysis: '静态分析',
  pattern_match: '模式匹配',
  security: '安全',
  architecture: '架构',
  performance: '性能',
  style: '风格',
  utility: '工具',
};

export const SkillManager: FC = () => {
  const queryClient = useQueryClient();
  const [selectedSkill, setSelectedSkill] = useState<string | null>(null);
  const [testCode, setTestCode] = useState('# 输入测试代码\nprint("Hello, World!")\n');
  const [testResult, setTestResult] = useState<SkillExecuteResponse | null>(null);
  const [testing, setTesting] = useState(false);

  const { data: skills, isLoading } = useQuery({
    queryKey: ['skills'],
    queryFn: skillApi.list,
  });

  const reloadMut = useMutation({
    mutationFn: skillApi.reload,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['skills'] }),
  });

  const runTest = async () => {
    if (!selectedSkill) return;
    setTesting(true);
    try {
      const res = await skillApi.execute({
        skill_name: selectedSkill,
        code: testCode,
        file_path: 'test.py',
      });
      setTestResult(res);
    } catch (err) {
      setTestResult({
        success: false,
        skill_name: selectedSkill,
        summary: `Error: ${err instanceof Error ? err.message : 'Unknown'}`,
        findings: [],
        execution_time_ms: 0,
      });
    } finally {
      setTesting(false);
    }
  };

  if (isLoading) return <LoadingSpinner text="加载 Skill 列表..." />;

  return (
    <div className="space-y-6 fade-in max-w-6xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Puzzle size={20} className="text-blue-500" />
          <h3 className="text-lg font-semibold text-slate-800">已注册 Skill</h3>
          {skills && <span className="text-xs text-slate-400 bg-slate-100 px-2 py-0.5 rounded-full">{skills.length} 个</span>}
        </div>
        <button
          onClick={() => reloadMut.mutate()}
          disabled={reloadMut.isPending}
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-slate-600 bg-slate-100 rounded-lg hover:bg-slate-200 disabled:opacity-50 transition-all"
        >
          <RefreshCw size={14} className={reloadMut.isPending ? 'animate-spin' : ''} />
          重新加载
        </button>
      </div>

      {/* Skill cards */}
      {(!skills || skills.length === 0) ? (
        <EmptyState icon={<Puzzle size={48} />} title="暂无已注册的 Skill" description="请检查后端 Skill 系统是否正确初始化" />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {skills.map((s: SkillMeta) => (
            <button
              key={s.name}
              onClick={() => {
                setSelectedSkill(s.name);
                setTestResult(null);
              }}
              className={`text-left p-5 rounded-xl border-2 transition-all ${
                selectedSkill === s.name
                  ? 'border-blue-400 bg-blue-50/50 shadow-md'
                  : 'border-slate-200 bg-white hover:border-blue-200 hover:shadow-sm'
              }`}
            >
              <div className="flex items-start justify-between mb-2">
                <h4 className="text-sm font-semibold text-slate-800">{s.display_name}</h4>
                <span className="text-[11px] text-slate-400">{s.version}</span>
              </div>
              <p className="text-xs text-slate-500 mb-3 line-clamp-2">{s.description}</p>
              <div className="flex items-center gap-2 flex-wrap">
                <span
                  className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium ${
                    categoryColors[s.category] || 'bg-slate-100 text-slate-600'
                  }`}
                >
                  <Tag size={10} />
                  {categoryLabels[s.category] || s.category}
                </span>
                {s.languages.map((lang: string) => (
                  <span
                    key={lang}
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-slate-100 text-[11px] text-slate-600"
                  >
                    <Code2 size={10} />
                    {lang}
                  </span>
                ))}
              </div>
            </button>
          ))}
        </div>
      )}

      {/* Test panel */}
      {selectedSkill && (
        <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
          <div className="px-5 py-3 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
            <span className="text-sm font-medium text-slate-700">
              测试 Skill: <span className="text-blue-600">{selectedSkill}</span>
            </span>
            <button
              onClick={runTest}
              disabled={testing}
              className="flex items-center gap-2 px-4 py-1.5 bg-blue-500 text-white rounded-lg text-xs font-medium hover:bg-blue-600 disabled:opacity-50 transition-all"
            >
              <Play size={12} />
              {testing ? '执行中...' : '执行测试'}
            </button>
          </div>
          <div style={{ height: 250 }}>
            <Editor
              height="100%"
              language="python"
              theme="vs-light"
              value={testCode}
              onChange={(v) => setTestCode(v || '')}
              options={{
                minimap: { enabled: false },
                fontSize: 13,
                lineNumbers: 'on',
                scrollBeyondLastLine: false,
              }}
            />
          </div>
          {testResult && (
            <div
              className={`mx-5 mb-5 mt-3 p-4 rounded-lg border ${
                testResult.success
                  ? 'bg-emerald-50 border-emerald-200'
                  : 'bg-red-50 border-red-200'
              }`}
            >
              <div className="flex items-center gap-2 mb-1">
                {testResult.success ? (
                  <CheckCircle2 size={16} className="text-emerald-500" />
                ) : (
                  <XCircle size={16} className="text-red-500" />
                )}
                <span className="text-sm font-medium text-slate-700">
                  {testResult.success ? '执行成功' : '执行失败'}
                </span>
                {testResult.execution_time_ms > 0 && (
                  <span className="text-xs text-slate-400 ml-auto">
                    {testResult.execution_time_ms.toFixed(0)}ms
                  </span>
                )}
              </div>
              <p className="text-sm text-slate-600">{testResult.summary}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
