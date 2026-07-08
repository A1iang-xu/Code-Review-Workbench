import { type FC, useState, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import Editor from '@monaco-editor/react';
import { reviewApi, skillApi } from '../services/api';
import { Plus, Trash2, Play, Upload, FileText, Puzzle } from 'lucide-react';
import type { ReviewRequest } from '../types';

interface FileItem {
  path: string;
  content: string;
}

const detectLanguage = (path: string): string => {
  const ext = path.split('.').pop()?.toLowerCase();
  const map: Record<string, string> = {
    py: 'python', go: 'go', ts: 'typescript', tsx: 'typescript',
    js: 'javascript', jsx: 'javascript', java: 'java',
  };
  return map[ext || ''] || 'python';
};

export const ReviewCreate: FC = () => {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<FileItem[]>([
    { path: 'example.py', content: '# 在此粘贴或编辑代码...\n' },
  ]);
  const [activeFileIdx, setActiveFileIdx] = useState(0);
  const [repoUrl, setRepoUrl] = useState('');
  const [branch, setBranch] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedSkills, setSelectedSkills] = useState<string[]>([]);
  const [selectedLanguage, setSelectedLanguage] = useState<string>('auto');

  const { data: skills } = useQuery({
    queryKey: ['skills'],
    queryFn: skillApi.list,
  });

  const toggleSkill = (name: string) => {
    setSelectedSkills((prev) =>
      prev.includes(name) ? prev.filter((s) => s !== name) : [...prev, name]
    );
  };

  const addFile = () => {
    const name = `file_${files.length + 1}.py`;
    setFiles((prev) => [...prev, { path: name, content: '# 新文件\n' }]);
    setActiveFileIdx(files.length);
  };

  const removeFile = (idx: number) => {
    if (files.length <= 1) return;
    setFiles((prev) => prev.filter((_, i) => i !== idx));
    if (activeFileIdx >= idx) setActiveFileIdx(Math.max(0, activeFileIdx - 1));
  };

  const updateFileContent = (content: string | undefined) => {
    setFiles((prev) =>
      prev.map((f, i) => (i === activeFileIdx ? { ...f, content: content || '' } : f))
    );
  };

  const updateFilePath = (path: string) => {
    setFiles((prev) =>
      prev.map((f, i) => (i === activeFileIdx ? { ...f, path } : f))
    );
  };

  const handleFileUpload = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const uploaded = e.target.files;
    if (!uploaded) return;
    const readers: Promise<FileItem>[] = [];
    for (let i = 0; i < uploaded.length; i++) {
      const file = uploaded[i];
      readers.push(
        new Promise((resolve) => {
          const reader = new FileReader();
          reader.onload = () =>
            resolve({ path: file.name, content: (reader.result as string) || '' });
          reader.readAsText(file);
        })
      );
    }
    Promise.all(readers).then((newFiles) => {
      setFiles((prev) => [...prev, ...newFiles]);
      setActiveFileIdx(files.length);
    });
    // Reset input
    if (fileInputRef.current) fileInputRef.current.value = '';
  }, [files.length]);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    const validFiles = files.filter((f) => f.path.trim() && f.content.trim());
    const payload: ReviewRequest = {
      files: validFiles,
      repo_url: repoUrl,
      branch,
      language: selectedLanguage,
      enabled_skills: selectedSkills,
    };
    try {
      const res = await reviewApi.create(payload);
      navigate(`/reviews/${res.task_id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  const activeFile = files[activeFileIdx];

  return (
    <div className="space-y-4 fade-in max-w-6xl">
      {/* Repo info */}
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex-1 min-w-[200px]">
            <label className="block text-xs font-medium text-slate-500 mb-1">仓库 URL (可选)</label>
            <input
              type="text"
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
              placeholder="https://github.com/user/repo"
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-100 focus:border-blue-400 outline-none transition-all"
            />
          </div>
          <div className="w-40">
            <label className="block text-xs font-medium text-slate-500 mb-1">分支 (可选)</label>
            <input
              type="text"
              value={branch}
              onChange={(e) => setBranch(e.target.value)}
              placeholder="main"
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-100 focus:border-blue-400 outline-none transition-all"
            />
          </div>
          <div className="pt-5">
            <button
              onClick={submit}
              disabled={submitting || !files.some((f) => f.content.trim())}
              className="flex items-center gap-2 px-5 py-2 bg-blue-500 text-white rounded-lg text-sm font-medium hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-sm"
            >
              <Play size={14} />
              {submitting ? '提交中...' : '开始审查'}
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Language selector */}
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <div className="flex items-center gap-3">
          <label className="text-xs font-medium text-slate-500 whitespace-nowrap">审查语言</label>
          <select
            value={selectedLanguage}
            onChange={(e) => setSelectedLanguage(e.target.value)}
            className="px-3 py-1.5 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-100 focus:border-blue-400 outline-none transition-all bg-white"
          >
            <option value="auto">自动检测</option>
            <option value="python">Python</option>
            <option value="go">Go</option>
            <option value="typescript">TypeScript</option>
            <option value="javascript">JavaScript</option>
            <option value="java">Java</option>
          </select>
          <span className="text-xs text-slate-400">默认自动检测，可手动指定以获得更精准的分析</span>
        </div>
      </div>

      {/* Skill 选择 */}
      {skills && skills.length > 0 && (
        <div className="bg-white rounded-xl border border-slate-200 p-5">
          <div className="flex items-center gap-2 mb-3">
            <Puzzle size={16} className="text-blue-500" />
            <h4 className="text-sm font-semibold text-slate-700">Skill 扫描（可选）</h4>
            <span className="text-xs text-slate-400">
              启用的 Skill 将在 Agent 审查前对每个文件执行静态扫描，发现的问题会合并进报告
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            {skills.map((s) => (
              <button
                key={s.name}
                type="button"
                onClick={() => toggleSkill(s.name)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${
                  selectedSkills.includes(s.name)
                    ? 'border-blue-400 bg-blue-50 text-blue-700'
                    : 'border-slate-200 bg-white text-slate-600 hover:border-blue-200'
                }`}
                title={s.description}
              >
                {s.display_name}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* File tabs + Editor */}
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        {/* File tabs */}
        <div className="flex items-center border-b border-slate-200 px-3 py-1 overflow-x-auto bg-slate-50/50">
          {files.map((f, idx) => (
            <div key={f.path || `file-${idx}`} className="flex items-center">
              <button
                onClick={() => setActiveFileIdx(idx)}
                className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-t transition-all whitespace-nowrap ${
                  idx === activeFileIdx
                    ? 'bg-white text-blue-600 border-x border-t border-slate-200 -mb-px'
                    : 'text-slate-500 hover:text-slate-700'
                }`}
              >
                <FileText size={12} />
                {f.path}
              </button>
              {files.length > 1 && (
                <button
                  onClick={() => removeFile(idx)}
                  className="p-0.5 text-slate-400 hover:text-red-500 transition-colors mr-1"
                  title="移除文件"
                >
                  <Trash2 size={12} />
                </button>
              )}
            </div>
          ))}
          <div className="flex items-center gap-2 ml-auto pr-2">
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".py,.go,.ts,.tsx,.js,.jsx,.java"
              onChange={handleFileUpload}
              className="hidden"
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              className="flex items-center gap-1 px-2 py-1 text-xs text-slate-500 hover:text-blue-600 hover:bg-blue-50 rounded transition-all"
              title="上传文件"
            >
              <Upload size={12} />
              上传
            </button>
            <button
              onClick={addFile}
              className="flex items-center gap-1 px-2 py-1 text-xs text-slate-500 hover:text-blue-600 hover:bg-blue-50 rounded transition-all"
              title="添加文件"
            >
              <Plus size={12} />
              添加
            </button>
          </div>
        </div>

        {/* File path edit */}
        <div className="px-4 py-2 bg-slate-50 border-b border-slate-100 flex items-center gap-2">
          <span className="text-xs text-slate-400">路径:</span>
          <input
            type="text"
            value={activeFile?.path || ''}
            onChange={(e) => updateFilePath(e.target.value)}
            className="flex-1 bg-transparent text-xs text-slate-600 outline-none"
          />
        </div>

        {/* Monaco Editor */}
        <div style={{ height: 500 }}>
          <Editor
            height="100%"
            language={detectLanguage(activeFile?.path || '')}
            theme="vs-light"
            value={activeFile?.content || ''}
            onChange={updateFileContent}
            options={{
              minimap: { enabled: false },
              fontSize: 13,
              lineNumbers: 'on',
              scrollBeyondLastLine: false,
              wordWrap: 'on',
              tabSize: 4,
            }}
          />
        </div>
      </div>
    </div>
  );
};
