# 代码审查工坊（Code Review Workbench）— 项目总览

> 本文档面向 Claude Code 等 AI 编程助手，介绍项目背景、技术架构、目录结构和开发约定，帮助 AI 快速理解项目全貌并高效执行开发任务。

---

## 项目简介

**代码审查工坊**是一个基于多 Agent 协作的智能代码审查平台。系统将安全审计、架构分析、性能优化、风格检查、重构建议等专业审查能力拆分为独立 Agent，通过 LangGraph 编排为并行审查流水线，最终由仲裁 Agent 汇总生成结构化审查报告。

**核心价值**：将传统人工 Code Review 中 80% 的重复性检查（风格、安全模式、常见错误）交给 AI Agent 处理，让人聚焦于 20% 的高价值判断（业务逻辑、架构决策、设计模式）。

---

## 技术栈

| 层级 | 技术选型 | 说明 |
|------|----------|------|
| **Agent 编排** | LangGraph | 图结构状态机，支持并行节点、条件分支、状态持久化 |
| **Web 框架** | FastAPI + Uvicorn | 高性能异步框架，SSE 流式响应 |
| **前端** | React 18 + TypeScript + Tailwind CSS + Vite | 现代化 SPA，Monaco Editor 代码展示 |
| **LLM 接入** | LiteLLM | 统一多模型调用（GLM-5.2 / DeepSeek V4 / Ollama 本地模型） |
| **模型策略** | 混合模式 | 关键推理用云端 API（GLM-5.2/DeepSeek V4），常规任务用本地模型（Qwen2.5-7B/DeepSeek-Coder-6.7B） |
| **AST 解析** | Tree-sitter + Semgrep + ast-grep | 多语言（Python/Go/TS/JS/Java）代码分析 |
| **数据库** | PostgreSQL + Redis + Milvus | 业务数据、缓存队列、向量检索 |
| **消息队列** | Celery + Redis | 异步任务分发 |
| **可观测** | OpenTelemetry + Prometheus + Grafana | 全链路追踪、指标采集 |
| **容器化** | Docker + Docker Compose | 一键部署 |
| **CI/CD** | GitHub Actions | 自动测试、lint、构建 |

---

## 核心模块

### 1. Agent 集群（7 个 Agent）

| Agent | 职责 | 模型策略 |
|-------|------|----------|
| Orchestrator | 任务拆分与调度 | 本地 Qwen2.5-7B |
| Security Auditor | 安全漏洞检测（SQL注入/XSS/硬编码密钥等） | 云端 GLM-5.2（推理） |
| Architecture Analyzer | 模块依赖分析、循环依赖检测 | 云端 DeepSeek V4（推理） |
| Performance Profiler | 圈复杂度、算法复杂度、性能热点 | 本地 DeepSeek-Coder-6.7B |
| Style Checker | 命名规范、注释质量、函数长度 | 本地 Qwen2.5-7B |
| Refactor Advisor | 代码坏味道识别、重构方案生成 | 云端 GLM-5.2（推理） |
| Arbitrator | 结果汇总、去重、冲突消解、报告生成 | 云端 DeepSeek V4（推理） |

### 2. Skill 系统

可插拔的专业能力模块，每个 Skill 封装一种代码分析能力。Agent 运行时按需加载 Skill，支持热插拔。内置 10 个 Skill：

- `ast_scan` — AST 结构化扫描
- `semgrep_scan` — Semgrep 模式匹配
- `cve_check` — CVE 漏洞扫描
- `dep_analyze` — 依赖关系分析
- `complexity_check` — 圈复杂度计算
- `sql_injection_detect` — SQL 注入检测
- `secret_leak_detect` — 密钥泄露检测
- `style_check` — 代码风格检查
- `refactor_suggest` — 重构建议
- `diff_context` — Git Diff 上下文增强

### 3. 记忆系统（四层）

| 记忆层 | 存储后端 | 生命周期 |
|--------|----------|----------|
| 工作记忆 | Redis | 单次审查任务 |
| 情节记忆 | PostgreSQL | 跨会话，保留最近 100 条 |
| 语义记忆 | Milvus 向量 + PostgreSQL | 长期，主动维护 |
| 程序性记忆 | PostgreSQL JSONB | 永久，随经验更新 |

### 4. 上下文压缩

- **分层摘要**：代码块 → 文件 → 模块 → 项目，逐层压缩（5x-10x）
- **滑动窗口**：保留最近消息 + 关键消息，中间层用摘要替代（3x-5x）
- **语义分块**：基于 AST 的函数/类边界分块，仅保留相关代码（2x-8x）
- **Token 配额管理**：本地模型 4K，云端模型 64K，用量超 70% 触发压缩

---

## 模型路由策略

### 可用模型

| 模型 | 来源 | 类型 | 用途 | Token 上限 |
|------|------|------|------|------------|
| `glm-5.2` | 智谱AI（云端） | 推理 | 安全审计、架构分析、重构、仲裁 | 128K |
| `deepseek-v4` | DeepSeek（云端） | 推理 | 安全审计、架构分析、性能分析、仲裁 | 128K |
| `qwen2.5:7b` | Ollama（本地） | 工具 | 风格检查、代码摘要、消息压缩 | 32K |
| `deepseek-coder:6.7b` | Ollama（本地） | 工具 | 性能分析、代码补全、AST 辅助 | 16K |

### 路由规则

- **`reasoning()` 方法**：调用 `LLM_REASONING_MODEL`（默认 `glm-5.2`），用于安全审计、架构分析、重构建议、仲裁汇总
- **`utility()` 方法**：调用 `LLM_UTILITY_MODEL`（默认 `ollama/qwen2.5:7b`），用于风格检查、代码摘要、消息压缩
- **Agent 级别覆盖**：每个 Agent 可在 `AgentContext` 中指定自己的模型，优先于全局默认
- **LiteLLM 前缀映射**：`glm/` → OpenAI 兼容接口（智谱），`deepseek/` → DeepSeek 原生接口，`ollama/` → Ollama 本地接口

### 本地模型部署（Ollama）

本地模型通过 Ollama 部署，需要拉取以下模型：

```bash
# 拉取本地模型（只需执行一次，模型会持久化到 ollamadata 卷）
docker exec crw-ollama ollama pull qwen2.5:7b
docker exec crw-ollama ollama pull deepseek-coder:6.7b

# 验证模型已就绪
docker exec crw-ollama ollama list
```

项目启动后，`docker-compose.yml` 中的 Ollama 服务会自动启动，但模型需要手动拉取（或在 Dockerfile 中预置）。

---

## 目录结构

```
code-review-workbench/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI 入口
│   │   ├── config.py                  # 全局配置
│   │   ├── api/v1/                    # API 路由
│   │   │   ├── reviews.py             # 审查任务 CRUD
│   │   │   ├── reports.py             # 审查报告查询
│   │   │   ├── webhooks.py            # GitHub/GitLab Webhook
│   │   │   ├── skills.py              # Skill 管理 API
│   │   │   └── ws.py                  # WebSocket 实时推送
│   │   ├── core/
│   │   │   ├── orchestrator.py        # LangGraph 编排器
│   │   │   ├── state.py               # 审查状态定义
│   │   │   ├── agents/                # 7 个 Agent 实现
│   │   │   ├── skills/                # Skill 系统（registry/loader/executor/builtin）
│   │   │   ├── memory/                # 四层记忆系统
│   │   │   └── compression/           # 上下文压缩
│   │   ├── models/                    # SQLAlchemy ORM
│   │   ├── schemas/                   # Pydantic 模型
│   │   ├── services/                  # 业务服务层
│   │   ├── integrations/              # 外部集成（GitHub/LLM/AST引擎）
│   │   └── utils/                     # 工具函数
│   ├── tests/                         # 测试
│   ├── alembic/                       # 数据库迁移
│   ├── Dockerfile
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── pages/                     # Dashboard / ReviewDetail / SkillManager / Settings
│   │   ├── components/                # layout / review / charts / common
│   │   ├── hooks/                     # useReviews / useSkills / useSSE
│   │   ├── services/api.ts            # 后端 API 封装
│   │   └── types/                     # TypeScript 类型
│   ├── Dockerfile
│   └── package.json
├── docs/                              # 开发文档
│   ├── project-overview.md            # 本文档
│   ├── phase-1-scaffold.md
│   ├── phase-2-multi-agent.md
│   ├── phase-3-memory-frontend.md
│   └── phase-4-production.md
├── skills/                            # 用户自定义 Skill 目录
├── docker-compose.yml
├── docker-compose.dev.yml
├── .env.example
└── README.md
```

---

## 开发约定

### 代码风格
- Python 3.11+，使用 `ruff` 作为 linter 和 formatter
- TypeScript 使用 ESLint + Prettier
- 所有公开函数/类必须有 docstring
- Agent 相关代码使用 `async/await` 异步模式

### 数据库
- 使用 SQLAlchemy 2.0 异步 ORM（`asyncpg` 驱动）
- 迁移使用 Alembic
- 所有时间字段使用 `DateTime(timezone=True)`

### API 设计
- RESTful 风格，版本化路径 `/api/v1/`
- 请求/响应使用 Pydantic v2 模型
- 长时间运行任务使用 SSE 推送进度
- 错误响应统一格式：`{"detail": "错误描述"}`

### Agent 开发
- 所有 Agent 继承 `BaseReviewAgent`，实现 `review()` 方法
- Agent 通过 `AgentContext` 获取 LLM 和 AST 引擎实例
- 审查结果统一格式：`{agent_type, severity, file_path, line_start, line_end, category, title, description, suggestion, code_snippet}`
- 严重等级：`critical > high > medium > low > info`

### Skill 开发
- 所有 Skill 继承 `BaseSkill`，实现 `metadata` 属性和 `execute()` 方法
- 内置 Skill 放在 `backend/app/core/skills/builtin/`
- 用户自定义 Skill 放在 `skills/` 目录
- Skill 通过 `SkillRegistry` 注册，`SkillLoader` 动态加载，`SkillExecutor` 执行

### 模型调用
- 统一通过 `LLMProvider` 调用，不直接使用 LiteLLM
- 安全审计和架构分析使用 `reasoning()` 方法（云端模型 GLM-5.2/DeepSeek V4）
- 风格检查和性能分析使用 `utility()` 方法（本地模型 Qwen2.5-7B/DeepSeek-Coder-6.7B）
- `_resolve_model()` 方法映射规则：`glm/` → OpenAI 兼容接口（智谱），`deepseek/` → DeepSeek 接口，`ollama/` → Ollama 本地接口
- 所有 LLM 调用记录 Token 用量

### 前端
- 组件使用函数式组件 + Hooks
- 状态管理使用 `@tanstack/react-query`
- 代码编辑器使用 `@monaco-editor/react`
- 图表使用 Recharts
- 样式使用 Tailwind CSS

---

## 环境变量

关键环境变量参见 `.env.example`：

| 变量 | 说明 |
|------|------|
| `ZHIPU_API_KEY` | 智谱AI API 密钥（GLM-5.2） |
| `ZHIPU_BASE_URL` | 智谱AI API 地址（默认 https://open.bigmodel.cn/api/paas/v4） |
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 |
| `DEEPSEEK_BASE_URL` | DeepSeek API 地址（默认 https://api.deepseek.com/v1） |
| `OLLAMA_BASE_URL` | Ollama 地址（默认 http://localhost:11434） |
| `OLLAMA_MODELS` | 需要部署的 Ollama 模型列表（逗号分隔） |
| `LLM_REASONING_MODEL` | 推理模型（默认 glm-5.2） |
| `LLM_UTILITY_MODEL` | 工具模型（默认 ollama/qwen2.5:7b） |
| `POSTGRES_*` | PostgreSQL 连接信息 |
| `REDIS_URL` | Redis 连接 URL |
| `GITHUB_TOKEN` | GitHub Personal Access Token |
| `WEBHOOK_SECRET` | Webhook 签名密钥 |

---

## 开发流程

1. **启动基础设施**：`docker compose up -d postgres redis ollama`
2. **部署本地模型**：`docker exec crw-ollama ollama pull qwen2.5:7b && docker exec crw-ollama ollama pull deepseek-coder:6.7b`
3. **安装依赖**：`cd backend && pip install -e ".[dev]"`
4. **数据库迁移**：`alembic upgrade head`
5. **启动后端**：`uvicorn app.main:app --reload --port 8000`
6. **启动前端**：`cd frontend && npm run dev`
7. **运行测试**：`pytest tests/ -v`
8. **代码检查**：`ruff check app/`

---

## 四阶段开发路线

| 阶段 | 目标 | 文档 |
|------|------|------|
| 一 | 基础骨架搭建，单 Agent（StyleChecker）可运行，Ollama 本地模型部署 | `phase-1-scaffold.md` |
| 二 | 全部 5 Agent + 仲裁，Skill 系统，并行编排 | `phase-2-multi-agent.md` |
| 三 | 四层记忆系统，上下文压缩，前端 Web 应用 | `phase-3-memory-frontend.md` |
| 四 | CI/CD Webhook，多语言扩展，可观测性，生产加固 | `phase-4-production.md` |

每个阶段的文档包含：具体任务清单、验收标准 checklist、关键技术决策说明。**文档中不包含代码实现，AI 需根据任务描述自行编写代码。**