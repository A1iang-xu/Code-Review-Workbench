import { type FC, useState } from 'react';
import Editor, { DiffEditor } from '@monaco-editor/react';

const languages = [
  { id: 'python', label: 'Python' },
  { id: 'go', label: 'Go' },
  { id: 'typescript', label: 'TypeScript' },
  { id: 'javascript', label: 'JavaScript' },
  { id: 'java', label: 'Java' },
];

interface Props {
  original: string;
  modified: string;
}

export const DiffViewer: FC<Props> = ({ original, modified }) => {
  const [language, setLanguage] = useState('python');
  const hasModified = modified && modified.trim().length > 0;

  return (
    <div className="space-y-2">
      {/* Language selector */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-slate-500">语言:</span>
        {languages.map((lang) => (
          <button
            key={lang.id}
            onClick={() => setLanguage(lang.id)}
            className={`px-2.5 py-1 rounded text-xs font-medium transition-all ${
              language === lang.id
                ? 'bg-blue-500 text-white'
                : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
            }`}
          >
            {lang.label}
          </button>
        ))}
      </div>

      {hasModified ? (
        /* Monaco Diff Editor — 有修改内容时显示对比 */
        <div className="border border-slate-200 rounded-lg overflow-hidden" style={{ height: 500 }}>
          <DiffEditor
            height="100%"
            language={language}
            original={original}
            modified={modified}
            theme="vs-light"
            options={{
              renderSideBySide: true,
              readOnly: true,
              minimap: { enabled: false },
              scrollBeyondLastLine: false,
              fontSize: 13,
              lineNumbers: 'on',
              folding: true,
              wordWrap: 'on',
            }}
          />
        </div>
      ) : (
        /* Monaco 普通编辑器 — 无修改内容时仅展示原始代码 */
        <div className="border border-slate-200 rounded-lg overflow-hidden" style={{ height: 500 }}>
          {original ? (
            <Editor
              height="100%"
              language={language}
              value={original}
              theme="vs-light"
              options={{
                readOnly: true,
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
                fontSize: 13,
                lineNumbers: 'on',
                folding: true,
                wordWrap: 'on',
              }}
            />
          ) : (
            <div className="flex items-center justify-center h-full text-slate-400">
              <p>暂无代码内容</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
