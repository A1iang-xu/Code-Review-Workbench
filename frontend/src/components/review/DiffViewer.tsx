import { type FC, useMemo } from 'react';
import Editor, { DiffEditor } from '@monaco-editor/react';

interface Props {
  original: string;
  modified: string;
}

/** 根据内容头部注释中的 File: 路径推断主要语言 */
const detectLanguageFromContent = (content: string): string => {
  // 从注释头中提取第一个文件路径
  const match = content.match(/# File:\s*(.+)/);
  if (match) {
    const ext = match[1].split('.').pop()?.toLowerCase().trim();
    const map: Record<string, string> = {
      py: 'python', go: 'go', ts: 'typescript', tsx: 'typescript',
      js: 'javascript', jsx: 'javascript', java: 'java',
    };
    if (ext && map[ext]) return map[ext];
  }
  return 'python';
};

export const DiffViewer: FC<Props> = ({ original, modified }) => {
  const language = useMemo(() => detectLanguageFromContent(original), [original]);
  const hasModified = modified && modified.trim().length > 0 && modified !== original;

  return (
    <div className="space-y-2">
      {hasModified ? (
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
