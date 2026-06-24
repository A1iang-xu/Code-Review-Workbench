// ============================================================
// TypeScript 类型定义
// ============================================================

export interface CodeIssue {
  id?: string;
  agent_type: string;
  severity: string;
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
  status: string;
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
}

export interface ReviewResponse {
  task_id: string;
  status: string;
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

export interface ReviewListItem {
  task_id: string;
  repo_url: string;
  branch: string;
  status: string;
  score: number;
  issues_count: number;
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
