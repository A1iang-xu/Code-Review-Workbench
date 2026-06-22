import axios from 'axios';
import type {
  ReviewRequest,
  ReviewResponse,
  SkillExecuteRequest,
  SkillExecuteResponse,
  SkillMeta,
} from '../types';

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 120000,
  headers: { 'Content-Type': 'application/json' },
});

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

  /** SSE 实时进度（返回 EventSource 实例） */
  streamProgress: (taskId: string): EventSource => {
    return new EventSource(`/api/v1/reviews/${taskId}/stream`);
  },
};

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

  /** 重新加载 Skill */
  reload: async (): Promise<{ success: boolean; loaded_count: number }> => {
    const res = await api.post('/skills/reload');
    return res.data;
  },
};

export default api;
