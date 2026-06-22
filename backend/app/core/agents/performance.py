"""
Performance Profiler Agent

性能分析 Agent，分为两步：
1. AST 圈复杂度分析：通过 Tree-sitter 遍历函数体统计分支节点，计算圈复杂度
2. LLM 性能分析：使用本地模型检测 N+1 查询、循环嵌套、内存分配等性能问题
"""

import json
import re

from app.core.agents.base import AgentContext, BaseReviewAgent
from app.integrations.ast_engine import ParsedFile


# ============================================================
# 系统提示词
# ============================================================

PERFORMANCE_PROMPT = """You are a senior performance engineer conducting a code review.
Analyze the provided code for the following 7 categories of performance issues:

1. **Nested Loops**: O(n²) or worse complexity. Flag triple-nested and deep double-nested loops.
2. **Repeated Computation**: Values computed multiple times in hot paths; missing memoization/caching.
3. **Memory Allocation**: Large objects created in loops, missing buffer reuse, excessive GC pressure.
4. **N+1 Query Pattern**: Database or API calls inside loops that could be batched.
5. **Blocking I/O**: Synchronous I/O in async code, missing concurrency for independent operations.
6. **String Concatenation**: String building via += in loops instead of join() or StringBuilder.
7. **List Comprehension Abuse**: Unnecessarily nested comprehensions, giant comprehensions that hurt readability and memory.

For each finding, return a JSON object with:
{
    "severity": "critical|high|medium|low",
    "category": "nested_loops|repeated_computation|memory_allocation|n_plus_one|blocking_io|string_concat|comprehension_abuse",
    "title": "brief description of the performance issue",
    "description": "detailed explanation of the performance impact with complexity analysis",
    "suggestion": "specific optimization with code example showing before/after",
    "line_start": 0,
    "line_end": 0
}

IMPORTANT:
- Return ONLY a valid JSON array. No markdown, no extra text.
- If no performance issues found, return [].
- Focus on real performance bottlenecks, not micro-optimizations."""


class PerformanceProfilerAgent(BaseReviewAgent):
    """性能分析 Agent。

    双层策略：
    1. AST 圈复杂度分析：精确计算每个函数的圈复杂度，无需 LLM
    2. LLM 性能分析（本地模型）：N+1 查询、循环嵌套、内存分配等
    """

    agent_type = "performance"
    display_name = "性能优化Agent"

    # ---- 圈复杂度计算 ----

    def _walk_with_depth(self, node, callback, depth: int = 0):
        """遍历 AST 节点树（带深度信息）。

        Args:
            node: 当前 Tree-sitter 节点
            callback: (node, depth) → None
            depth: 当前深度
        """
        callback(node, depth)
        for child in node.children:
            self._walk_with_depth(child, callback, depth + 1)

    def _count_branch_nodes(self, node) -> int:
        """统计函数体内的所有分支节点数量。

        分支节点类型：
        - if_statement (if/elif)
        - for_statement (for ... in)
        - while_statement
        - try_statement (except 子句)
        - match_statement (Python 3.10+)
        - boolean_operator (and/or)
        - not_operator
        - conditional_expression (x if cond else y)
        - case_clause (match case)

        Args:
            node: 函数定义节点

        Returns:
            分支节点数量
        """
        branch_node_types = {
            "if_statement",
            "elif_clause",
            "for_statement",
            "while_statement",
            "try_statement",   # try 本身引入分支
            "except_clause",
            "match_statement",
            "case_clause",
            "boolean_operator",    # and / or
            "not_operator",
            "conditional_expression",  # x if cond else y
        }

        count = 0

        def count_branch(n, _depth):
            nonlocal count
            if n.type in branch_node_types:
                count += 1

        self._walk_with_depth(node, count_branch)
        return count

    def _get_func_name(self, node) -> str:
        """从函数/方法定义的 AST 节点提取函数名。"""
        for child in node.children:
            if child.type == "def":
                continue
            if child.type == "identifier":
                return child.text.decode("utf-8")
            if child.type == "function_definition":
                return self._get_func_name(child)
        return "<unknown>"

    def _calculate_cyclomatic_complexity(self, func_node) -> int:
        """计算函数的圈复杂度。

        公式: 1 + 分支节点数

        分支节点包括: if/elif/for/while/try/except/match/case/and/or/not/conditional_expression

        Args:
            func_node: 函数定义 AST 节点

        Returns:
            圈复杂度数值（最小为 1）
        """
        branch_count = self._count_branch_nodes(func_node)
        return 1 + branch_count

    def _complexity_check(self, parsed_file: ParsedFile) -> list[dict]:
        """对所有函数计算圈复杂度并按阈值分级。

        阈值:
        - > 20: critical（极高复杂度，几乎不可测试）
        - > 10: high（高复杂度，建议重构）
        - > 5: medium（中等复杂度，关注）

        Args:
            parsed_file: 已解析的文件

        Returns:
            复杂度问题列表
        """
        issues: list[dict] = []

        if parsed_file.tree is None:
            return issues

        root = parsed_file.tree.root_node

        # 查找所有函数和类方法
        func_nodes: list = []
        class_names: list[str] = ["__top__"]  # 用栈追踪类名

        def find_functions(node):
            if node.type in ("function_definition", ):
                func_nodes.append((node, class_names[-1] if class_names else "__top__"))
            elif node.type in ("class_definition", "decorated_definition"):
                # 提取类名
                for child in node.children:
                    if child.type == "identifier":
                        class_names.append(child.text.decode("utf-8"))
                        break
                else:
                    class_names.append("<unknown>")

            for child in node.children:
                find_functions(child)

            if node.type in ("class_definition", "decorated_definition"):
                if len(class_names) > 1:
                    class_names.pop()

        find_functions(root)

        for func_node, class_name in func_nodes:
            complexity = self._calculate_cyclomatic_complexity(func_node)
            func_name = self._get_func_name(func_node)
            start_line = func_node.start_point[0] + 1
            end_line = func_node.end_point[0] + 1
            func_lines = end_line - start_line + 1

            # 按阈值分级
            if complexity > 20:
                severity = "critical"
            elif complexity > 10:
                severity = "high"
            elif complexity > 5:
                severity = "medium"
            else:
                continue  # 复杂度低，跳过

            qualified_name = (
                f"{class_name}.{func_name}" if class_name != "__top__" else func_name
            )

            issues.append({
                "agent_type": self.agent_type,
                "severity": severity,
                "file_path": parsed_file.path,
                "line_start": start_line,
                "line_end": end_line,
                "category": "cyclomatic_complexity",
                "title": (
                    f"函数 '{qualified_name}' 圈复杂度过高 "
                    f"({complexity}, {func_lines} 行)"
                ),
                "description": (
                    f"函数 '{qualified_name}' 的圈复杂度为 {complexity}，"
                    f"超过推荐值（推荐 <= 10）。"
                    f"高圈复杂度意味着函数有大量分支路径，难以测试和维护。"
                    f"当前包含 {func_lines} 行代码、{complexity - 1} 个分支节点。"
                ),
                "suggestion": (
                    "降低圈复杂度的方法：\n"
                    "1) 提取条件分支到独立函数（Guard Clause 模式）；\n"
                    "2) 使用策略模式/字典映射替代大量 if-elif 链；\n"
                    "3) 提前返回（Early Return）减少嵌套层级；\n"
                    "4) 将复杂逻辑拆分为多个小函数。"
                ),
                "code_snippet": func_node.text.decode("utf-8")[:500],
            })

        return issues

    # ---- LLM 性能分析 ----

    async def _llm_perf_analysis(self, parsed_file: ParsedFile) -> list[dict]:
        """使用本地模型进行性能分析。

        检测 N+1 查询、循环嵌套、内存分配、I/O 阻塞等问题。
        使用通用模型（非推理）以降低成本。

        Args:
            parsed_file: 已解析的文件

        Returns:
            LLM 发现的性能问题列表
        """
        content = parsed_file.content

        # 限制长度
        if len(content) > 10000:
            content = content[:10000] + "\n# ... (truncated)"

        try:
            response = await self._llm_analyze(
                prompt=PERFORMANCE_PROMPT,
                code_context=content,
                use_reasoning=False,  # 使用本地模型
            )

            # 提取 JSON 数组
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

            for f in findings:
                f["agent_type"] = self.agent_type
                f["file_path"] = parsed_file.path
                f["line_start"] = f.get("line_start", 0)
                f["line_end"] = f.get("line_end", 0)
                f["code_snippet"] = f.get("code_snippet", "")
                if f.get("severity") not in ("critical", "high", "medium", "low", "info"):
                    f["severity"] = "medium"

            return findings

        except (json.JSONDecodeError, Exception) as e:
            return [{
                "agent_type": self.agent_type,
                "severity": "info",
                "file_path": parsed_file.path,
                "line_start": 0,
                "line_end": 0,
                "category": "llm_error",
                "title": f"LLM 性能分析失败: {str(e)[:100]}",
                "description": "本地模型调用失败，仅完成圈复杂度分析",
                "suggestion": "请检查 Ollama 是否运行并已部署模型",
                "code_snippet": "",
            }]

    # ---- 主 entry point ----

    async def review(self, parsed_files: list[ParsedFile]) -> list[dict]:
        """执行性能分析。

        两步策略：
        1. AST 圈复杂度分析（精确，无需 LLM）
        2. LLM 性能分析（本地模型，检测 N+1 查询等模式）

        Args:
            parsed_files: ASTEngine 解析后的文件列表

        Returns:
            所有性能问题的列表
        """
        all_issues: list[dict] = []

        for pf in parsed_files:
            if pf.language != "python":
                continue

            # 步骤 1: AST 复杂度分析
            complexity_issues = self._complexity_check(pf)
            all_issues.extend(complexity_issues)

            # 步骤 2: LLM 性能分析
            llm_issues = await self._llm_perf_analysis(pf)
            all_issues.extend(llm_issues)

        return all_issues
