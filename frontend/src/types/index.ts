// ============================================================
// TypeScript 类型定义
// ============================================================

// ---- 枚举字面量联合类型（编译期校验，避免拼写错误） ----

/** 问题严重级别 */
export type Severity = 'critical' | 'high' | 'medium' | 'low' | 'info';

/** 审查任务状态 */
export type ReviewStatus = 'pending' | 'running' | 'completed' | 'failed';

/** Agent 类型（与后端 orchestrator 注册的 Agent 保持一致） */
export type AgentType =
  | 'style'
  | 'security'
  | 'architecture'
  | 'performance'
  | 'refactor'
  | 'arbitrator';

export interface CodeIssue {
  id?: string;
  agent_type: string;
  severity: Severity;
  title: string;
  file_path?: string;
  line_start?: number;
  line_end?: number;
  category?: string;
  description?: string;
  suggestion?: string;
  code_snippet?: string;
}

export interface AgentTimelineStep {
  agent_type: string;
  display_name: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  duration_ms: number;
  finding_count: number;
}

export interface ReviewProgress {
  task_id: string;
  status: ReviewStatus;
  current_stage: string;
  progress: number;
  completed_agents?: string[];
}

export interface SkillMeta {
  name: string;
  display_name: string;
  version: string;
  category: string;
  description: string;
  languages: string[];
  tags: string[];
}

export interface ReviewRequest {
  files: { path: string; content: string }[];
  repo_url?: string;
  branch?: string;
  language?: string;
  enabled_skills?: string[];
}

export interface ReviewResponse {
  task_id: string;
  status: ReviewStatus;
  summary?: string;
  score?: number;
  report_html?: string;
  issues_count?: number;
  stats?: Record<string, number>;
  issues?: CodeIssue[];
  agent_timeline?: AgentTimelineStep[];
  files?: { path: string; content: string }[];
  errors?: string[];
}

export interface SkillExecuteRequest {
  skill_name: string;
  code: string;
  file_path: string;
}

export interface SkillExecuteResponse {
  success: boolean;
  skill_name: string;
  summary: string;
  findings: CodeIssue[];
  execution_time_ms: number;
}

/**
 * 审查列表项。
 * 注意：repo_url / branch / score 在数据库层可能为空，
 * 前端使用时需做 null 检查（Dashboard 已用 `||` 兜底）。
 */
export interface ReviewListItem {
  task_id: string;
  repo_url?: string;
  branch?: string;
  status: ReviewStatus;
  score?: number;
  issues_count?: number;
  created_at: string;
}

export interface ReviewListResponse {
  total: number;
  items: ReviewListItem[];
}

export interface ReviewStats {
  total_reviews: number;
  avg_score: number;
  active_agents: number;
  registered_skills: number;
}

// ---- API 统一错误响应格式（与后端 main.py 全局异常处理器对齐） ----

export interface ApiErrorResponse {
  code: string;
  message: string;
  detail?: unknown;
  path?: string;
}
