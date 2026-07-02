import axios, { AxiosError, type AxiosInstance } from 'axios';
import type {
  ReviewRequest,
  ReviewResponse,
  ReviewListResponse,
  ReviewStats,
  SkillExecuteRequest,
  SkillExecuteResponse,
  SkillMeta,
  ApiErrorResponse,
} from '../types';

const api: AxiosInstance = axios.create({
  baseURL: '/api/v1',
  timeout: 120000,
  headers: { 'Content-Type': 'application/json' },
});

// ============================================================
// 请求拦截器：注入 traceId（无鉴权场景，留作扩展点）
// ============================================================
api.interceptors.request.use(
  (config) => {
    // 统一注入请求 ID，便于后端日志关联
    const traceId = `req-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    config.headers['X-Request-Id'] = traceId;
    return config;
  },
  (error) => Promise.reject(error),
);

// ============================================================
// 响应拦截器：统一错误处理
// ============================================================
// 后端全局异常处理器返回 {code, message, detail?, path?}
// 此处提取为标准化的 ApiError，调用方可通过 error.code 区分错误类型
export class ApiError extends Error {
  code: string;
  detail?: unknown;
  path?: string;
  status: number;

  constructor(status: number, code: string, message: string, detail?: unknown, path?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.path = path;
  }
}

// 订阅者模式：允许 UI 层（如 ToastProvider）监听全局错误
type ErrorListener = (error: ApiError) => void;
const errorListeners: Set<ErrorListener> = new Set();

export function subscribeApiError(listener: ErrorListener): () => void {
  errorListeners.add(listener);
  return () => errorListeners.delete(listener);
}

function notifyErrorListeners(error: ApiError): void {
  errorListeners.forEach((l) => {
    try {
      l(error);
    } catch {
      // 监听器本身抛错不应影响主流程
    }
  });
}

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiErrorResponse>) => {
    // 取消请求不视为错误
    if (axios.isCancel(error)) {
      return Promise.reject(error);
    }

    const status = error.response?.status ?? 0;
    const body = error.response?.data;

    // 提取后端统一错误结构
    const code = body?.code ?? 'UNKNOWN_ERROR';
    const message = body?.message ?? error.message ?? '请求失败';
    const detail = body?.detail;
    const path = body?.path;

    const apiError = new ApiError(status, code, message, detail, path);

    // 网络错误（无 response）
    if (status === 0) {
      apiError.message = '网络连接失败，请检查网络或后端服务是否运行';
      apiError.code = 'NETWORK_ERROR';
    }

    // 通知全局监听器（Toast/通知中心可订阅）
    notifyErrorListeners(apiError);

    return Promise.reject(apiError);
  },
);

// ---- 审查 API ----

export const reviewApi = {
  /** 创建审查任务 */
  create: async (data: ReviewRequest): Promise<ReviewResponse> => {
    const res = await api.post<ReviewResponse>('/reviews', data);
    return res.data;
  },

  /** 查询审查结果 */
  get: async (taskId: string): Promise<ReviewResponse> => {
    const res = await api.get<ReviewResponse>(`/reviews/${taskId}`);
    return res.data;
  },

  /** 列出审查任务（支持搜索和过滤） */
  list: (params?: {
    limit?: number;
    offset?: number;
    search?: string;
    repo?: string;
    minScore?: number;
    maxScore?: number;
    status?: string;
  }) => api.get<ReviewListResponse>('/reviews', { params }).then(r => r.data),

  /** 审查统计概览 */
  stats: () =>
    api.get<ReviewStats>('/reviews/stats/summary').then(r => r.data),

  /** 导出审查报告，返回 Blob */
  export: async (taskId: string, format: 'markdown' | 'pdf'): Promise<Blob> => {
    const res = await api.get(`/reviews/${taskId}/export`, {
      params: { format },
      responseType: 'blob',
    });
    return res.data;
  },
};

// ---- 工具函数：触发浏览器下载（从 service 层剥离 DOM 操作） ----

export function triggerDownload(blob: Blob, filename: string): void {
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.URL.revokeObjectURL(url);
}

// ---- Skill API ----

export const skillApi = {
  /** 列出所有 Skill */
  list: async (): Promise<SkillMeta[]> => {
    const res = await api.get<SkillMeta[]>('/skills');
    return res.data;
  },

  /** 执行指定 Skill */
  execute: async (data: SkillExecuteRequest): Promise<SkillExecuteResponse> => {
    const res = await api.post<SkillExecuteResponse>('/skills/execute', data);
    return res.data;
  },

  /** 重新加载 Skill（内置 + 自定义） */
  reload: async (): Promise<{ success: boolean; loaded_count: number; builtin_count: number; custom_count: number }> => {
    const res = await api.post('/skills/reload');
    return res.data;
  },

  /** 添加自定义 Skill */
  createCustom: async (data: {
    name: string;
    display_name: string;
    description?: string;
    category?: string;
    code: string;
  }): Promise<{ success: boolean; name: string; message: string }> => {
    const res = await api.post('/skills/custom', data);
    return res.data;
  },

  /** 删除自定义 Skill */
  deleteCustom: async (name: string): Promise<{ success: boolean; name: string; message: string }> => {
    const res = await api.delete(`/skills/custom/${name}`);
    return res.data;
  },
};

export default api;
