import { type FC } from 'react';
import { Settings as SettingsIcon, Database, Brain, Key } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { reviewApi } from '../services/api';
import { LoadingSpinner } from '../components/common/LoadingSpinner';

export const Settings: FC = () => {
  const { data: config, isLoading } = useQuery({
    queryKey: ['system-config'],
    queryFn: reviewApi.getConfig,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <LoadingSpinner />
      </div>
    );
  }

  return (
    <div className="space-y-6 fade-in max-w-3xl">
      <div className="flex items-center gap-3 mb-2">
        <SettingsIcon size={20} className="text-slate-500" />
        <h3 className="text-lg font-semibold text-slate-800">设置</h3>
      </div>

      {/* LLM */}
      <div className="bg-white rounded-xl border border-slate-200 p-6">
        <div className="flex items-center gap-3 mb-4">
          <Brain size={18} className="text-purple-500" />
          <h4 className="text-sm font-semibold text-slate-700">LLM 配置</h4>
        </div>
        <div className="space-y-3">
          <div>
            <label className="block text-xs text-slate-500 mb-1">推理模型</label>
            <input
              type="text"
              defaultValue={config?.llm_reasoning_model ?? '—'}
              disabled
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm bg-slate-50"
            />
            <p className="text-[11px] text-slate-400 mt-0.5">用于安全审计、架构分析、重构建议、仲裁汇总</p>
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">工具模型</label>
            <input
              type="text"
              defaultValue={config?.llm_utility_model ?? '—'}
              disabled
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm bg-slate-50"
            />
            <p className="text-[11px] text-slate-400 mt-0.5">用于风格检查、代码摘要、消息压缩等高频轻量任务</p>
          </div>
        </div>
      </div>

      {/* Database */}
      <div className="bg-white rounded-xl border border-slate-200 p-6">
        <div className="flex items-center gap-3 mb-4">
          <Database size={18} className="text-blue-500" />
          <h4 className="text-sm font-semibold text-slate-700">数据库</h4>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-slate-500 mb-1">主机</label>
            <input type="text" defaultValue={config?.postgres_host ?? '—'} disabled className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm bg-slate-50" />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">端口</label>
            <input type="text" defaultValue={config?.postgres_port ?? '—'} disabled className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm bg-slate-50" />
          </div>
        </div>
      </div>

      {/* API Keys */}
      <div className="bg-white rounded-xl border border-slate-200 p-6">
        <div className="flex items-center gap-3 mb-4">
          <Key size={18} className="text-amber-500" />
          <h4 className="text-sm font-semibold text-slate-700">API Keys</h4>
        </div>
        <div className="space-y-3">
          <div>
            <label className="block text-xs text-slate-500 mb-1">智谱 AI (GLM)</label>
            <input
              type="text"
              defaultValue={config?.zhipu_api_key_masked ?? '—'}
              disabled
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm bg-slate-50"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">DeepSeek</label>
            <input
              type="text"
              defaultValue={config?.deepseek_api_key_masked ?? '—'}
              disabled
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm bg-slate-50"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">Ollama Base URL</label>
            <input
              type="text"
              defaultValue={config?.ollama_base_url ?? '—'}
              disabled
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm bg-slate-50"
            />
          </div>
        </div>
      </div>

      <p className="text-xs text-slate-400 text-center">
        设置目前为只读预览，配置修改请在 .env 文件中进行。
      </p>
    </div>
  );
};
