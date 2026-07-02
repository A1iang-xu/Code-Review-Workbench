import { type FC, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { skillApi } from '../services/api';
import Editor from '@monaco-editor/react';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { EmptyState } from '../components/common/EmptyState';
import { Puzzle, Play, RefreshCw, Tag, Code2, CheckCircle2, XCircle, Plus, Trash2, X } from 'lucide-react';
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

// 自定义 Skill 代码模板
const SKILL_TEMPLATE = `from app.core.skills.registry import BaseSkill, SkillMetadata, SkillResult, SkillCategory


class MySkill(BaseSkill):
    metadata = SkillMetadata(
        name="my_skill",
        display_name="我的 Skill",
        version="1.0.0",
        category=SkillCategory.UTILITY,
        description="自定义 Skill 示例",
        languages=["python"],
    )

    async def execute(self, code, file_path="<string>", context=None):
        findings = []
        # 在此实现检测逻辑
        return SkillResult(
            success=True,
            findings=findings,
            summary="扫描完成",
        )


skill = MySkill()
`;

export const SkillManager: FC = () => {
  const queryClient = useQueryClient();
  const [selectedSkill, setSelectedSkill] = useState<string | null>(null);
  const [testCode, setTestCode] = useState('# 输入测试代码\nprint("Hello, World!")\n');
  const [testResult, setTestResult] = useState<SkillExecuteResponse | null>(null);
  const [testing, setTesting] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState({
    name: '',
    display_name: '',
    description: '',
    category: 'utility',
    code: SKILL_TEMPLATE,
  });
  const [createError, setCreateError] = useState<string | null>(null);

  const { data: skills, isLoading } = useQuery({
    queryKey: ['skills'],
    queryFn: skillApi.list,
  });

  const reloadMut = useMutation({
    mutationFn: skillApi.reload,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['skills'] }),
  });

  const createMut = useMutation({
    mutationFn: skillApi.createCustom,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skills'] });
      setShowCreate(false);
      setCreateError(null);
      setCreateForm({ name: '', display_name: '', description: '', category: 'utility', code: SKILL_TEMPLATE });
    },
    onError: (err: unknown) => {
      setCreateError(err instanceof Error ? err.message : '创建失败');
    },
  });

  const deleteMut = useMutation({
    mutationFn: skillApi.deleteCustom,
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

  const handleDelete = (name: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (window.confirm(`确认删除自定义 Skill "${name}"？`)) {
      deleteMut.mutate(name);
    }
  };

  const submitCreate = () => {
    setCreateError(null);
    if (!createForm.name.trim() || !createForm.display_name.trim()) {
      setCreateError('名称和展示名称不能为空');
      return;
    }
    createMut.mutate(createForm);
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
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-blue-500 rounded-lg hover:bg-blue-600 transition-all"
          >
            <Plus size={14} />
            添加自定义
          </button>
          <button
            onClick={() => reloadMut.mutate()}
            disabled={reloadMut.isPending}
            className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-slate-600 bg-slate-100 rounded-lg hover:bg-slate-200 disabled:opacity-50 transition-all"
          >
            <RefreshCw size={14} className={reloadMut.isPending ? 'animate-spin' : ''} />
            重新加载
          </button>
        </div>
      </div>

      {/* Skill cards */}
      {(!skills || skills.length === 0) ? (
        <EmptyState icon={<Puzzle size={48} />} title="暂无已注册的 Skill" description={'点击"添加自定义"创建，或检查后端 Skill 系统是否正确初始化'} />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {skills.map((s: SkillMeta) => (
            <div
              key={s.name}
              onClick={() => {
                setSelectedSkill(s.name);
                setTestResult(null);
              }}
              className={`text-left p-5 rounded-xl border-2 transition-all cursor-pointer relative ${
                selectedSkill === s.name
                  ? 'border-blue-400 bg-blue-50/50 shadow-md'
                  : 'border-slate-200 bg-white hover:border-blue-200 hover:shadow-sm'
              }`}
            >
              <div className="flex items-start justify-between mb-2">
                <h4 className="text-sm font-semibold text-slate-800">{s.display_name}</h4>
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-slate-400">{s.version}</span>
                  {/* 自定义 Skill 显示删除按钮（通过 tags 判断或文件存在性） */}
                  {s.tags.includes('custom') && (
                    <button
                      onClick={(e) => handleDelete(s.name, e)}
                      className="text-slate-400 hover:text-red-500 transition-colors"
                      title="删除自定义 Skill"
                    >
                      <Trash2 size={12} />
                    </button>
                  )}
                </div>
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
            </div>
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

      {/* 创建自定义 Skill 弹窗 */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-3xl max-h-[90vh] flex flex-col">
            {/* 弹窗头部 */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200">
              <h3 className="text-base font-semibold text-slate-800">添加自定义 Skill</h3>
              <button
                onClick={() => setShowCreate(false)}
                className="text-slate-400 hover:text-slate-600 transition-colors"
              >
                <X size={18} />
              </button>
            </div>

            {/* 弹窗内容 */}
            <div className="flex-1 overflow-y-auto p-6 space-y-4">
              {createError && (
                <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
                  {createError}
                </div>
              )}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-slate-500 mb-1">Skill 名称（小写字母+下划线）</label>
                  <input
                    type="text"
                    value={createForm.name}
                    onChange={(e) => setCreateForm({ ...createForm, name: e.target.value })}
                    placeholder="my_skill"
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-100 focus:border-blue-400 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-500 mb-1">展示名称</label>
                  <input
                    type="text"
                    value={createForm.display_name}
                    onChange={(e) => setCreateForm({ ...createForm, display_name: e.target.value })}
                    placeholder="我的 Skill"
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-100 focus:border-blue-400 outline-none"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-slate-500 mb-1">分类</label>
                  <select
                    value={createForm.category}
                    onChange={(e) => setCreateForm({ ...createForm, category: e.target.value })}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-100 focus:border-blue-400 outline-none bg-white"
                  >
                    {Object.entries(categoryLabels).map(([val, label]) => (
                      <option key={val} value={val}>{label}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-500 mb-1">描述</label>
                  <input
                    type="text"
                    value={createForm.description}
                    onChange={(e) => setCreateForm({ ...createForm, description: e.target.value })}
                    placeholder="Skill 功能描述"
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-100 focus:border-blue-400 outline-none"
                  />
                </div>
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 mb-1">Skill 代码（需定义 skill 变量）</label>
                <div style={{ height: 320 }}>
                  <Editor
                    height="100%"
                    language="python"
                    theme="vs-light"
                    value={createForm.code}
                    onChange={(v) => setCreateForm({ ...createForm, code: v || '' })}
                    options={{
                      minimap: { enabled: false },
                      fontSize: 13,
                      lineNumbers: 'on',
                      scrollBeyondLastLine: false,
                    }}
                  />
                </div>
              </div>
            </div>

            {/* 弹窗底部 */}
            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-slate-200 bg-slate-50">
              <button
                onClick={() => setShowCreate(false)}
                className="px-4 py-2 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-all"
              >
                取消
              </button>
              <button
                onClick={submitCreate}
                disabled={createMut.isPending}
                className="px-4 py-2 text-sm font-medium text-white bg-blue-500 rounded-lg hover:bg-blue-600 disabled:opacity-50 transition-all"
              >
                {createMut.isPending ? '创建中...' : '创建'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
