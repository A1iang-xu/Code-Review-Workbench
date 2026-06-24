import { type FC } from 'react';

interface Props {
  html: string;
}

export const ReportPanel: FC<Props> = ({ html }) => {
  if (!html) {
    return (
      <div className="text-center py-12 text-slate-400">
        <p>暂无报告内容</p>
      </div>
    );
  }

  return (
    <div className="w-full max-w-full overflow-hidden">
      {/*
        Use iframe + srcdoc to fully isolate the HTML report from the parent
        React layout. The report is a complete HTML document (with <html>/<body>)
        which, when injected via dangerouslySetInnerHTML, would otherwise
        escape the sidebar's ml-60 margin and stretch edge-to-edge.
      */}
      <iframe
        title="代码审查报告"
        srcDoc={html}
        className="w-full bg-white rounded-lg border border-slate-200"
        style={{ height: '900px', display: 'block' }}
        sandbox="allow-same-origin"
      />
    </div>
  );
};
