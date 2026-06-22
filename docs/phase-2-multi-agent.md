# 阶段二：多Agent协作 + Skill系统

> 目标：实现全部 5 个专业 Agent + 仲裁 Agent，构建可插拔 Skill 系统，完成 LangGraph 并行审查 + 汇总仲裁的完整流水线。
> 前置条件：阶段一验收通过（StyleChecker 可运行，数据库表就绪，LLM 联通）

---

## 前置条件

1. 阶段一全部验收标准通过
2. `backend/pyproject.toml` 已包含 `networkx` 依赖（`pip install networkx`）
3. 可选：安装 `semgrep`（`pip install semgrep`）用于 SemgrepScanSkill
4. 数据库表 `review_tasks`、`agent_results`、`review_reports` 已存在

---

## 任务清单

### 任务 1：实现 Security Auditor Agent（安全审计）

| # | 任务 | 涉及文件 |
|---|------|----------|
| 1.1 | 创建 `SecurityAuditorAgent` 类，继承 `BaseReviewAgent`，`agent_type="security"`，`display_name="安全审计Agent"` | `app/core/agents/security.py` |
| 1.2 | 定义 `SECURITY_PROMPT` 系统提示词，覆盖 8 类安全漏洞：SQL 注入、XSS、路径遍历、硬编码密钥、不安全反序列化、命令注入、SSRF、权限缺失 | `app/core/agents/security.py` |
| 1.3 | 定义 `HIGH_RISK_PATTERNS` 正则模式字典，覆盖硬编码密钥、命令注入、不安全反序列化、SQL 注入四类高危模式 | `app/core/agents/security.py` |
| 1.4 | 实现 `_pattern_scan()` 方法：基于正则快速扫描，排除注释行和环境变量读取等误报场景 | `app/core/agents/security.py` |
| 1.5 | 实现 `_llm_scan()` 方法：使用推理模型（`use_reasoning=True`）进行深度安全分析，解析 JSON 返回结果 | `app/core/agents/security.py` |
| 1.6 | 实现 `review()` 方法：先正则扫描再 LLM 深度推理，合并两次结果 | `app/core/agents/security.py` |

### 任务 2：实现 Architecture Analyzer Agent（架构分析）

| # | 任务 | 涉及文件 |
|---|------|----------|
| 2.1 | 创建 `ArchitectureAnalyzerAgent` 类，`agent_type="architecture"`，`display_name="架构分析Agent"` | `app/core/agents/architecture.py` |
| 2.2 | 定义 `ARCHITECTURE_PROMPT` 系统提示词，覆盖 6 个维度：模块划分、依赖方向、接口设计、设计模式、耦合度、内聚性 | `app/core/agents/architecture.py` |
| 2.3 | 实现 `_build_dependency_graph()` 方法：使用 `networkx.DiGraph`，通过 Tree-sitter 遍历所有文件的 import 语句构建模块依赖图 | `app/core/agents/architecture.py` |
| 2.4 | 实现 `_analyze_graph()` 方法：检测循环依赖（`nx.simple_cycles`）和高耦合节点（入度 > 5） | `app/core/agents/architecture.py` |
| 2.5 | 实现 `_llm_analyze_architecture()` 方法：使用推理模型进行架构评估 | `app/core/agents/architecture.py` |
| 2.6 | 实现 `review()` 方法：先构建依赖图分析，再 LLM 架构评估 | `app/core/agents/architecture.py` |

### 任务 3：实现 Performance Profiler Agent（性能分析）

| # | 任务 | 涉及文件 |
|---|------|----------|
| 3.1 | 创建 `PerformanceProfilerAgent` 类，`agent_type="performance"`，`display_name="性能优化Agent"` | `app/core/agents/performance.py` |
| 3.2 | 定义 `PERFORMANCE_PROMPT` 系统提示词，覆盖 7 类性能问题：循环嵌套、重复计算、内存分配、N+1 查询、I/O 阻塞、字符串拼接、列表推导式滥用 | `app/core/agents/performance.py` |
| 3.3 | 实现 `_calculate_cyclomatic_complexity()` 方法：通过 Tree-sitter 遍历函数体，统计所有分支节点（if/for/while/except/match/and/or/not/conditional_expression），公式为 `1 + 分支节点数` | `app/core/agents/performance.py` |
| 3.4 | 实现 `_complexity_check()` 方法：对所有函数计算圈复杂度，按阈值分级（>20 高危，>10 中危，>5 低危） | `app/core/agents/performance.py` |
| 3.5 | 实现 `_llm_perf_analysis()` 方法：使用通用模型（非推理）进行性能分析 | `app/core/agents/performance.py` |
| 3.6 | 实现 `review()` 方法：先 AST 复杂度分析，再 LLM 性能分析 | `app/core/agents/performance.py` |

### 任务 4：实现 Refactor Advisor Agent（重构建议）

| # | 任务 | 涉及文件 |
|---|------|----------|
| 4.1 | 创建 `RefactorAdvisorAgent` 类，`agent_type="refactor"`，`display_name="重构建议Agent"` | `app/core/agents/refactor.py` |
| 4.2 | 定义 `REFACTOR_PROMPT` 系统提示词，覆盖 10 种代码坏味道：长函数、过多参数、重复代码、上帝类、数据泥团、特性依恋、Switch 语句、发散式变化、霰弹式修改、注释过多 | `app/core/agents/refactor.py` |
| 4.3 | 实现 `_ast_smell_detection()` 方法：通过 Tree-sitter 检测过多参数（>5 个）的函数 | `app/core/agents/refactor.py` |
| 4.4 | 实现 `_llm_refactor_advice()` 方法：使用推理模型生成重构方案，提示词要求返回含代码示例的修复建议 | `app/core/agents/refactor.py` |
| 4.5 | 实现 `review()` 方法：先 AST 坏味道检测，再 LLM 深度重构建议 | `app/core/agents/refactor.py` |

### 任务 5：实现 Arbitrator Agent（仲裁与报告生成）

| # | 任务 | 涉及文件 |
|---|------|----------|
| 5.1 | 创建 `ArbitratorAgent` 类，`agent_type="arbitrator"`，`display_name="仲裁Agent"` | `app/core/agents/arbitrator.py` |
| 5.2 | 定义 `ARBITRATOR_PROMPT` 系统提示词，指导 LLM 执行去重、冲突消解、严重等级排序、综合摘要生成、评分 | `app/core/agents/arbitrator.py` |
| 5.3 | 实现 `arbitrate()` 方法：合并所有 Agent 结果 → 去重（file_path + line_start + category 为 Key）→ 按严重等级排序（critical > high > medium > low > info）→ 统计各维度数据 → 计算评分（扣分制：critical -2.0, high -1.0, medium -0.3, low -0.1，乘以系数 0.5）→ LLM 生成综合摘要 | `app/core/agents/arbitrator.py` |
| 5.4 | 实现 `_generate_summary()` 方法：将 Top 20 问题和统计信息传给 LLM 生成 3-5 句中文摘要 | `app/core/agents/arbitrator.py` |
| 5.5 | 实现 `generate_html_report()` 方法：生成包含评分、统计、问题详情（含颜色标记、代码片段）的 HTML 审查报告 | `app/core/agents/arbitrator.py` |

### 任务 6：Skill 系统核心实现

| # | 任务 | 涉及文件 |
|---|------|----------|
| 6.1 | 创建 `SkillCategory` 枚举：STATIC_ANALYSIS / PATTERN_MATCH / SECURITY / ARCHITECTURE / PERFORMANCE / STYLE / UTILITY | `app/core/skills/registry.py` |
| 6.2 | 创建 `SkillMetadata` dataclass：name、display_name、version、category、description、author、requires、languages、tags | `app/core/skills/registry.py` |
| 6.3 | 创建 `SkillResult` dataclass：success、findings、summary、raw_output、execution_time_ms、tokens_used | `app/core/skills/registry.py` |
| 6.4 | 创建 `BaseSkill` 抽象基类：定义 `metadata` 属性、`execute(code, file_path, context)` 抽象方法、`validate()` 和 `cleanup()` 可选钩子 | `app/core/skills/registry.py` |
| 6.5 | 实现 `SkillRegistry` 单例类：`register()` / `unregister()` / `get()` / `list_all()` / `list_by_category()` / `search()` 方法 | `app/core/skills/registry.py` |
| 6.6 | 创建 `SkillLoader` 类：`load_builtin()` 从 `builtin/` 目录加载内置 Skill，`load_custom()` 从用户指定目录加载自定义 Skill，`reload()` 热重载指定 Skill | `app/core/skills/loader.py` |
| 6.7 | 创建 `SkillExecutor` 类：`execute()` 执行单个 Skill，`execute_all()` 并行执行多个 Skill，`execute_pipeline()` 链式执行（前一个输出注入后一个上下文），`execute_by_category()` 按分类批量执行 | `app/core/skills/executor.py` |
| 6.8 | 创建 `ASTScanSkill`：基于 Tree-sitter 的 AST 结构化扫描，统计函数/类数量、嵌套深度、超长函数（>100 行） | `app/core/skills/builtin/ast_scan.py` |
| 6.9 | 创建 `SemgrepScanSkill`：调用 `semgrep --config auto --json` 命令行，解析 JSON 输出，支持超时和错误处理 | `app/core/skills/builtin/semgrep_scan.py` |
| 6.10 | 创建 `app/core/skills/__init__.py`，实现 `init_skills()` 函数：创建 SkillLoader 并调用 `load_builtin()` | `app/core/skills/__init__.py` |

### 任务 7：LangGraph 多Agent 并行编排

| # | 任务 | 涉及文件 |
|---|------|----------|
| 7.1 | 重构 `build_review_graph()` 函数：定义 8 个节点（parse_code → 5 个 Agent 节点 → arbitrate → generate_report），从 parse_code 分叉到 5 个 Agent（并行执行），5 个 Agent 汇聚到 arbitrate，最后到 generate_report | `app/core/orchestrator.py` |
| 7.2 | 实现 `_parse_files()` 辅助函数：从 ReviewState 中提取 files，用 ASTEngine 解析每个文件，返回 ParsedFile 列表 | `app/core/orchestrator.py` |
| 7.3 | 实现 5 个 Agent 节点函数：`security_review_node` / `architecture_review_node` / `performance_review_node` / `style_review_node` / `refactor_review_node`，每个节点创建对应的 Agent 实例并调用 `review()`，返回 agent_type_results 和进度更新 | `app/core/orchestrator.py` |
| 7.4 | 实现 `arbitrate_node`：收集所有 Agent 结果，调用 `ArbitratorAgent.arbitrate()`，返回 report_summary、report_score、进度更新 | `app/core/orchestrator.py` |
| 7.5 | 实现 `generate_report_node`：调用 Arbitrator 生成 HTML 报告，保存审查结果到记忆系统（MemoryManager），设置进度为 1.0 和 completed_at 时间戳 | `app/core/orchestrator.py` |

### 任务 8：更新审查 API 端点

| # | 任务 | 涉及文件 |
|---|------|----------|
| 8.1 | 更新 `POST /api/v1/reviews`：构建完整的 ReviewState（包含所有 results 字段），调用 `review_graph.ainvoke()`，返回 task_id、status、summary、score、report_html、stats（各 Agent 发现数） | `app/api/v1/reviews.py` |
| 8.2 | 实现 `GET /api/v1/reviews/{task_id}/stream` SSE 端点：轮询任务进度，以 `progress` / `complete` / `error` 事件推送状态，进度存储使用内存字典（标注后续迁移到 Redis Pub/Sub） | `app/api/v1/ws.py` |
| 8.3 | 在 `main.py` 中注册 SSE 路由 | `app/main.py` |

### 任务 9：Skill 管理 API

| # | 任务 | 涉及文件 |
|---|------|----------|
| 9.1 | 创建 `GET /api/v1/skills`：返回所有已注册 Skill 的元数据列表（name、display_name、version、category、description、languages、tags） | `app/api/v1/skills.py` |
| 9.2 | 创建 `POST /api/v1/skills/execute`：接收 skill_name、code、file_path，调用 SkillExecutor 执行并返回 success、summary、findings、execution_time_ms | `app/api/v1/skills.py` |
| 9.3 | 创建 `POST /api/v1/skills/reload`：重新加载所有内置 Skill，返回加载数量 | `app/api/v1/skills.py` |
| 9.4 | 在 `main.py` 中注册 skills 路由，在 lifespan 中调用 `init_skills()` | `app/main.py` |

---

## 验收标准

### 多Agent 协作
- [ ] `POST /api/v1/reviews` 并行执行 5 个 Agent 的审查，总耗时接近最慢 Agent 的耗时（而非串行累加）
- [ ] Security Auditor 能通过正则扫描检测到硬编码密钥（如 `API_KEY = "sk-..."`）和 SQL 注入（字符串拼接 SQL）
- [ ] Security Auditor 能通过 LLM 深度分析检测到 XSS、路径遍历、不安全反序列化等复杂漏洞
- [ ] Architecture Analyzer 能通过依赖图检测到模块间的循环依赖
- [ ] Architecture Analyzer 能检测到被超过 5 个模块依赖的高耦合节点
- [ ] Performance Profiler 能正确计算函数的圈复杂度（至少覆盖 if/for/while/except/match 分支节点）
- [ ] Performance Profiler 能通过 LLM 检测到 N+1 查询、循环嵌套等性能问题
- [ ] Refactor Advisor 能通过 AST 检测到参数超过 5 个的函数
- [ ] Refactor Advisor 能通过 LLM 输出包含代码示例的重构方案

### 仲裁与报告
- [ ] Arbitrator 能正确去重（相同 file_path + line_start + category 只保留一条）
- [ ] Arbitrator 能按严重等级正确排序（critical > high > medium > low > info）
- [ ] Arbitrator 评分公式正确：`max(0, 10 - (critical*2 + high*1 + medium*0.3 + low*0.1) * 0.5)`，上限 10
- [ ] 审查结果包含 HTML 格式的完整报告（含评分、统计、问题详情、代码片段）

### Skill 系统
- [ ] `GET /api/v1/skills` 列出所有已注册的 Skill（至少包含 ast_scan 和 semgrep_scan）
- [ ] `POST /api/v1/skills/execute` 能单独执行指定 Skill 并返回正确结果
- [ ] `POST /api/v1/skills/reload` 能重新加载 Skill 并返回最新数量
- [ ] ASTScanSkill 能正确统计代码中的函数和类数量
- [ ] SemgrepScanSkill 在 Semgrep 已安装时能正常执行（未安装时返回友好错误提示）

### 实时进度
- [ ] SSE 端点 `GET /api/v1/reviews/{task_id}/stream` 能实时推送审查进度（progress 事件）
- [ ] 审查完成时 SSE 推送 complete 事件并关闭连接
- [ ] 审查失败时 SSE 推送 error 事件

---

## 技术决策说明

- **安全审计采用"正则先行 + LLM 深度分析"双层策略**：正则扫描速度快（毫秒级），覆盖常见模式；LLM 推理（GLM-5.2）覆盖复杂场景，两者互补减少漏报
- **架构分析使用 networkx 构建依赖图**：相比纯 LLM 分析，图算法能精确检测循环依赖和耦合度，不依赖模型推理质量；图分析后的架构评估使用 DeepSeek V4 推理
- **性能分析以圈复杂度为核心指标**：圈复杂度是代码可测试性和 bug 风险的最直接指标，计算完全基于 AST，无需 LLM 参与；LLM 性能分析使用本地 DeepSeek-Coder-6.7B
- **模型分配策略**：Security Auditor 和 Refactor Advisor 使用 GLM-5.2（推理），Architecture Analyzer 和 Arbitrator 使用 DeepSeek V4（推理），Performance Profiler 和 Style Checker 使用本地模型（工具）
- **Skill 系统采用插件化架构**：基于抽象基类 + 注册中心 + 动态加载器，支持热加载和用户自定义扩展
- **LangGraph 并行节点设计**：5 个 Agent 节点从 parse_code 分叉后并行执行，汇聚到 arbitrate 节点，充分利用异步 I/O 减少总耗时