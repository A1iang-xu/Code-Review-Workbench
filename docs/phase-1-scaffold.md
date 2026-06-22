# 阶段一：基础骨架搭建

> 目标：工程基础设施就绪，Ollama 本地模型部署完成，单 Agent（StyleChecker）可运行，完成首个审查流水线闭环。
> 技术栈：Python 3.11+ / FastAPI / LangGraph / PostgreSQL / Redis / LiteLLM / Tree-sitter / Ollama

---

## 前置条件

1. 项目目录骨架已创建（`e:\MiCode\code-review-workbench\`）
2. `backend/pyproject.toml`、`.env.example`、`docker-compose.yml` 已存在
3. Docker Desktop 已安装并运行
4. Python 3.11+ 已安装
5. 阅读 `docs/project-overview.md` 了解项目全貌和开发约定，特别注意**模型路由策略**和**本地模型部署**章节

**启动命令**：
```bash
docker compose up -d postgres redis ollama
cd backend && pip install -e ".[dev]"
```

---

## 任务清单

### 任务 0：Ollama 本地模型部署

> **重要**：此任务必须在 LLM 接入层开发之前完成，确保本地模型可用。

| # | 任务 | 涉及文件 |
|---|------|----------|
| 0.1 | 确认 Ollama 容器已启动：`docker ps | grep crw-ollama`，如未启动则执行 `docker compose up -d ollama` | 无（手动操作） |
| 0.2 | 拉取 Qwen2.5-7B 模型（工具模型）：`docker exec crw-ollama ollama pull qwen2.5:7b`。该模型用于风格检查、代码摘要、消息压缩等常规任务 | 无（手动操作） |
| 0.3 | 拉取 DeepSeek-Coder-6.7B 模型（辅助工具模型）：`docker exec crw-ollama ollama pull deepseek-coder:6.7b`。该模型用于性能分析、代码补全、AST 辅助分析 | 无（手动操作） |
| 0.4 | 验证模型已就绪：`docker exec crw-ollama ollama list`，确认输出包含 `qwen2.5:7b` 和 `deepseek-coder:6.7b` | 无（手动操作） |
| 0.5 | 测试 Ollama 连通性：`curl http://localhost:11434/api/tags`，确认返回模型列表 JSON | 无（手动操作） |

### 任务 1：项目初始化与配置管理

| # | 任务 | 涉及文件 |
|---|------|----------|
| 1.1 | 创建 `backend/app/__init__.py`，写入项目 docstring | `app/__init__.py` |
| 1.2 | 创建 `backend/app/config.py`，使用 `pydantic-settings` 定义全局配置类 `Settings`，从环境变量和 `.env` 加载。**关键配置项**：`ZHIPU_API_KEY`、`ZHIPU_BASE_URL`、`DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`OLLAMA_BASE_URL`、`OLLAMA_MODELS`、`LLM_REASONING_MODEL`（默认 `glm-5.2`）、`LLM_UTILITY_MODEL`（默认 `ollama/qwen2.5:7b`）、数据库连接串（asyncpg + psycopg2 双 URL）、Redis URL、审查参数 | `app/config.py` |
| 1.3 | 创建 `backend/app/models/__init__.py`，使用 SQLAlchemy 2.0 异步引擎创建 `async_session_factory` 和 `get_db()` 依赖注入函数 | `app/models/__init__.py` |
| 1.4 | 创建 `backend/app/main.py`，搭建 FastAPI 应用骨架：lifespan 管理、CORS 中间件、`GET /health` 健康检查端点 | `app/main.py` |

### 任务 2：数据库模型定义与迁移

| # | 任务 | 涉及文件 |
|---|------|----------|
| 2.1 | 创建 `ReviewTask` 模型：id（UUID）、repo_url、branch、commit_sha、status（pending/running/completed/failed）、file_paths（JSONB）、config（JSONB）、created_at、updated_at | `app/models/review.py` |
| 2.2 | 创建 `AgentResult` 模型：id（UUID）、task_id（FK）、agent_type、severity、file_path、line_start、line_end、category、title、description、suggestion、code_snippet、metadata（JSONB）、created_at | `app/models/agent_result.py` |
| 2.3 | 创建 `ReviewReport` 模型：id（UUID）、task_id（FK，unique）、summary、score（Float）、stats（JSONB）、full_report_html、full_report_md、created_at | `app/models/report.py` |
| 2.4 | 在 `app/models/__init__.py` 中导入所有模型，确保 `Base.metadata` 完整 | `app/models/__init__.py` |
| 2.5 | 配置 `alembic/env.py`，连接 `DATABASE_URL_SYNC`，设置 `target_metadata = Base.metadata` | `alembic/env.py` |
| 2.6 | 执行 `alembic revision --autogenerate` 和 `alembic upgrade head` 创建表 | `alembic/versions/` |

### 任务 3：LLM 统一接入层

| # | 任务 | 涉及文件 |
|---|------|----------|
| 3.1 | 创建 `LLMProvider` 类，封装 LiteLLM。实现 `_resolve_model()` 方法：`glm/` 前缀 → 使用 ZHIPU_BASE_URL + ZHIPU_API_KEY（OpenAI 兼容接口），`deepseek/` 前缀 → 使用 DEEPSEEK_BASE_URL + DEEPSEEK_API_KEY，`ollama/` 前缀 → 使用 OLLAMA_BASE_URL（无需 API Key）。不包含以上前缀的模型名默认按 `ollama/` 处理 | `app/integrations/llm.py` |
| 3.2 | 实现 `chat()` 类方法：支持 `model`、`temperature`、`max_tokens`、`stream` 参数，调用 `litellm.acompletion`。根据 `_resolve_model()` 的结果设置对应的 `api_base` 和 `api_key` | `app/integrations/llm.py` |
| 3.3 | 实现 `reasoning()` 快捷方法：使用 `LLM_REASONING_MODEL`（默认 `glm-5.2`，走智谱 API），`temperature=0.1`，`max_tokens=4096` | `app/integrations/llm.py` |
| 3.4 | 实现 `utility()` 快捷方法：使用 `LLM_UTILITY_MODEL`（默认 `ollama/qwen2.5:7b`，走本地 Ollama），`temperature=0.3`，`max_tokens=2048` | `app/integrations/llm.py` |
| 3.5 | 在 `main.py` 中添加 `POST /api/test/llm` 测试端点，分别测试 reasoning 模型（GLM-5.2）和 utility 模型（Qwen2.5-7B）的连通性 | `app/main.py` |

### 任务 4：AST 解析引擎集成

| # | 任务 | 涉及文件 |
|---|------|----------|
| 4.1 | 创建 `CodeIssue` dataclass：file_path、line_start、line_end、severity、category、title、description、suggestion、code_snippet | `app/integrations/ast_engine.py` |
| 4.2 | 创建 `ParsedFile` dataclass：path、content、language、tree（Node）、issues（list） | `app/integrations/ast_engine.py` |
| 4.3 | 创建 `ASTEngine` 类：维护 `_parsers` 字典缓存，`SUPPORTED_LANGUAGES` 字典（当前仅 Python），`_get_parser()` 工厂方法 | `app/integrations/ast_engine.py` |
| 4.4 | 实现 `parse(code, file_path, language)` 方法：返回 `ParsedFile` | `app/integrations/ast_engine.py` |
| 4.5 | 实现 `detect_language(file_path)` 方法：根据扩展名推断语言（.py→python, .go→go, .ts/.tsx→typescript, .js/.jsx→javascript, .java→java） | `app/integrations/ast_engine.py` |
| 4.6 | 编写脚本验证 AST 引擎能正确解析 Python 代码 | 手动验证 |

### 任务 5：LangGraph 工作流核心

| # | 任务 | 涉及文件 |
|---|------|----------|
| 5.1 | 定义 `ReviewState` TypedDict：task_id、repo_url、branch、files（Annotated list）、current_stage、progress、5 个 Agent 结果列表（均用 Annotated + operator.add）、report_summary、report_score、report_html、errors、started_at、completed_at | `app/core/state.py` |
| 5.2 | 创建 `AgentContext` dataclass：llm（LLMProvider）、ast_engine（ASTEngine）、config（dict） | `app/core/agents/base.py` |
| 5.3 | 创建 `BaseReviewAgent` 抽象基类：定义 `agent_type` 属性、`display_name` 属性、`review(parsed_files)` 抽象方法、`_llm_analyze(prompt, code_context, use_reasoning)` 辅助方法。`use_reasoning=True` 时调用 `LLMProvider.reasoning()`（GLM-5.2），`use_reasoning=False` 时调用 `LLMProvider.utility()`（本地 Qwen2.5-7B） | `app/core/agents/base.py` |
| 5.4 | 实现 `StyleCheckerAgent`：`agent_type="style"`，`display_name="风格检查Agent"`。`review()` 方法分两步：先用 AST 检查函数长度（>50 行告警），再用 LLM（`use_reasoning=False`，走本地 Qwen2.5-7B）检查命名规范、注释质量、代码重复、导入顺序。LLM 提示词要求返回 JSON 数组 | `app/core/agents/style.py` |
| 5.5 | 实现 `_walk()` 和 `_get_func_name()` 辅助方法在 StyleChecker 中 | `app/core/agents/style.py` |
| 5.6 | 创建 `build_review_graph()` 函数：构建 LangGraph StateGraph，3 个节点（parse_code → style_review → generate_report），线性流程 | `app/core/orchestrator.py` |
| 5.7 | 实现 `parse_code_node`：遍历 state.files，用 ASTEngine 解析每个文件 | `app/core/orchestrator.py` |
| 5.8 | 实现 `style_review_node`：创建 AgentContext 和 StyleCheckerAgent，执行 review，返回 `style_results` | `app/core/orchestrator.py` |
| 5.9 | 实现 `generate_report_node`：统计 severity_counts，计算评分公式（扣分制），生成 summary 文本 | `app/core/orchestrator.py` |

### 任务 6：审查 API 端点

| # | 任务 | 涉及文件 |
|---|------|----------|
| 6.1 | 创建 `CodeFile` Pydantic 模型（path + content）和 `ReviewRequest`（files + repo_url + branch） | `app/api/v1/reviews.py` |
| 6.2 | 实现 `POST /api/v1/reviews`：接收 ReviewRequest，构建 ReviewState，调用 `review_graph.ainvoke()`，返回 task_id 和 status | `app/api/v1/reviews.py` |
| 6.3 | 实现 `GET /api/v1/reviews/{task_id}`（阶段一暂返回占位信息） | `app/api/v1/reviews.py` |
| 6.4 | 在 `main.py` 中注册 reviews 路由 | `app/main.py` |

### 任务 7：验收测试

| # | 任务 | 涉及文件 |
|---|------|----------|
| 7.1 | 编写手动测试脚本：使用 httpx 调用 `/health` 和 `POST /api/v1/reviews`，传入包含长函数和过多参数的 Python 测试代码，验证返回结果 | `tests/test_phase1_manual.py` |
| 7.2 | 启动后端服务，运行验收测试，确认所有断言通过 | 手动执行 |

---

## 验收标准

### Ollama 本地模型
- [ ] Ollama 容器正常运行（`docker ps | grep ollama` 有输出）
- [ ] `qwen2.5:7b` 模型已拉取并可用（`ollama list` 包含该模型）
- [ ] `deepseek-coder:6.7b` 模型已拉取并可用（`ollama list` 包含该模型）
- [ ] `curl http://localhost:11434/api/tags` 返回模型列表

### API 与 LLM
- [ ] `GET /health` 返回 `{"status": "ok", "app": "code-review-workbench", "env": "development"}`
- [ ] `POST /api/test/llm` 能成功调用 GLM-5.2（reasoning）并返回响应
- [ ] `POST /api/test/llm` 能成功调用 Qwen2.5-7B（utility）并返回响应
- [ ] `_resolve_model()` 正确映射：`glm-5.2` → 智谱 API，`ollama/qwen2.5:7b` → Ollama，`deepseek-v4` → DeepSeek API

### AST 与工作流
- [ ] Tree-sitter 能正确解析 Python 代码生成 AST（验证 root_node.type 为 "module"）
- [ ] `POST /api/v1/reviews` 接收代码文件并返回 `{"task_id": "...", "status": "completed"}`
- [ ] StyleChecker Agent 能通过 AST 检测到函数超过 50 行的问题
- [ ] StyleChecker Agent 能通过 LLM（本地 Qwen2.5-7B）检测到命名规范、注释质量等问题
- [ ] LangGraph 工作流完整执行：parse_code → style_review → generate_report

### 数据库
- [ ] 报告生成节点正确统计各严重等级的问题数量并计算评分
- [ ] 数据库表 `review_tasks`、`agent_results`、`review_reports` 已创建
- [ ] `alembic` 迁移可正常执行

---

## 技术决策说明

- **配置管理选用 pydantic-settings**：支持 `.env` 文件和环境变量，类型安全，与 FastAPI 生态一致
- **数据库使用异步驱动 asyncpg**：与 FastAPI 异步模型匹配，避免阻塞事件循环
- **LLM 接入使用 LiteLLM**：统一 API 调用接口，支持 GLM（OpenAI 兼容）、DeepSeek、Ollama 三种后端，通过 `_resolve_model()` 前缀路由
- **模型策略：GLM-5.2 做推理 + Qwen2.5-7B 做工具**：GLM-5.2 推理能力强且价格合理，用于安全审计、架构分析等深度推理；Qwen2.5-7B 本地运行零成本，用于风格检查、代码摘要等高频轻量任务
- **DeepSeek V4 作为推理备选**：在 GLM 不可用或需要对比时，可切换到 DeepSeek V4
- **Ollama 本地模型部署**：Qwen2.5-7B 和 DeepSeek-Coder-6.7B 通过 Ollama 在本地运行，数据不出本机，适合处理敏感代码
- **AST 引擎第一阶段仅支持 Python**：先验证架构可行性，后续阶段扩展多语言
- **LangGraph 工作流先线性后并行**：阶段一用线性流程验证基本链路，阶段二再引入并行执行