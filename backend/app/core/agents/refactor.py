"""
Refactor Advisor Agent

重构建议 Agent，分为两步：
1. AST 坏味道检测：检测过多参数（>5）、过长函数等结构性坏味道
2. LLM 重构建议：使用推理模型（GLM-5.2）生成含代码示例的重构方案
"""

import json
import re

from app.core.agents.base import AgentContext, BaseReviewAgent
from app.integrations.ast_engine import ParsedFile


# ============================================================
# 支持的语言
# ============================================================

SUPPORTED_LANGUAGES = {"python", "go", "typescript", "javascript", "java"}

# 各语言函数定义节点类型
_FUNC_NODE_TYPES: dict[str, tuple[str, ...]] = {
    "python": ("function_definition", "method_definition"),
    "go": ("function_declaration", "method_declaration"),
    "typescript": (
        "function_declaration", "method_definition",
        "arrow_function", "function_expression",
    ),
    "javascript": (
        "function_declaration", "method_definition",
        "arrow_function", "function_expression",
    ),
    "java": ("method_declaration", "constructor_declaration"),
}

# 各语言参数列表节点类型
_PARAM_LIST_TYPES: dict[str, str] = {
    "python": "parameters",
    "go": "parameter_list",
    "typescript": "formal_parameters",
    "javascript": "formal_parameters",
    "java": "formal_parameters",
}

# 各语言参数节点类型（单个参数）
_PARAM_NODE_TYPES: dict[str, tuple[str, ...]] = {
    "python": (
        "identifier", "typed_parameter", "typed_default_parameter",
        "default_parameter", "list_splat_pattern", "dictionary_splat_pattern",
    ),
    "go": ("parameter_declaration", "variadic_parameter_declaration"),
    "typescript": (
        "required_parameter", "optional_parameter",
        "rest_parameter", "formal_parameter",
    ),
    "javascript": (
        "identifier", "assignment_pattern",
        "rest_parameter", "formal_parameter",
    ),
    "java": ("formal_parameter", "spread_parameter"),
}

# 各语言应排除的隐式参数（如 self/this）
_IMPLICIT_PARAMS: dict[str, set[str]] = {
    "python": {"self", "cls"},
    "go": set(),  # Go receiver 不在参数列表中
    "typescript": {"this"},
    "javascript": {"this"},
    "java": set(),
}


# ============================================================
# 系统提示词
# ============================================================

REFACTOR_PROMPT = """You are a senior software engineer specializing in code refactoring.
Analyze the provided code for the following 10 code smells and anti-patterns:

1. **Long Function**: Functions/methods that are too long and do too many things. Flag functions > 50 lines.
2. **Too Many Parameters**: Functions with > 5 parameters — hard to call, hard to understand.
3. **Duplicate Code**: Repeated code blocks that should be extracted into a shared function.
4. **God Class**: Classes that have too many methods/responsibilities (trying to do everything).
5. **Data Clumps**: Groups of parameters that always appear together — should be a class/struct.
6. **Feature Envy**: A method that uses another class's data more than its own — move it.
7. **Switch Statements**: Long if-elif chains or switch/match statements that should use polymorphism.
8. **Divergent Change**: A class that changes for multiple different reasons (mixing concerns).
9. **Shotgun Surgery**: A small change that requires touching many different files.
10. **Comments Abuse**: Excessive comments explaining bad code instead of making code self-documenting.

For each finding, return a JSON object with:
{
    "severity": "critical|high|medium|low",
    "category": "long_function|too_many_params|duplicate_code|god_class|data_clumps|feature_envy|switch_statement|divergent_change|shotgun_surgery|comment_abuse",
    "title": "brief description of the code smell",
    "description": "detailed explanation of why this is a problem and its impact on maintainability",
    "suggestion": "specific refactoring plan with code example showing BEFORE and AFTER",
    "line_start": 0,
    "line_end": 0
}

IMPORTANT:
- Return ONLY a valid JSON array. No markdown, no extra text.
- Include concrete code examples in suggestions (BEFORE/AFTER format).
- If no code smells found, return []. Be honest — don't flag minor issues."""


class RefactorAdvisorAgent(BaseReviewAgent):
    """重构建议 Agent。

    双层策略：
    1. AST 坏味道检测：参数过多、长函数（精确，无需 LLM）
    2. LLM 重构方案（GLM-5.2 推理）：含代码示例的完整重构建议
    """

    agent_type = "refactor"
    display_name = "重构建议Agent"

    # ---- AST 坏味道检测 ----

    def _walk(self, node, callback):
        """递归遍历 AST 节点树。"""
        callback(node)
        for child in node.children:
            self._walk(child, callback)

    def _get_func_name(self, node, language: str = "python") -> str:
        """从函数/方法定义的 AST 节点提取函数名（多语言支持）。"""
        if language in ("typescript", "javascript"):
            for child in node.children:
                if child.type == "identifier":
                    return child.text.decode("utf-8")
                if child.type == "property_identifier":
                    for grandchild in child.children:
                        if grandchild.type == "identifier":
                            return grandchild.text.decode("utf-8")
            return "<unknown>"

        if language == "python":
            for child in node.children:
                if child.type == "def":
                    continue
                if child.type == "identifier":
                    return child.text.decode("utf-8")
                if child.type == "function_definition":
                    return self._get_func_name(child, language)
        elif language in ("go", "java"):
            for child in node.children:
                if child.type == "identifier":
                    return child.text.decode("utf-8")

        return "<unknown>"

    def _count_params(self, func_node, language: str = "python") -> int:
        """统计函数的参数数量（多语言支持）。

        Args:
            func_node: 函数定义 AST 节点
            language: 编程语言

        Returns:
            参数数量（排除 self/cls/this 等隐式参数）
        """
        param_list_type = _PARAM_LIST_TYPES.get(language, "parameters")
        param_node_types = _PARAM_NODE_TYPES.get(
            language, _PARAM_NODE_TYPES["python"]
        )
        implicit = _IMPLICIT_PARAMS.get(language, set())

        count = 0
        for child in func_node.children:
            if child.type == param_list_type:
                for param in child.children:
                    if param.type in param_node_types:
                        param_name = param.text.decode("utf-8") if param.text else ""
                        # Handle default parameters: "x=1" -> "x"
                        if "=" in param_name:
                            param_name = param_name.split("=")[0].strip()
                        param_name = param_name.split(":")[0].strip()
                        if param_name not in implicit:
                            count += 1
                break
        return count

    def _ast_smell_detection(self, parsed_file: ParsedFile) -> list[dict]:
        """通过 Tree-sitter 检测代码坏味道（多语言支持）。

        当前检测：
        - 过多参数（>5 个）
        - 过长函数（>100 行）

        Args:
            parsed_file: 已解析的文件

        Returns:
            坏味道问题列表
        """
        issues: list[dict] = []

        if parsed_file.tree is None:
            return issues

        language = parsed_file.language
        root = parsed_file.tree.root_node
        func_node_types = _FUNC_NODE_TYPES.get(
            language, _FUNC_NODE_TYPES["python"]
        )

        def check_node(node):
            if node.type in func_node_types:
                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1
                func_lines = end_line - start_line + 1
                func_name = self._get_func_name(node, language)
                param_count = self._count_params(node, language)

                # 检测参数过多（>5）
                if param_count > 5:
                    severity = "high" if param_count > 8 else "medium"
                    issues.append({
                        "agent_type": self.agent_type,
                        "severity": severity,
                        "file_path": parsed_file.path,
                        "line_start": start_line,
                        "line_end": end_line,
                        "category": "too_many_params",
                        "title": (
                            f"[{language}] 函数 '{func_name}' 参数过多 "
                            f"({param_count} 个参数)"
                        ),
                        "description": (
                            f"函数 '{func_name}' 接收 {param_count} 个参数，"
                            f"超过推荐的 5 个上限。"
                            f"过多参数使函数难以理解、调用和测试。"
                        ),
                        "suggestion": (
                            f"重构建议：\n"
                            f"1) 将相关参数封装为数据类/struct；\n"
                            f"2) 使用构建器模式（Builder Pattern）分步设置；\n"
                            f"3) 检查是否可以拆分为多个职责更单一的函数。"
                        ),
                        "code_snippet": node.text.decode("utf-8")[:500],
                    })

                # 检测超长函数（>100 行）
                if func_lines > 100:
                    issues.append({
                        "agent_type": self.agent_type,
                        "severity": "high",
                        "file_path": parsed_file.path,
                        "line_start": start_line,
                        "line_end": end_line,
                        "category": "long_function",
                        "title": f"[{language}] 函数 '{func_name}' 过长 ({func_lines} 行)",
                        "description": (
                            f"函数 '{func_name}' 包含 {func_lines} 行代码，"
                            f"远超推荐的 20-30 行上限。超长函数难以理解和维护，"
                            f"通常是多个职责混杂的标志。"
                        ),
                        "suggestion": (
                            "重构建议：\n"
                            "1) 使用提取方法（Extract Method）将逻辑拆分为小函数；\n"
                            "2) 每个函数只做一件事（Single Responsibility）；\n"
                            "3) 使用组合方法模式（Composed Method）保持同一抽象层级。"
                        ),
                        "code_snippet": node.text.decode("utf-8")[:500],
                    })

        self._walk(root, check_node)
        return issues

    # ---- LLM 重构建议 ----

    async def _llm_refactor_advice(self, parsed_file: ParsedFile) -> list[dict]:
        """使用推理模型（GLM-5.2）生成重构方案。

        检测代码重复、上帝类、数据泥团、特性依恋、Switch 语句等
        AST 分析难以检测的坏味道。

        Args:
            parsed_file: 已解析的文件

        Returns:
            LLM 发现的重构问题列表
        """
        content = parsed_file.content
        language = parsed_file.language

        if len(content) > 12000:
            content = content[:12000] + "\n# ... (truncated)"

        try:
            response = await self._llm_analyze(
                prompt=(
                    f"{REFACTOR_PROMPT}\n\n"
                    f"Analyze the following {language} file for code smells. "
                    f"Provide BEFORE/AFTER code examples for each suggestion. "
                    f"Focus on: duplicate code, god classes, data clumps, "
                    f"feature envy, switch statement abuse, divergent change, "
                    f"shotgun surgery, and excessive comments.\n\n"
                    f"File: {parsed_file.path}"
                ),
                code_context=content,
                use_reasoning=True,  # 使用 GLM-5.2 推理
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

        except Exception as e:
            # LLM 失败时静默跳过，避免在问题列表中产生 llm_error 噪声
            print(f"[RefactorAdvisor] LLM 分析失败，已跳过: {e}")
            return []

    # ---- 主 entry point ----

    async def review(self, parsed_files: list[ParsedFile]) -> list[dict]:
        """执行重构建议分析。

        两步策略：
        1. AST 坏味道检测（精确，无需 LLM）
        2. LLM 重构方案生成（GLM-5.2 推理，含代码示例）

        Args:
            parsed_files: ASTEngine 解析后的文件列表

        Returns:
            所有重构建议的列表
        """
        all_issues: list[dict] = []

        for pf in parsed_files:
            # 仅审查支持的语言
            if pf.language not in SUPPORTED_LANGUAGES:
                continue

            # 步骤 1: AST 坏味道检测
            ast_issues = self._ast_smell_detection(pf)
            all_issues.extend(ast_issues)

            # 步骤 2: LLM 重构建议
            llm_issues = await self._llm_refactor_advice(pf)
            all_issues.extend(llm_issues)

        return all_issues
