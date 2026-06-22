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
    <div
      className="max-w-none"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
};
