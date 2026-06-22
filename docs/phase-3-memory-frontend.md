# 阶段三：记忆系统 + 上下文压缩 + 前端

> 目标：实现四层记忆体系、智能上下文压缩，构建完整的前端 Web 应用（Dashboard + 审查详情 + Skill 管理）。
> 前置条件：阶段二验收通过（5 Agent 并行审查 + 仲裁正常，Skill 系统可运行）

---

## 前置条件

1. 阶段二全部验收标准通过
2. `backend/pyproject.toml` 已包含 `tiktoken` 依赖（`pip install tiktoken`）
3. Node.js 20+ 已安装
4. 前端目录 `frontend/` 已创建

---

## 任务清单

### 任务 1：工作记忆（Working Memory）

| # | 任务 | 涉及文件 |
|---|------|----------|
| 1.1 | 创建 `WorkingMemory` 类：管理当前审查任务的上下文窗口，维护 `messages` 列表和 `scratch_pad` 字典 | `app/core/memory/working.py` |
| 1.2 | 实现 `add_message(role, content)` 方法：添加消息并统计 token 数（使用 `tiktoken` 的 `cl100k_base` 编码），超限时从最旧消息开始丢弃（保留 system prompt） | `app/core/memory/working.py` |
| 1.3 | 实现 `set(key, value)` / `get(key, default)` 方法：管理临时上下文数据 | `app/core/memory/working.py` |
| 1.4 | 实现 `clear()` 方法：重置消息列表和 token 计数 | `app/core/memory/working.py` |
| 1.5 | 实现 `get_context(max_messages)` 方法：返回最近 N 条消息 | `app/core/memory/working.py` |
| 1.6 | 实现 `token_usage` 属性：返回当前 token 占用数 | `app/core/memory/working.py` |

### 任务 2：情节记忆（Episodic Memory）

| # | 任务 | 涉及文件 |
|---|------|----------|
| 2.1 | 创建 `EpisodicMemory` 类：跨会话的审查历史记忆，基于 JSON 文件持久化，最大存储 100 条记录 | `app/core/memory/episodic.py` |
| 2.2 | 实现 `save_session(task_id, review_result, issues)` 方法：调用 LLM 生成审查摘要和关键事实，保存 episode 记录（task_id、timestamp、summary、key_facts、score、issue_count、repo_url、top_categories） | `app/core/memory/episodic.py` |
| 2.3 | 实现 `_summarize_session()` 方法：使用 LLM utility 模型将 Top 10 问题总结为 2-3 句摘要 | `app/core/memory/episodic.py` |
| 2.4 | 实现 `_extract_facts()` 方法：从审查结果中提取 critical/high 级别的问题标题作为关键事实 | `app/core/memory/episodic.py` |
| 2.5 | 实现 `retrieve_recent(n)` 方法：返回最近 N 条审查记录 | `app/core/memory/episodic.py` |
| 2.6 | 实现 `search(query, top_k)` 方法：基于关键词匹配搜索相关审查记录 | `app/core/memory/episodic.py` |

### 任务 3：语义记忆（Semantic Memory）

| # | 任务 | 涉及文件 |
|---|------|----------|
| 3.1 | 创建 `SemanticMemory` 类：长期语义记忆，存储审查规则、代码模式和最佳实践，基于 JSON 文件持久化 | `app/core/memory/semantic.py` |
| 3.2 | 实现 `add_rule(rule)` / `add_pattern(pattern)` / `add_best_practice(practice)` 方法：分别添加审查规则、代码模式、最佳实践（均带时间戳） | `app/core/memory/semantic.py` |
| 3.3 | 实现 `get_rules(category, language)` 方法：按分类和语言筛选审查规则 | `app/core/memory/semantic.py` |
| 3.4 | 实现 `get_prompt_context()` 方法：生成可注入 LLM 提示词的上下文文本，包含最近 5 条最佳实践和最近 10 条自定义规则 | `app/core/memory/semantic.py` |

### 任务 4：程序性记忆（Procedural Memory）

| # | 任务 | 涉及文件 |
|---|------|----------|
| 4.1 | 创建 `ProceduralMemory` 类：工具使用经验和修复模式积累，基于 JSON 文件持久化 | `app/core/memory/procedural.py` |
| 4.2 | 实现 `record_finding(issue_type, title, suggestion, severity)` 方法：记录一个审查发现及其修复建议，自动累加出现次数 | `app/core/memory/procedural.py` |
| 4.3 | 实现 `get_frequent_issues(top_k)` 方法：按出现次数降序返回最高频的问题类型 | `app/core/memory/procedural.py` |
| 4.4 | 实现 `get_suggestions_for(issue_type)` 方法：获取某类问题的最佳修复建议（按出现次数排序） | `app/core/memory/procedural.py` |
| 4.5 | 实现 `record_batch(issues)` 方法：批量记录审查发现 | `app/core/memory/procedural.py` |

### 任务 5：记忆系统集成 — MemoryManager

| # | 任务 | 涉及文件 |
|---|------|----------|
| 5.1 | 创建 `MemoryManager` 单例类：统一管理四层记忆（working / episodic / semantic / procedural） | `app/core/memory/__init__.py` |
| 5.2 | 实现 `new_session(max_tokens)` 方法：创建新的工作记忆会话 | `app/core/memory/__init__.py` |
| 5.3 | 实现 `get_system_context()` 方法：聚合三层记忆（语义记忆的规则和最佳实践 + 情节记忆的最近审查记录 + 程序性记忆的高频问题），生成可注入系统提示词的上下文文本 | `app/core/memory/__init__.py` |
| 5.4 | 实现 `save_session(task_id, review_result, issues)` 方法：审查完成后同时保存情节记忆和更新程序性记忆 | `app/core/memory/__init__.py` |

### 任务 6：上下文压缩系统

| # | 任务 | 涉及文件 |
|---|------|----------|
| 6.1 | 创建 `ModelTier` 枚举（LOCAL / CLOUD）和 `TokenBudget` dataclass（total / system_prompt / code_context / agent_messages / reserved），计算 used / available / usage_ratio 属性 | `app/core/compression/token_manager.py` |
| 6.2 | 创建 `TokenQuotaManager` 类：定义预算表（LOCAL: 4000 tokens, CLOUD: 64000 tokens），实现 `allocate_code()` / `allocate_system()` / `should_compress()` / `compress_messages()` 方法 | `app/core/compression/token_manager.py` |
| 6.3 | 实现 `compress_messages()` 方法：当 usage_ratio > 0.7 时，保留 system prompt + 最近 6 条消息，中间消息用摘要替代 | `app/core/compression/token_manager.py` |
| 6.4 | 创建 `SemanticChunker` 类：基于 Tree-sitter AST 的代码语义分块器 | `app/core/compression/chunker.py` |
| 6.5 | 实现 `chunk_by_function(code, max_chunk_tokens, language)` 方法：按函数/类边界分块，每块不超过 max_chunk_tokens，记录每个块的 symbols 列表 | `app/core/compression/chunker.py` |
| 6.6 | 实现 `chunk_for_review(code, target_tokens)` 方法：审查场景分块策略——代码总量 < target_tokens 直接返回整段，否则按函数分块 | `app/core/compression/chunker.py` |
| 6.7 | 实现 `_estimate_tokens(text)` 方法：粗略估算 token 数（字符数 / 4） | `app/core/compression/chunker.py` |
| 6.8 | 创建 `HierarchicalSummarizer` 类：分层摘要生成器（代码块 → 文件 → 模块 → 项目） | `app/core/compression/summarizer.py` |
| 6.9 | 实现 `summarize_code(code)` 方法：使用 LLM utility 模型对单段代码生成 1-2 句功能摘要 | `app/core/compression/summarizer.py` |
| 6.10 | 实现 `summarize_file(code_chunks)` 方法：对文件的所有代码块摘要进行汇总，生成文件级摘要 | `app/core/compression/summarizer.py` |
| 6.11 | 实现 `compress_agent_output(findings, max_items)` 方法：按严重等级排序后截断，只保留最重要的 N 条发现 | `app/core/compression/summarizer.py` |

### 任务 7：将记忆系统集成到审查工作流

| # | 任务 | 涉及文件 |
|---|------|----------|
| 7.1 | 在 `AgentContext` 中添加 `memory_context` 字段（默认为空字符串） | `app/core/agents/base.py` |
| 7.2 | 在 5 个 Agent 审查节点中，创建 AgentContext 时注入 `MemoryManager.get_system_context()` 作为 memory_context | `app/core/orchestrator.py` |
| 7.3 | 在 `generate_report_node` 中，审查完成后调用 `MemoryManager.save_session()` 保存记忆 | `app/core/orchestrator.py` |
| 7.4 | 在各 Agent 的 `_llm_analyze()` 调用中，将 `memory_context` 拼接到系统提示词末尾 | `app/core/agents/base.py` |

### 任务 8：前端项目初始化

| # | 任务 | 涉及文件 |
|---|------|----------|
| 8.1 | 使用 Vite 初始化 React + TypeScript 项目：`npm create vite@latest . -- --template react-ts` | `frontend/` |
| 8.2 | 安装依赖：`react-router-dom`、`@tanstack/react-query`、`axios`、`tailwindcss`、`@tailwindcss/vite` | `frontend/package.json` |
| 8.3 | 安装 UI 依赖：`@monaco-editor/react`（代码 Diff 视图）、`recharts`（图表）、`lucide-react`（图标）、`@headlessui/react`（Tab 组件） | `frontend/package.json` |
| 8.4 | 配置 Tailwind CSS：创建 `tailwind.config.js`，引入 `@tailwindcss/vite` 插件 | `frontend/tailwind.config.js`、`frontend/vite.config.ts` |
| 8.5 | 创建前端目录结构：`pages/`、`components/layout/`、`components/review/`、`components/charts/`、`components/common/`、`hooks/`、`services/`、`types/`、`styles/` | `frontend/src/` |

### 任务 9：TypeScript 类型定义与 API 服务层

| # | 任务 | 涉及文件 |
|---|------|----------|
| 9.1 | 定义 `ReviewTask` 接口：task_id、status、repo_url、branch、created_at、score、summary | `frontend/src/types/index.ts` |
| 9.2 | 定义 `CodeIssue` 接口：agent_type、severity、file_path、line_start、line_end、category、title、description、suggestion、code_snippet | `frontend/src/types/index.ts` |
| 9.3 | 定义 `ReviewReport` 接口：task_id、status、summary、score、report_html、stats（5 个 Agent 的问题数）、agent_timeline | `frontend/src/types/index.ts` |
| 9.4 | 定义 `AgentTimelineStep` 接口：agent_type、display_name、status、duration_ms、finding_count | `frontend/src/types/index.ts` |
| 9.5 | 定义 `SkillMeta` 接口：name、display_name、version、category、description、languages、tags | `frontend/src/types/index.ts` |
| 9.6 | 定义 `ReviewProgress` 接口：task_id、status、current_stage、progress、completed_agents | `frontend/src/types/index.ts` |
| 9.7 | 创建 `api.ts`：axios 实例配置（baseURL、timeout 120s），封装 `reviewApi`（create / get / list / streamProgress）和 `skillApi`（list / execute / reload） | `frontend/src/services/api.ts` |

### 任务 10：路由配置与布局组件

| # | 任务 | 涉及文件 |
|---|------|----------|
| 10.1 | 创建 `App.tsx`：配置 BrowserRouter，使用 QueryClientProvider 包裹，定义 5 条路由（/ → Dashboard、/reviews/new → ReviewCreate、/reviews/:taskId → ReviewDetail、/skills → SkillManager、/settings → Settings），整体布局为 Sidebar + main 内容区 | `frontend/src/App.tsx` |
| 10.2 | 创建 `Sidebar.tsx`：侧边栏导航，包含 Logo、5 个导航项（总览 / 新建审查 / Skill 管理 / 设置），使用 `lucide-react` 图标，当前路由高亮 | `frontend/src/components/layout/Sidebar.tsx` |
| 10.3 | 创建 `Header.tsx`：顶部栏，显示页面标题和用户信息占位 | `frontend/src/components/layout/Header.tsx` |

### 任务 11：核心页面 — Dashboard

| # | 任务 | 涉及文件 |
|---|------|----------|
| 11.1 | 创建 `Dashboard.tsx`：使用 `@tanstack/react-query` 的 `useQuery` 获取审查列表 | `frontend/src/pages/Dashboard.tsx` |
| 11.2 | 实现 4 个统计卡片（StatCard 组件）：总审查次数、平均评分、活跃 Agent 数、已注册 Skill 数，使用不同颜色（蓝/绿/紫/橙） | `frontend/src/pages/Dashboard.tsx` |
| 11.3 | 实现审查质量趋势图：使用 `recharts` 的 `BarChart`，X 轴为日期，Y 轴为评分 | `frontend/src/pages/Dashboard.tsx` |
| 11.4 | 实现最近审查列表表格：task_id、仓库、评分、状态、时间，支持点击跳转到详情页 | `frontend/src/pages/Dashboard.tsx` |

### 任务 12：核心页面 — 审查详情

| # | 任务 | 涉及文件 |
|---|------|----------|
| 12.1 | 创建 `ReviewDetail.tsx`：通过 `useParams` 获取 taskId，使用 `useQuery` 获取审查报告 | `frontend/src/pages/ReviewDetail.tsx` |
| 12.2 | 实现评分摘要区：大字显示评分（蓝色），旁边显示摘要文本和各 Agent 统计标签 | `frontend/src/pages/ReviewDetail.tsx` |
| 12.3 | 使用 `@headlessui/react` 的 `Tab.Group` 实现 3 个 Tab 页：问题列表 / 代码对比 / Agent 时间线 | `frontend/src/pages/ReviewDetail.tsx` |
| 12.4 | 处理加载状态（显示 "加载中..."）和空状态（显示 "未找到审查记录"） | `frontend/src/pages/ReviewDetail.tsx` |

### 任务 13：核心页面 — 创建审查

| # | 任务 | 涉及文件 |
|---|------|----------|
| 13.1 | 创建 `ReviewCreate.tsx`：提供代码输入区（使用 Monaco Editor）和仓库 URL 输入框 | `frontend/src/pages/ReviewCreate.tsx` |
| 13.2 | 实现文件管理：支持添加多个文件（每个文件有 path 和 content），支持删除文件 | `frontend/src/pages/ReviewCreate.tsx` |
| 13.3 | 实现提交审查按钮：调用 `reviewApi.create()`，提交后跳转到详情页 | `frontend/src/pages/ReviewCreate.tsx` |
| 13.4 | 实现文件上传功能：支持从本地选择 `.py` / `.go` / `.ts` / `.js` / `.java` 文件 | `frontend/src/pages/ReviewCreate.tsx` |

### 任务 14：核心页面 — Skill 管理

| # | 任务 | 涉及文件 |
|---|------|----------|
| 14.1 | 创建 `SkillManager.tsx`：使用 `useQuery` 获取 Skill 列表，以卡片网格展示 | `frontend/src/pages/SkillManager.tsx` |
| 14.2 | 每个 Skill 卡片展示：名称、版本、分类标签、描述、支持语言、tags | `frontend/src/pages/SkillManager.tsx` |
| 14.3 | 实现 Skill 测试功能：选中 Skill 后，在 Monaco Editor 中输入测试代码，点击执行查看结果 | `frontend/src/pages/SkillManager.tsx` |
| 14.4 | 实现 Skill 重载按钮：调用 `skillApi.reload()`，刷新列表 | `frontend/src/pages/SkillManager.tsx` |

### 任务 15：核心组件

| # | 任务 | 涉及文件 |
|---|------|----------|
| 15.1 | 创建 `DiffViewer.tsx`：使用 `@monaco-editor/react` 的 `DiffEditor`，支持 side-by-side 模式，语言选择器（Python/Go/TypeScript/JavaScript/Java） | `frontend/src/components/review/DiffViewer.tsx` |
| 15.2 | 创建 `IssueList.tsx`：问题列表组件，支持按严重等级筛选（全部/critical/high/medium/low/info），每条 issue 显示严重等级标签、Agent 类型、文件位置、标题、描述、建议、代码片段 | `frontend/src/components/review/IssueList.tsx` |
| 15.3 | 创建 `AgentTimeline.tsx`：Agent 执行时间线组件，垂直时间线展示 6 个 Agent（5 个审查 + 1 个仲裁），每个节点显示名称、状态（完成/执行中）、耗时、发现数，使用绿色圆点表示完成、蓝色脉冲圆点表示运行中 | `frontend/src/components/review/AgentTimeline.tsx` |
| 15.4 | 创建 `ReportPanel.tsx`：报告面板，渲染后端返回的 HTML 报告（使用 `dangerouslySetInnerHTML`） | `frontend/src/components/review/ReportPanel.tsx` |
| 15.5 | 创建 `SeverityBadge.tsx`：严重等级标签组件，根据等级显示不同颜色（critical=红、high=橙、medium=黄、low=蓝、info=灰） | `frontend/src/components/common/SeverityBadge.tsx` |
| 15.6 | 创建 `LoadingSpinner.tsx`：加载动画组件 | `frontend/src/components/common/LoadingSpinner.tsx` |
| 15.7 | 创建 `EmptyState.tsx`：空状态占位组件 | `frontend/src/components/common/EmptyState.tsx` |

### 任务 16：SSE 实时进度 Hook

| # | 任务 | 涉及文件 |
|---|------|----------|
| 16.1 | 创建 `useReviewProgress(taskId)` Hook：使用 `useEffect` 创建 EventSource 连接，监听 `progress` / `complete` / `error` 事件，返回 `ReviewProgress` 状态 | `frontend/src/hooks/useSSE.ts` |
| 16.2 | 在 ReviewDetail 页面中集成 SSE Hook：审查进行中时展示实时进度条和各 Agent 状态 | `frontend/src/pages/ReviewDetail.tsx` |

### 任务 17：全局样式

| # | 任务 | 涉及文件 |
|---|------|----------|
| 17.1 | 配置 Tailwind 全局样式：引入 `@tailwind base/components/utilities`，设置基础字体和背景色 | `frontend/src/styles/index.css` |
| 17.2 | 自定义滚动条样式、代码块样式、过渡动画 | `frontend/src/styles/index.css` |

---

## 验收标准

### 记忆系统
- [ ] 工作记忆能正常管理审查上下文，Token 超限时自动丢弃最旧消息（保留 system prompt）
- [ ] 情节记忆在审查完成后自动保存摘要和关键事实到 JSON 文件
- [ ] 情节记忆的 `retrieve_recent()` 能正确返回最近 N 条记录
- [ ] 情节记忆的 `search()` 能基于关键词匹配找到相关审查记录
- [ ] 语义记忆能存储和检索审查规则与最佳实践
- [ ] 语义记忆的 `get_prompt_context()` 能生成可注入提示词的上下文文本
- [ ] 程序性记忆能统计高频问题类型，按出现次数降序排列
- [ ] 程序性记忆的 `get_suggestions_for()` 能返回某类问题的最佳修复建议
- [ ] MemoryManager 的 `get_system_context()` 能聚合三层记忆生成完整上下文
- [ ] 审查完成后 MemoryManager 正确保存情节记忆和程序性记忆

### 上下文压缩
- [ ] Token 配额管理器在用量超过 70% 时触发压缩
- [ ] 消息压缩保留 system prompt 和最近 6 条消息，中间消息替换为摘要
- [ ] 语义分块器能按函数/类边界正确拆分代码
- [ ] 语义分块器的 `chunk_for_review()` 在代码总量未超限时返回整段代码
- [ ] 分层摘要生成器能对代码块生成 1-2 句功能摘要
- [ ] `compress_agent_output()` 能按严重等级排序后截断

### 前端
- [ ] 前端项目能正常启动（`npm run dev`）
- [ ] 路由切换正常：/ → Dashboard、/reviews/new → ReviewCreate、/reviews/:taskId → ReviewDetail、/skills → SkillManager、/settings → Settings
- [ ] Dashboard 正确展示 4 个统计卡片和趋势图
- [ ] 审查详情页的 Tab 切换正常（问题列表 / 代码对比 / Agent 时间线）
- [ ] Monaco Editor Diff 视图正常渲染，side-by-side 模式可用
- [ ] IssueList 支持按严重等级筛选，筛选后正确过滤
- [ ] AgentTimeline 正确展示 6 个 Agent 的执行状态和时间线
- [ ] ReviewCreate 页面支持添加/删除文件，提交后跳转到详情页
- [ ] SkillManager 正确展示 Skill 卡片列表，支持测试执行和重载
- [ ] SSE 实时进度在前端正确展示（进度条 + Agent 状态更新）
- [ ] 加载状态和空状态正确处理

---

## 技术决策说明

- **记忆系统采用四层架构**：灵感来自认知心理学，工作记忆管当前上下文、情节记忆管历史审查、语义记忆管知识积累、程序性记忆管经验沉淀，层层递进
- **情节记忆使用 JSON 文件存储（阶段三）**：快速实现验证，后续阶段迁移到 PostgreSQL + Milvus 向量检索
- **Token 估算使用字符数/4 的粗略方法**：tiktoken 精确计算用于消息压缩，AST 分块场景使用粗略估算减少开销
- **语义分块基于 AST 而非固定长度**：按函数/类边界分块保留代码语义完整性，避免在函数中间截断
- **前端使用 Vite + React 18 + TypeScript + Tailwind**：现代化工具链，开发体验好，Tailwind 的 utility-first 风格适合快速构建复杂 UI
- **Monaco Editor 用于 Diff 视图**：与 VS Code 同源，支持语法高亮、side-by-side 对比，开发者体验优秀