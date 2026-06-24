import { type FC } from 'react';
import { Settings as SettingsIcon, Database, Brain, Key } from 'lucide-react';

export const Settings: FC = () => (
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
            defaultValue="glm-5.2"
            disabled
            className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm bg-slate-50"
          />
          <p className="text-[11px] text-slate-400 mt-0.5">用于安全审计、架构分析、重构建议、仲裁汇总</p>
        </div>
        <div>
          <label className="block text-xs text-slate-500 mb-1">工具模型</label>
          <input
            type="text"
            defaultValue="ollama/qwen2.5:7b"
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
          <input type="text" defaultValue="localhost" disabled className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm bg-slate-50" />
        </div>
        <div>
          <label className="block text-xs text-slate-500 mb-1">端口</label>
          <input type="text" defaultValue="5432" disabled className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm bg-slate-50" />
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
          <label className="block text-xs text-slate-500 mb-1">智谱 AI (GLM-5.2)</label>
          <input
            type="password"
            defaultValue="••••••••••••••••"
            disabled
            className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm bg-slate-50"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-500 mb-1">DeepSeek (V4)</label>
          <input
            type="password"
            defaultValue="••••••••••••••••"
            disabled
            className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm bg-slate-50"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-500 mb-1">Ollama Base URL</label>
          <input
            type="text"
            defaultValue="http://localhost:11434"
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
