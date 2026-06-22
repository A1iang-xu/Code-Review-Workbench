# API 参考文档

Base URL: `http://localhost:8000`

所有 API 响应均为 JSON 格式。错误响应统一格式：

```json
{
  "detail": "错误描述"
}
```

---

## 健康检查与监控

### GET /health

健康检查端点。

**响应 200:**

```json
{
  "status": "ok",
  "app": "code-review-workbench",
  "env": "production",
  "version": "0.3.0"
}
```

### GET /metrics

Prometheus 指标端点。返回 Prometheus 文本格式。

**响应 200:** `text/plain` — Prometheus metrics 文本

---

## 测试端点

### POST /api/test/llm

测试 LLM 连通性。

**响应 200:**

```json
{
  "reasoning": {
    "model": "glm-5.2",
    "status": "ok",
    "response": "ok"
  },
  "utility": {
    "model": "ollama/qwen2.5:7b",
    "status": "ok",
    "response": "ok"
  }
}
```

---

## 审查 API

### POST /api/v1/reviews

提交代码审查任务。5 个 Agent 并行审查 + 仲裁汇总。

**请求体:**

```json
{
  "files": [
    {
      "path": "src/main.py",
      "content": "def hello():\\n    print('world')\\n"
    }
  ],
  "repo_url": "https://github.com/user/repo",
  "branch": "main",
  "language": "python"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| files | array | 是 | 待审查的代码文件列表 |
| files[].path | string | 是 | 文件路径 |
| files[].content | string | 是 | 文件源代码 |
| repo_url | string | 否 | Git 仓库 URL |
| branch | string | 否 | 分支名 |
| language | string | 否 | 审查语言: auto/python/go/typescript/javascript/java (默认 auto) |

**响应 200:**

```json
{
  "task_id": "abc12345-6789-...",
  "status": "completed",
  "summary": "代码审查完成，共发现 5 个问题。其中严重问题 1 个...",
  "score": 7.5,
  "report_html": "<!DOCTYPE html>...",
  "issues_count": 5,
  "stats": {
    "security": 2,
    "style": 2,
    "architecture": 1
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| task_id | string | 任务唯一 ID |
| status | string | completed / completed_with_errors / failed |
| summary | string | 审查摘要 (中文) |
| score | float | 综合评分 0-10 |
| report_html | string | 完整 HTML 报告 |
| issues_count | int | 去重后的问题总数 |
| stats | object | 各 Agent 发现数 |

### GET /api/v1/reviews/{task_id}

查询审查结果。

**路径参数:**

| 参数 | 类型 | 说明 |
|------|------|------|
| task_id | string | 任务 ID |

**响应 200:** 同 `POST /api/v1/reviews` 响应格式

### GET /api/v1/reviews/{task_id}/stream

SSE 实时进度推送。

**事件类型:**

```
event: progress
data: {"task_id": "...", "stage": "security_review", "progress": 0.45, "status": "running"}

event: complete
data: {"task_id": "...", "stage": "done", "progress": 1.0}

event: error
data: {"task_id": "...", "error": "审查失败原因"}
```

---

## Skill API

### GET /api/v1/skills

列出所有已注册 Skill。

**响应 200:**

```json
[
  {
    "name": "ast_scan",
    "display_name": "AST 结构化扫描",
    "version": "1.0.0",
    "category": "static_analysis",
    "description": "基于 Tree-sitter 解析代码结构",
    "languages": ["python"],
    "tags": ["ast", "static"]
  }
]
```

### POST /api/v1/skills/execute

执行指定 Skill。

**请求体:**

```json
{
  "skill_name": "ast_scan",
  "code": "def hello():\n    pass\n",
  "file_path": "example.py"
}
```

**响应 200:**

```json
{
  "success": true,
  "skill_name": "ast_scan",
  "summary": "发现 1 个函数, 0 个类",
  "findings": [
    {
      "type": "function",
      "name": "hello",
      "line": 1
    }
  ],
  "execution_time_ms": 12.5
}
```

### POST /api/v1/skills/reload

重新加载所有内置 Skill。

**响应 200:**

```json
{
  "success": true,
  "loaded_count": 10,
  "message": "已重新加载 10 个内置 Skill"
}
```

---

## Webhook API

### POST /api/v1/webhooks/github

GitHub Webhook 端点。接收 Pull Request 事件并自动触发审查。

**Headers:**

| Header | 说明 |
|--------|------|
| X-GitHub-Event | 事件类型 (需为 `pull_request`) |
| X-Hub-Signature-256 | HMAC-SHA256 签名 |

**支持的操作:** opened、synchronize、reopened

**响应 200:**

```json
{
  "message": "Review scheduled",
  "delivery_id": "abc123...",
  "owner": "user",
  "repo": "repo",
  "pr": 42
}
```

**响应 403:** (签名验证失败)

```json
{
  "detail": "Invalid webhook signature"
}
```

**审查流程:**
1. 设置 Commit Status → `pending`
2. 获取 PR 变更文件列表
3. 过滤代码文件 (排除 .md/.json/.yaml 等)
4. 获取每个文件的完整内容
5. 运行 LangGraph 审查流水线
6. 创建 PR Review 汇总评论 (含评分和统计表格)
7. 对 critical/high 问题添加行内评论 (最多 5 条)
8. 设置最终 Commit Status → `success`/`error`

**评分阈值:**
- score < 5 → PR Review event: `REQUEST_CHANGES`
- score >= 5 → PR Review event: `COMMENT`

### POST /api/v1/webhooks/gitlab

GitLab Webhook 端点。接收 Merge Request 事件并自动触发审查。

**Headers:**

| Header | 说明 |
|--------|------|
| X-Gitlab-Event | 事件类型 (需为 `Merge Request Hook`) |

**支持的操作:** open、update、reopen

**响应 200:**

```json
{
  "message": "GitLab MR review scheduled",
  "project_id": 123,
  "mr_iid": 5
}
```

---

## 模型路由说明

系统使用 LiteLLM 进行多模型统一调度，通过前缀路由：

| 前缀 | 模型 | 用途 |
|------|------|------|
| `glm/` | GLM-5.2 (智谱AI) | 安全审计、架构分析、重构、仲裁 |
| `deepseek/` | DeepSeek V4 | 安全审计、架构分析、性能分析、仲裁 |
| `ollama/` | Qwen2.5-7B / DeepSeek-Coder-6.7B | 风格检查、代码摘要、消息压缩 |

**推理模型** (`LLM_REASONING_MODEL`): 默认 `glm-5.2`，用于安全审计、架构分析、重构建议、仲裁汇总。

**工具模型** (`LLM_UTILITY_MODEL`): 默认 `ollama/qwen2.5:7b`，用于风格检查、代码摘要、消息压缩。
