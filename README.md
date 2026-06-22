# Code Review Workbench — 智能代码审查与重构工坊

基于多 Agent 协作的智能代码审查平台。系统将安全审计、架构分析、性能优化、风格检查、重构建议等专业审查能力拆分为独立 Agent，通过 LangGraph 编排为并行审查流水线，最终由仲裁 Agent 汇总生成结构化审查报告。

## 核心特性

- **多 Agent 并行审查** — 5 个专业 Agent + 1 个仲裁 Agent 并行执行，覆盖安全、架构、性能、风格、重构
- **Skill 可插拔系统** — 10 个内置 Skill，支持热插拔和自定义扩展
- **四层记忆系统** — 工作记忆、情节记忆、语义记忆、程序性记忆，支持跨会话学习
- **多语言支持** — Python / Go / TypeScript / JavaScript / Java，基于 Tree-sitter AST 解析
- **GitHub/GitLab Webhook** — 自动触发 PR/MR 审查，结果回写
- **全链路可观测** — OpenTelemetry 追踪 + Prometheus 指标 + 结构化 JSON 日志
- **Docker 一键部署** — 9 个服务容器化，`docker compose up` 即可启动
- **CI/CD 集成** — GitHub Actions 自动测试、Lint、构建

## 技术架构

```
┌──────────────────────────────────────────────────────┐
│                     Frontend (React 18)               │
│          Monaco Editor | Tailwind CSS | Recharts      │
└──────────────────────┬───────────────────────────────┘
                       │ HTTP/SSE
┌──────────────────────▼───────────────────────────────┐
│                 Backend (FastAPI)                      │
│  ┌─────────────────────────────────────────────────┐  │
│  │           LangGraph Orchestrator                 │  │
│  │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌───────────┐ │  │
│  │  │Style│ │Sec  │ │Arch │ │Perf │ │Refac│ │Arb│ │ │  │
│  │  └──┬──┘ └──┬──┘ └──┬──┘ └──┬──┘ └──┬──┘ └─┬─┘ │  │
│  └─────┼───────┼───────┼───────┼────────┼───────┼──┘  │
│        │       │       │       │        │       │     │
│  ┌─────▼───────▼───────▼───────▼────────▼───────▼──┐  │
│  │              Memory System (4 layers)            │  │
│  └─────────────────────────────────────────────────┘  │
└──────────────────────┬───────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────┐
│  PostgreSQL │ Redis │ Milvus │ Ollama │ Jaeger │ ...  │
└──────────────────────────────────────────────────────┘
```

## 快速开始

### 前置条件

- Docker Desktop 已安装并运行
- Git

### 启动

```bash
# 1. 克隆仓库
git clone https://github.com/your-org/code-review-workbench.git
cd code-review-workbench

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 填入你的 API Key（ZHIPU_API_KEY 等）

# 3. 一键启动所有服务
docker compose up -d

# 4. 拉取 Ollama 本地模型（只需一次）
docker exec crw-ollama ollama pull qwen2.5:7b
docker exec crw-ollama ollama pull deepseek-coder:6.7b

# 5. 访问前端
open http://localhost
```

### 验证

```bash
# 健康检查
curl http://localhost:8000/health

# 测试 LLM 连通性
curl -X POST http://localhost:8000/api/test/llm

# 查看 Jaeger 追踪
open http://localhost:16686

# 查看 Prometheus 指标
open http://localhost:9090
```

## API 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/metrics` | Prometheus 指标 |
| POST | `/api/v1/reviews` | 提交代码审查 |
| GET | `/api/v1/reviews/{id}` | 查询审查结果 |
| GET | `/api/v1/reviews/{id}/stream` | SSE 进度推送 |
| GET | `/api/v1/skills` | 列出所有 Skill |
| POST | `/api/v1/skills/execute` | 执行指定 Skill |
| POST | `/api/v1/webhooks/github` | GitHub Webhook |
| POST | `/api/v1/webhooks/gitlab` | GitLab Webhook |

详见 [API 参考文档](docs/api-reference.md)。

## 项目结构

```
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口
│   │   ├── config.py            # 全局配置
│   │   ├── api/v1/              # API 路由
│   │   ├── core/                # Agent/编排/Skill/记忆/压缩
│   │   ├── models/              # SQLAlchemy ORM
│   │   ├── schemas/             # Pydantic 模型
│   │   ├── integrations/        # GitHub/GitLab/LLM/AST
│   │   └── utils/               # 日志/指标/追踪
│   ├── tests/                   # 测试
│   └── Dockerfile
├── frontend/
│   ├── src/                     # React 18 + TypeScript
│   └── Dockerfile
├── docs/                        # 文档
├── docker-compose.yml           # Docker 编排
├── prometheus.yml               # Prometheus 配置
└── .github/workflows/ci.yml     # CI/CD
```

## 开发指南

### 本地开发

```bash
# 1. 启动基础设施
docker compose up -d postgres redis

# 2. 安装 Python 依赖
cd backend
pip install -e ".[dev]"

# 3. 数据库迁移
alembic upgrade head

# 4. 启动后端
uvicorn app.main:app --reload --port 8000

# 5. 启动前端
cd ../frontend
npm install
npm run dev
```

### 运行测试

```bash
cd backend
pytest tests/ -v --cov=app --cov-report=term-missing
```

### 代码检查

```bash
cd backend
ruff check app/
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `ZHIPU_API_KEY` | 智谱AI API 密钥 | - |
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | - |
| `LLM_REASONING_MODEL` | 推理模型 | `glm-5.2` |
| `LLM_UTILITY_MODEL` | 工具模型 | `ollama/qwen2.5:7b` |
| `GITHUB_TOKEN` | GitHub PAT | - |
| `WEBHOOK_SECRET` | Webhook 签名密钥 | - |

完整列表见 `.env.example`。

## 文档索引

- [架构文档](docs/architecture.md)
- [API 参考](docs/api-reference.md)
- [Skill 开发指南](docs/skill-development.md)
- [项目总览](docs/project-overview.md)

## 贡献指南

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交变更 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 创建 Pull Request

请确保：
- 所有测试通过 (`pytest tests/ -v`)
- 代码通过 Lint (`ruff check app/`)
- 新功能包含测试
- 更新相关文档

## License

MIT
