import axios from 'axios';
import type {
  ReviewRequest,
  ReviewResponse,
  ReviewListResponse,
  ReviewStats,
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

  /** 列出审查任务 */
  list: (params?: { limit?: number; offset?: number }) =>
    api.get<ReviewListResponse>('/reviews', { params }).then(r => r.data),

  /** 审查统计概览 */
  stats: () =>
    api.get<ReviewStats>('/reviews/stats/summary').then(r => r.data),
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
