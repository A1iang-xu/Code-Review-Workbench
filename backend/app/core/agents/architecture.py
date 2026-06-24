"""
Architecture Analyzer Agent

架构分析 Agent，分为两步：
1. 依赖图分析：使用 networkx 构建模块依赖图，检测循环依赖和高耦合节点
2. LLM 架构评估：使用推理模型（DeepSeek V4）进行语义级架构分析

图分析能精确检测结构性问题（循环依赖、扇入扇出），不依赖模型推理质量。
"""

import json
import re
from typing import Any

from app.core.agents.base import AgentContext, BaseReviewAgent
from app.integrations.ast_engine import ParsedFile


# ============================================================
# 系统提示词
# ============================================================

ARCHITECTURE_PROMPT = """You are a senior software architect conducting a code architecture review.
Analyze the provided codebase for the following 6 dimensions:

1. **Module Partitioning**: Are modules (files/classes) well-separated by responsibility?
   Look for files that mix concerns (e.g., database access + UI logic in one file).
2. **Dependency Direction**: Do dependencies flow in the right direction (e.g., high-level → low-level)?
   Flag any dependency inversion violations.
3. **Interface Design**: Are public interfaces (function signatures, class APIs) clean and minimal?
   Look for functions with too many parameters or classes exposing too many public methods.
4. **Design Patterns**: Are appropriate design patterns used? Are there anti-patterns (God Object, Singleton abuse)?
5. **Coupling**: Are modules tightly coupled? Look for direct imports that could be abstracted.
6. **Cohesion**: Do classes/functions have a single, clear responsibility?

For each finding, return a JSON object with:
{
    "severity": "critical|high|medium|low",
    "category": "module_partitioning|dependency_direction|interface_design|design_pattern|coupling|cohesion",
    "title": "brief description of the architectural issue",
    "description": "detailed explanation of why this is a problem",
    "suggestion": "specific refactoring recommendation with code example if applicable",
    "line_start": 0,
    "line_end": 0
}

IMPORTANT:
- Return ONLY a valid JSON array. No markdown, no extra text.
- If no architectural issues found, return [].
- Focus on structural and design-level concerns, not implementation details."""


class ArchitectureAnalyzerAgent(BaseReviewAgent):
    """架构分析 Agent。

    双层策略：
    1. networkx 依赖图分析：检测循环依赖、高耦合节点（毫秒级，精确）
    2. LLM 架构评估（DeepSeek V4 推理）：模块划分、接口设计、设计模式等
    """

    agent_type = "architecture"
    display_name = "架构分析Agent"

    # ---- 依赖图分析 ----

    def _build_dependency_graph(
        self, parsed_files: list[ParsedFile]
    ) -> "tuple[Any, dict[str, set[str]]]":
        """构建模块依赖图。

        遍历所有文件的 import 语句，构建有向图。
        节点为模块名（文件路径去后缀），边为 import 依赖。

        Args:
            parsed_files: 已解析的文件列表

        Returns:
            (networkx.DiGraph, module_to_external_deps):
            - DiGraph: 模块间依赖图
            - dict: 模块到外部依赖集合的映射
        """
        import networkx as nx

        graph = nx.DiGraph()
        module_names: dict[str, str] = {}  # file_path → module_name

        for pf in parsed_files:
            if pf.language != "python":
                continue

            # 将文件路径转换为模块名
            module_name = self._path_to_module(pf.path)
            module_names[pf.path] = module_name

            if not graph.has_node(module_name):
                graph.add_node(module_name)
                # 存储文件路径作为节点属性
                graph.nodes[module_name]["file_path"] = pf.path

        # 第二轮：提取 import 关系
        for pf in parsed_files:
            if pf.language != "python" or pf.tree is None:
                continue

            module_name = module_names[pf.path]
            imports = self._extract_imports(pf.content)

            for imported in imports:
                # 将 import 路径转换为模块名并在图中找到或创建
                imported_module = self._resolve_import(imported)

                if imported_module and imported_module != module_name:
                    if not graph.has_node(imported_module):
                        graph.add_node(imported_module)
                    # 添加有向边: 当前模块 → 被导入的模块
                    if not graph.has_edge(module_name, imported_module):
                        graph.add_edge(module_name, imported_module)

        return graph, module_names

    def _path_to_module(self, file_path: str) -> str:
        """将文件路径转换为模块名。

        e.g., 'app/core/agents/security.py' → 'app.core.agents.security'
              'src/utils/helpers.py' → 'src.utils.helpers'

        Args:
            file_path: 文件路径

        Returns:
            模块名（点分隔）
        """
        # 去掉后缀
        path = file_path
        if path.endswith(".py"):
            path = path[:-3]
        # 去掉 __init__ 后缀（__init__ 文件即是包本身）
        if path.endswith("__init__"):
            # Remove __init__ from path: "pkg/__init__" -> "pkg", root "__init__" -> ""
            parent = path.rsplit("/", 1)[0] if "/" in path else ""
            return (parent or path).replace("/", ".").replace("\\", ".").strip(".")
        # 路径分隔符转点
        module = path.replace("/", ".").replace("\\", ".")
        # 清理首尾点
        return module.strip(".")

    def _extract_imports(self, content: str) -> list[str]:
        """从 Python 源代码中提取所有 import 目标。

        支持:
        - import X, import X.Y
        - from X import Y, from X.Y import Z
        - from .X import Y (相对导入)
        - from ..X import Y (多级相对导入)

        Args:
            content: 源代码文本

        Returns:
            导入模块名列表
        """
        imports: list[str] = []

        # import X, import X.Y, import X as Z
        import_pattern = re.findall(
            r'^\s*import\s+([\w.]+(?:\s*,\s*[\w.]+)*)',
            content,
            re.MULTILINE,
        )
        for match in import_pattern:
            for part in re.split(r'\s*,\s*', match):
                part = part.strip()
                if part:
                    imports.append(part)

        # from X import Y, from X.Y import Z
        from_pattern = re.findall(
            r'^\s*from\s+([\w.]+)\s+import',
            content,
            re.MULTILINE,
        )
        for match in from_pattern:
            if match:
                imports.append(match.strip())

        return imports

    def _resolve_import(self, imported: str) -> str | None:
        """解析 import 目标为模块名。

        处理相对导入和第三方库过滤。

        Args:
            imported: import 语句中的模块名

        Returns:
            解析后的模块名，如果为第三方库则返回 None
        """
        # 过滤标准库和第三方库
        stdlib_top = {
            "os", "sys", "re", "json", "math", "datetime", "collections",
            "itertools", "functools", "typing", "abc", "pathlib", "io",
            "subprocess", "logging", "hashlib", "base64", "uuid", "copy",
            "enum", "dataclasses", "asyncio", "threading", "multiprocessing",
            "http", "urllib", "socket", "ssl", "email", "csv", "xml",
            "argparse", "configparser", "unittest", "traceback", "warnings",
            "contextlib", "inspect", "ast", "textwrap", "shutil", "tempfile",
            "pickle", "marshal", "struct", "sqlite3", "random", "statistics",
            "time", "platform", "signal", "atexit", "gc", "types",
        }

        top_level = imported.split(".")[0]
        if top_level in stdlib_top:
            return None

        # 常见第三方库
        third_party = {
            "fastapi", "uvicorn", "sqlalchemy", "alembic", "pydantic",
            "langgraph", "langchain", "litellm", "starlette", "networkx",
            "tree_sitter", "semgrep", "radon", "redis", "celery",
            "httpx", "pymilvus", "tiktoken", "opentelemetry",
            "prometheus_client", "websockets", "git", "numpy", "pandas",
            "requests", "aiohttp", "transformers", "torch", "tensorflow",
        }
        if top_level in third_party:
            return None

        return imported

    def _analyze_graph(
        self, graph: "Any", module_names: dict[str, str],
        parsed_files: list[ParsedFile] | None = None,
    ) -> list[dict]:
        """分析依赖图，检测循环依赖和高耦合节点。

        Args:
            graph: networkx.DiGraph
            module_names: file_path → module_name 映射
            parsed_files: 可选，用于基于文件数判断是否启用孤立模块检测

        Returns:
            架构问题列表
        """
        import networkx as nx

        issues: list[dict] = []

        # 反向映射：module_name → file_path
        module_to_path: dict[str, str] = {}
        for path, mod in module_names.items():
            module_to_path[mod] = path

        # --- 检测循环依赖 ---
        try:
            cycles = list(nx.simple_cycles(graph))
            for cycle in cycles:
                if len(cycle) >= 2:
                    # 获取文件路径
                    cycle_paths = [
                        module_to_path.get(n, graph.nodes[n].get("file_path", n))
                        for n in cycle
                    ]
                    cycle_str = " → ".join(cycle) + " → " + cycle[0]

                    issues.append({
                        "agent_type": self.agent_type,
                        "severity": "high",
                        "file_path": cycle_paths[0],
                        "line_start": 0,
                        "line_end": 0,
                        "category": "dependency_direction",
                        "title": f"循环依赖: {len(cycle)} 个模块形成依赖环",
                        "description": (
                            f"以下 {len(cycle)} 个模块形成循环依赖: {cycle_str}。"
                            f"循环依赖使模块无法独立测试和复用，增加耦合度。"
                        ),
                        "suggestion": (
                            "打破循环依赖的方法："
                            "1) 提取公共接口/抽象到独立模块；"
                            "2) 使用依赖注入反转依赖方向；"
                            "3) 将共享逻辑提取到新的底层模块。"
                        ),
                        "code_snippet": "",
                    })
        except Exception:
            pass  # 图分析失败不影响后续流程

        # --- 检测高耦合节点（入度 > 5）---
        in_degrees = dict(graph.in_degree())
        high_coupling = {
            node: deg for node, deg in in_degrees.items() if deg > 5
        }

        for node, degree in sorted(
            high_coupling.items(), key=lambda x: -x[1]
        ):
            file_path = module_to_path.get(
                node, graph.nodes[node].get("file_path", node)
            )
            # 获取依赖于该节点的模块列表
            dependents = [
                pred
                for pred in graph.predecessors(node)
            ]

            severity = "critical" if degree > 10 else "high" if degree > 8 else "medium"

            issues.append({
                "agent_type": self.agent_type,
                "severity": severity,
                "file_path": file_path,
                "line_start": 0,
                "line_end": 0,
                "category": "coupling",
                "title": f"高耦合节点: '{node}' 被 {degree} 个模块依赖",
                "description": (
                    f"模块 '{node}' 被 {degree} 个模块直接依赖，"
                    f"超过推荐的 5 个上限。"
                    f"高耦合意味着修改此模块可能影响 {degree} 个下游模块。"
                    f"依赖者包括: {', '.join(dependents[:5])}"
                    f"{'...' if len(dependents) > 5 else ''}"
                ),
                "suggestion": (
                    "降低耦合度的方法："
                    "1) 提取接口（抽象基类/Protocol）到独立层；"
                    "2) 使用事件驱动架构解耦；"
                    "3) 考虑是否可拆分此模块为多个职责更单一的模块。"
                ),
                "code_snippet": "",
            })

        # --- 检测孤岛模块（出度和入度均为 0）---
        # 仅在 ≥ 2 个文件时检测：单文件审查必然出现"孤立模块"误报
        if parsed_files is None or len(parsed_files) >= 2:
            isolated = [
                node for node in graph.nodes()
                if graph.in_degree(node) == 0 and graph.out_degree(node) == 0
                and node in module_to_path
            ]
            if isolated and len(isolated) <= 10:
                for node in isolated:
                    file_path = module_to_path.get(node, node)
                    issues.append({
                        "agent_type": self.agent_type,
                        "severity": "low",
                        "file_path": file_path,
                        "line_start": 0,
                        "line_end": 0,
                        "category": "module_partitioning",
                        "title": f"孤立模块: '{node}' 无任何依赖关系",
                        "description": (
                            f"模块 '{node}' 既不被其他模块引用，也不依赖任何项目内模块。"
                            f"可能是未使用的死代码或缺少集成。"
                        ),
                        "suggestion": "确认此模块是否仍在使用。如已废弃应移除；如仍需使用应添加适当的集成。",
                        "code_snippet": "",
                    })

        return issues

    # ---- LLM 架构分析 ----

    async def _llm_analyze_architecture(
        self, parsed_files: list[ParsedFile]
    ) -> list[dict]:
        """使用推理模型（DeepSeek V4）进行架构评估。

        关注模块划分、接口设计、设计模式、内聚性等图分析难以覆盖的维度。

        Args:
            parsed_files: 已解析的文件列表

        Returns:
            LLM 发现的架构问题列表
        """
        # 构建代码概要（文件列表 + 类/函数签名摘要）
        code_summary_parts: list[str] = []
        for pf in parsed_files:
            if pf.language != "python":
                continue
            # 提取关键信息
            lines = pf.content.split("\n")
            class_func_lines = [
                ln for ln in lines
                if ln.strip().startswith(("class ", "def ", "async def "))
            ]
            summary = f"# {pf.path} ({len(lines)} lines)\n"
            summary += "\n".join(class_func_lines[:30])  # 最多 30 个签名
            code_summary_parts.append(summary)

        code_summary = "\n\n".join(code_summary_parts)

        # 限制总长度
        if len(code_summary) > 10000:
            code_summary = code_summary[:10000] + "\n# ... (truncated)"

        try:
            response = await self._llm_analyze(
                prompt=f"{ARCHITECTURE_PROMPT}\n\nAnalyze the following project structure:",
                code_context=code_summary,
                use_reasoning=True,  # 使用 DeepSeek V4 推理
            )

            # 尝试提取 JSON 数组
            json_match = re.search(r"\[.*\]", response, re.DOTALL)
            if json_match:
                try:
                    findings = json.loads(json_match.group(0))
                except json.JSONDecodeError:
                    raw = json_match.group(0)
                    raw = re.sub(r",\s*]", "]", raw)
                    try:
                        findings = json.loads(raw)
                    except json.JSONDecodeError:
                        findings = []
            else:
                findings = []

            # 补充 agent_type 和默认值
            for f in findings:
                f["agent_type"] = self.agent_type
                f["file_path"] = f.get("file_path", parsed_files[0].path if parsed_files else "")
                f["line_start"] = f.get("line_start", 0)
                f["line_end"] = f.get("line_end", 0)
                f["code_snippet"] = f.get("code_snippet", "")
                if f.get("severity") not in ("critical", "high", "medium", "low", "info"):
                    f["severity"] = "medium"

            return findings

        except Exception as e:
            # LLM 失败时静默跳过，避免在问题列表中产生 llm_error 噪声
            print(f"[ArchitectureAnalyzer] LLM 分析失败，已跳过: {e}")
            return []

    # ---- 主 entry point ----

    async def review(self, parsed_files: list[ParsedFile]) -> list[dict]:
        """执行架构分析。

        两步策略：
        1. 依赖图分析（networkx）：循环依赖、高耦合、孤立模块
        2. LLM 架构评估（DeepSeek V4）：模块划分、接口设计、设计模式、内聚性

        Args:
            parsed_files: ASTEngine 解析后的文件列表

        Returns:
            所有架构问题的列表
        """
        all_issues: list[dict] = []

        # 步骤 1: 依赖图分析
        try:
            import networkx as nx
            graph, module_names = self._build_dependency_graph(parsed_files)
            graph_issues = self._analyze_graph(graph, module_names, parsed_files)
            all_issues.extend(graph_issues)
        except ImportError:
            all_issues.append({
                "agent_type": self.agent_type,
                "severity": "info",
                "file_path": "",
                "line_start": 0,
                "line_end": 0,
                "category": "tool_error",
                "title": "networkx 未安装，跳过依赖图分析",
                "description": "请运行 `pip install networkx`",
                "suggestion": "pip install networkx",
                "code_snippet": "",
            })
        except Exception as e:
            all_issues.append({
                "agent_type": self.agent_type,
                "severity": "info",
                "file_path": "",
                "line_start": 0,
                "line_end": 0,
                "category": "tool_error",
                "title": f"依赖图分析失败: {str(e)[:100]}",
                "description": "依赖图构建或分析过程中出现异常",
                "suggestion": "请检查代码是否正确解析",
                "code_snippet": "",
            })

        # 步骤 2: LLM 架构评估
        llm_issues = await self._llm_analyze_architecture(parsed_files)
        all_issues.extend(llm_issues)

        return all_issues
