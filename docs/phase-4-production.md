# 阶段四：CI/CD集成 + 多语言扩展 + 生产加固

> 目标：GitHub/GitLab Webhook 集成、多语言支持（Go/TypeScript/Java）、全链路可观测、测试覆盖与文档完善。
> 前置条件：阶段三验收通过（记忆系统 + 前端完整可用）

---

## 前置条件

1. 阶段三全部验收标准通过
2. 安装多语言 Tree-sitter 解析器：`pip install tree-sitter-go tree-sitter-typescript tree-sitter-java`
3. 安装可观测性依赖：`pip install opentelemetry-api opentelemetry-sdk opentelemetry-instrumentation-fastapi opentelemetry-exporter-otlp prometheus-client`
4. 安装测试依赖：`pip install pytest pytest-asyncio pytest-cov httpx`
5. Docker Desktop 已安装并运行
6. GitHub 账号，已创建 Personal Access Token（权限：repo, pull_requests）
7. GitLab 账号（可选），已创建 Personal Access Token（权限：api）

---

## 任务清单

### 任务 1：GitHub Webhook 集成

| # | 任务 | 涉及文件 |
|---|------|----------|
| 1.1 | 创建 `GitHubIntegration` 类：初始化 GitHub API 客户端（base_url + token + headers），封装 `verify_signature()` 静态方法（HMAC-SHA256 签名验证） | `app/integrations/github.py` |
| 1.2 | 实现 `get_pr_files(owner, repo, pr_number)` 方法：调用 GitHub API `GET /repos/{owner}/{repo}/pulls/{pr_number}/files` 获取 PR 变更文件列表 | `app/integrations/github.py` |
| 1.3 | 实现 `get_file_content(owner, repo, path, ref)` 方法：调用 GitHub API `GET /repos/{owner}/{repo}/contents/{path}?ref={ref}`，Base64 解码返回文件内容 | `app/integrations/github.py` |
| 1.4 | 实现 `create_review_comment(owner, repo, pr_number, commit_id, body, path, line)` 方法：在 PR 特定行创建行内审查评论 | `app/integrations/github.py` |
| 1.5 | 实现 `create_pr_review(owner, repo, pr_number, commit_id, body, event)` 方法：创建 PR 审查汇总评论，event 支持 COMMENT / APPROVE / REQUEST_CHANGES | `app/integrations/github.py` |
| 1.6 | 实现 `set_commit_status(owner, repo, sha, state, description, target_url)` 方法：设置 Commit 状态（pending / success / failure / error），context 为 "code-review-workbench" | `app/integrations/github.py` |
| 1.7 | 创建 `POST /api/v1/webhooks/github` 端点：验证签名 → 过滤事件类型（仅处理 pull_request 的 opened/synchronize/reopened）→ 提取 PR 信息 → 通过 BackgroundTasks 异步触发审查 | `app/api/v1/webhooks.py` |
| 1.8 | 实现 `run_pr_review()` 后台任务：设置 Commit 状态为 pending → 获取 PR 变更文件 → 过滤代码文件（排除 .md/.json/.yaml 等）→ 构建 ReviewState → 调用 `review_graph.ainvoke()` → 生成 PR Review 评论（含评分和统计表格）→ 对 critical/high 问题添加行内评论（最多 5 条）→ 设置最终 Commit 状态 | `app/api/v1/webhooks.py` |
| 1.9 | 在 `main.py` 中注册 webhooks 路由 | `app/main.py` |
| 1.10 | 在 `.env` 中添加 `GITHUB_TOKEN` 和 `WEBHOOK_SECRET` 配置项 | `.env`、`.env.example` |

### 任务 2：GitLab Webhook 集成

| # | 任务 | 涉及文件 |
|---|------|----------|
| 2.1 | 创建 `GitLabIntegration` 类：初始化 GitLab API 客户端（base_url + PRIVATE-TOKEN header） | `app/integrations/gitlab.py` |
| 2.2 | 实现 `get_merge_request_changes(project_id, mr_iid)` 方法：调用 GitLab API `GET /projects/{project_id}/merge_requests/{mr_iid}/changes` | `app/integrations/gitlab.py` |
| 2.3 | 实现 `create_mr_note(project_id, mr_iid, body)` 方法：在 MR 下创建评论 | `app/integrations/gitlab.py` |
| 2.4 | 创建 `POST /api/v1/webhooks/gitlab` 端点：处理 Merge Request Hook 事件，触发自动审查 | `app/api/v1/webhooks.py` |
| 2.5 | 在 `.env` 中添加 `GITLAB_TOKEN` 配置项 | `.env`、`.env.example` |

### 任务 3：多语言 Tree-sitter 扩展

| # | 任务 | 涉及文件 |
|---|------|----------|
| 3.1 | 更新 `ASTEngine.SUPPORTED_LANGUAGES` 字典：添加 Go（`tree_sitter_go.language`）、TypeScript、JavaScript、Java 的语言映射 | `app/integrations/ast_engine.py` |
| 3.2 | 更新 `ASTEngine._get_parser()` 方法：支持按语言名获取对应的 Tree-sitter Parser 实例 | `app/integrations/ast_engine.py` |
| 3.3 | 更新 `ASTEngine.parse()` 方法：根据检测到的语言使用对应的解析器 | `app/integrations/ast_engine.py` |
| 3.4 | 在 `AgentContext` 中添加 `language` 字段（默认 "python"），用于 Agent 感知当前审查语言 | `app/core/agents/base.py` |
| 3.5 | 创建 `LANGUAGE_STYLE_RULES` 配置字典：Python（PEP 8, max_func_lines=50, linter=ruff）、Go（Effective Go, max_func_lines=80, linter=golangci-lint）、TypeScript（ESLint recommended, max_func_lines=60）、JavaScript（Airbnb, max_func_lines=50）、Java（Google Java Style, max_func_lines=60） | `app/core/agents/style.py` |
| 3.6 | 更新 `StyleCheckerAgent`：根据 `context.language` 动态选择对应的代码风格规则和提示词 | `app/core/agents/style.py` |
| 3.7 | 更新 `ReviewRequest` Pydantic 模型：添加 `language` 字段（默认 "auto"，支持 auto / python / go / typescript / javascript / java） | `app/api/v1/reviews.py` |
| 3.8 | 更新 `parse_code_node`：根据 ReviewRequest 的 language 参数或自动检测结果设置每个文件的解析语言 | `app/core/orchestrator.py` |

### 任务 4：OpenTelemetry 链路追踪

| # | 任务 | 涉及文件 |
|---|------|----------|
| 4.1 | 创建 `setup_telemetry(app, service_name)` 函数：创建 TracerProvider（Resource 含 service_name），配置 OTLP gRPC Exporter（endpoint: localhost:4317），添加 BatchSpanProcessor，设置全局 TracerProvider | `app/utils/telemetry.py` |
| 4.2 | 调用 `FastAPIInstrumentor.instrument_app(app)` 自动注入 FastAPI 请求追踪 | `app/utils/telemetry.py` |
| 4.3 | 调用 `HTTPXClientInstrumentor().instrument()` 自动注入 HTTPX 外部调用追踪 | `app/utils/telemetry.py` |
| 4.4 | 创建 `trace_agent(agent_type)` 装饰器：创建自定义 Span（名称 `agent.{agent_type}`），记录 agent_type 属性和 findings_count | `app/utils/telemetry.py` |
| 4.5 | 在 `main.py` 的 lifespan 中调用 `setup_telemetry(app)` | `app/main.py` |
| 4.6 | 在 `docker-compose.yml` 中添加 Jaeger 服务（image: jaegertracing/all-in-one），暴露 16686（UI）和 4317（OTLP gRPC）端口 | `docker-compose.yml` |

### 任务 5：Prometheus 指标采集

| # | 任务 | 涉及文件 |
|---|------|----------|
| 5.1 | 创建 Prometheus 指标定义：`crw_review_total`（Counter，按 status 标签）、`crw_review_duration_seconds`（Histogram，分桶 1/5/10/30/60/120/300s）、`crw_agent_call_total`（Counter，按 agent_type 和 status 标签）、`crw_agent_call_duration_seconds`（Histogram，按 agent_type 标签）、`crw_token_usage_total`（Counter，按 model 和 tier 标签）、`crw_active_reviews`（Gauge） | `app/utils/metrics.py` |
| 5.2 | 创建 `metrics_endpoint()` 函数：使用 `generate_latest(REGISTRY)` 生成 Prometheus 格式指标文本 | `app/utils/metrics.py` |
| 5.3 | 在 `main.py` 中添加 `GET /metrics` 端点 | `app/main.py` |
| 5.4 | 在 Agent 审查节点中，使用 `review_duration` 和 `agent_call_duration` 记录执行时间 | `app/core/orchestrator.py` |
| 5.5 | 在 LLM 调用中，记录 `token_usage_total` 指标 | `app/integrations/llm.py` |
| 5.6 | 在 `docker-compose.yml` 中添加 Prometheus 服务（image: prom/prometheus），挂载 `prometheus.yml` 配置文件，暴露 9090 端口 | `docker-compose.yml` |
| 5.7 | 创建 `prometheus.yml` 配置文件：定义 scrape_configs 抓取 backend:8000 的 /metrics 端点 | `prometheus.yml` |

### 任务 6：结构化日志

| # | 任务 | 涉及文件 |
|---|------|----------|
| 6.1 | 创建 `StructuredFormatter` 类：继承 `logging.Formatter`，输出 JSON 格式日志（timestamp、level、logger、message、module、function、line），支持额外字段（task_id、agent_type、skill_name、duration_ms、tokens_used） | `app/utils/logger.py` |
| 6.2 | 创建 `setup_logging(level)` 函数：配置 StreamHandler + StructuredFormatter，设置第三方库日志级别（httpx → WARNING, httpcore → WARNING） | `app/utils/logger.py` |
| 6.3 | 在 `main.py` 启动时调用 `setup_logging()` | `app/main.py` |
| 6.4 | 在关键节点添加结构化日志：审查开始/结束、Agent 调用开始/结束、LLM 调用、Skill 执行、错误异常 | 各 Agent 文件和 orchestrator |

### 任务 7：测试覆盖

| # | 任务 | 涉及文件 |
|---|------|----------|
| 7.1 | 创建 `tests/conftest.py`：定义 `client` fixture（httpx AsyncClient + ASGITransport）、`sample_python_code` fixture（包含硬编码密钥、SQL 注入、三层嵌套循环的测试代码）、`sample_files` fixture | `tests/conftest.py` |
| 7.2 | 创建 `tests/test_agents/test_security.py`：`test_security_agent_detects_hardcoded_key`（验证检测到 `API_KEY = "sk-..."`）、`test_security_agent_detects_sql_injection`（验证检测到字符串拼接 SQL） | `tests/test_agents/test_security.py` |
| 7.3 | 创建 `tests/test_agents/test_style.py`：`test_style_agent_detects_long_function`（验证检测到超过 50 行的函数） | `tests/test_agents/test_style.py` |
| 7.4 | 创建 `tests/test_agents/test_performance.py`：`test_cyclomatic_complexity_calculation`（验证圈复杂度计算正确） | `tests/test_agents/test_performance.py` |
| 7.5 | 创建 `tests/test_skills/test_ast_scan.py`：`test_ast_scan_skill`（验证 ASTScanSkill 正确统计函数和类数量） | `tests/test_skills/test_ast_scan.py` |
| 7.6 | 创建 `tests/test_api/test_health.py`：`test_health_check`（验证 /health 返回 200 和 status=ok） | `tests/test_api/test_health.py` |
| 7.7 | 创建 `tests/test_api/test_reviews.py`：`test_create_review`（验证 POST /api/v1/reviews 返回 task_id、score、stats） | `tests/test_api/test_reviews.py` |
| 7.8 | 创建 `tests/test_api/test_skills.py`：`test_list_skills`（验证 GET /api/v1/skills 返回 Skill 列表） | `tests/test_api/test_skills.py` |
| 7.9 | 创建 `tests/test_memory/test_episodic.py`：`test_episodic_memory_saves_and_retrieves`（使用 TemporaryDirectory 验证保存和检索） | `tests/test_memory/test_episodic.py` |
| 7.10 | 创建 `tests/test_memory/test_working.py`：`test_working_memory_token_limit`（验证 token 超限时自动丢弃旧消息） | `tests/test_memory/test_working.py` |
| 7.11 | 创建 `tests/test_compression/test_chunker.py`：`test_semantic_chunker_by_function`（验证按函数边界分块正确） | `tests/test_compression/test_chunker.py` |
| 7.12 | 配置 pytest：在 `pyproject.toml` 中添加 `[tool.pytest.ini_options]`，设置 `asyncio_mode = "auto"`、`testpaths = ["tests"]` | `backend/pyproject.toml` |

### 任务 8：Docker 生产部署

| # | 任务 | 涉及文件 |
|---|------|----------|
| 8.1 | 创建 `backend/Dockerfile`：基于 `python:3.12-slim`，安装 git 和 build-essential，复制 pyproject.toml 并安装依赖，复制应用代码，EXPOSE 8000，CMD 启动 uvicorn | `backend/Dockerfile` |
| 8.2 | 创建 `frontend/Dockerfile`：多阶段构建，第一阶段 `node:20-alpine` 执行 `npm ci && npm run build`，第二阶段 `nginx:alpine` 复制 dist 和 nginx.conf | `frontend/Dockerfile` |
| 8.3 | 创建 `frontend/nginx.conf`：SPA 路由支持（`try_files $uri /index.html`），API 代理到 `backend:8000`（含 proxy_read_timeout 120s） | `frontend/nginx.conf` |
| 8.4 | 更新 `docker-compose.yml`：添加 backend 服务（build: ./backend, depends_on: postgres/redis/milvus, environment 从 .env 加载）、frontend 服务（build: ./frontend, depends_on: backend, ports: 80:80）、Ollama 服务（image: ollama/ollama, volumes 挂载模型） | `docker-compose.yml` |
| 8.5 | 验证 `docker compose up` 能一键启动所有 9 个服务（backend、frontend、postgres、redis、milvus、etcd、minio、ollama、jaeger） | 手动验证 |

### 任务 9：GitHub Actions CI/CD

| # | 任务 | 涉及文件 |
|---|------|----------|
| 9.1 | 创建 `.github/workflows/ci.yml`：定义 test 和 build 两个 job | `.github/workflows/ci.yml` |
| 9.2 | test job：ubuntu-latest runner，启动 postgres（pgvector/pgvector:pg16）和 redis（redis:7-alpine）服务容器，Setup Python 3.12，安装依赖，运行 `pytest tests/ -v --cov=app --cov-report=term-missing`，运行 `ruff check app/` | `.github/workflows/ci.yml` |
| 9.3 | build job：依赖 test job 通过，仅在 main 分支 push 时触发，执行 `docker build` 构建 backend 和 frontend 镜像 | `.github/workflows/ci.yml` |

### 任务 10：文档完善

| # | 任务 | 涉及文件 |
|---|------|----------|
| 10.1 | 创建 `README.md`：项目简介、核心特性、技术架构图、快速开始（docker compose up）、API 文档链接、开发指南、贡献指南 | `README.md` |
| 10.2 | 创建 `docs/architecture.md`：系统架构详图、Agent 交互流程、数据模型 ER 图、部署架构 | `docs/architecture.md` |
| 10.3 | 创建 `docs/api-reference.md`：所有 API 端点的请求/响应示例和参数说明 | `docs/api-reference.md` |
| 10.4 | 创建 `docs/skill-development.md`：Skill 开发指南（如何创建自定义 Skill、元数据定义、测试方法） | `docs/skill-development.md` |

---

## 验收标准

### CI/CD 集成
- [ ] GitHub Webhook 接收到 PR opened 事件后自动触发审查
- [ ] GitHub Webhook 接收到 PR synchronize 事件（新 commit push）后自动触发审查
- [ ] 审查结果以 PR Review 形式回写到 GitHub（含评分和统计表格）
- [ ] 评分 < 5 时 PR Review event 为 REQUEST_CHANGES，>= 5 时为 COMMENT
- [ ] critical/high 级别问题以行内评论形式回写到对应代码行（最多 5 条）
- [ ] Commit Status 正确反映审查流程：pending → 审查中 → success/failure
- [ ] Webhook 签名验证正确拒绝无效签名的请求（返回 403）
- [ ] GitLab Webhook 接收到 Merge Request 事件后自动触发审查（如已配置）

### 多语言支持
- [ ] Tree-sitter 能正确解析 Go 代码（验证 root_node 类型正确）
- [ ] Tree-sitter 能正确解析 TypeScript 代码
- [ ] Tree-sitter 能正确解析 Java 代码
- [ ] StyleChecker 根据语言自动切换风格规则（Python PEP 8 / Go Effective Go / TypeScript ESLint）
- [ ] `POST /api/v1/reviews` 的 `language` 参数能正确指定审查语言
- [ ] `language="auto"` 时能根据文件扩展名自动检测语言

### 可观测性
- [ ] OpenTelemetry Span 数据正常发送到 Jaeger（访问 http://localhost:16686 可查看）
- [ ] 每个 HTTP 请求自动创建 Span（含 method、path、status_code）
- [ ] 每个 Agent 调用自动创建自定义 Span（含 agent_type 和 findings_count）
- [ ] `GET /metrics` 端点返回 Prometheus 格式指标文本
- [ ] Prometheus 能正常抓取 backend 的 /metrics 端点（http://localhost:9090 可查询）
- [ ] 结构化日志以 JSON 格式输出到 stdout（每行一条 JSON）
- [ ] 日志包含 timestamp、level、logger、message 等标准字段
- [ ] 审查任务日志包含 task_id 字段用于关联

### 测试
- [ ] 所有单元测试通过（`pytest tests/ -v`）
- [ ] 代码覆盖率 > 70%（`pytest --cov=app --cov-report=term-missing`）
- [ ] Security Auditor 测试：验证硬编码密钥和 SQL 注入检测
- [ ] Style Checker 测试：验证长函数检测
- [ ] ASTScanSkill 测试：验证函数/类统计
- [ ] API 健康检查测试：验证 /health 返回 200
- [ ] 记忆系统测试：验证情节记忆的保存和检索
- [ ] 工作记忆测试：验证 token 超限自动丢弃
- [ ] 语义分块测试：验证按函数边界分块

### Docker 部署
- [ ] `docker compose up` 一键启动所有服务，无报错
- [ ] 后端容器健康检查通过（/health 返回 200）
- [ ] 前端容器能正常访问（http://localhost）
- [ ] 前端 Nginx 正确代理 API 请求到后端
- [ ] 数据库迁移在容器启动时自动执行

### CI/CD
- [ ] GitHub Actions CI 在每次 push 到 main 时自动运行
- [ ] CI 包含 test 和 lint 两个步骤
- [ ] CI 失败时阻止 PR 合并（如配置了 branch protection）

### 文档
- [ ] README.md 包含完整的快速开始指南
- [ ] 架构文档清晰描述系统组件和交互流程
- [ ] API 参考文档覆盖所有端点
- [ ] Skill 开发指南包含可操作的示例

---

## 技术决策说明

- **Webhook 审查使用 BackgroundTasks 异步执行**：避免 Webhook 响应超时（GitHub 要求 10 秒内响应），审查任务在后台执行，通过 Commit Status 反馈进度
- **行内评论限制最多 5 条**：避免在 PR 中刷屏，只对 critical 和 high 级别问题添加行内评论，其余问题在汇总评论中展示
- **多语言 Tree-sitter 使用独立 Python 包**：每个语言有独立的 tree-sitter-xxx 包，按需安装，避免单一巨大依赖
- **OpenTelemetry 选择 OTLP gRPC 协议**：性能优于 HTTP，与 Jaeger/Prometheus 生态兼容，未来可无缝切换到 Grafana Tempo
- **Prometheus 指标命名遵循 `crw_` 前缀约定**：避免与系统指标冲突，便于在 Grafana 中筛选
- **结构化日志选择 JSON 格式**：便于 ELK/Loki 等日志系统采集和索引，生产环境可配置日志级别和输出目标
- **Docker 多阶段构建减小镜像体积**：前端构建阶段使用 node:20-alpine，运行阶段仅保留 nginx + dist，最终镜像 < 50MB
- **GitHub Actions 使用 Service Containers**：直接在 CI 环境中启动 PostgreSQL 和 Redis，无需 mock，测试更真实