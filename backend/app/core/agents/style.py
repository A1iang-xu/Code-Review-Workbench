"""
StyleChecker Agent

代码风格审查 Agent，分为两步：
1. AST 静态分析：检测函数长度、参数过多等问题（支持多语言）
2. LLM 分析：使用本地模型检查命名规范、注释质量、代码重复、导入顺序等

阶段四：支持多语言（Python / Go / TypeScript / JavaScript / Java）
"""

import json
import re

from app.core.agents.base import AgentContext, BaseReviewAgent
from app.integrations.ast_engine import CodeIssue, ParsedFile


# ============================================================
# 多语言风格规则配置
# ============================================================

LANGUAGE_STYLE_RULES: dict[str, dict] = {
    "python": {
        "name": "Python",
        "style_guide": "PEP 8",
        "max_func_lines": 50,
        "max_params": 5,
        "linter": "ruff",
        "indent": 4,
        "naming": {
            "function": "snake_case",
            "class": "PascalCase",
            "variable": "snake_case",
            "constant": "UPPER_SNAKE_CASE",
        },
        "prompt_suffix": (
            "\nLanguage: Python\n"
            "Follow PEP 8 style guide.\n"
            "Check for: snake_case functions/variables, PascalCase classes, "
            "UPPER_SNAKE_CASE constants, docstrings, type hints, "
            "import order (stdlib → third-party → local), "
            "line length <= 100, meaningful variable names."
        ),
    },
    "go": {
        "name": "Go",
        "style_guide": "Effective Go",
        "max_func_lines": 80,
        "max_params": 5,
        "linter": "golangci-lint",
        "indent": 1,  # tabs
        "naming": {
            "function": "camelCase / PascalCase (exported)",
            "class": "N/A (structs use PascalCase for exported)",
            "variable": "camelCase",
            "constant": "PascalCase (exported) / camelCase (unexported)",
        },
        "prompt_suffix": (
            "\nLanguage: Go\n"
            "Follow Effective Go style guide.\n"
            "Check for: proper error handling, idiomatic Go patterns, "
            "descriptive variable names (short names ok for local scope), "
            "package organization, interface naming (single-method: -er suffix), "
            "no stuttering (package.DoSomething not package.DoPackageSomething)."
        ),
    },
    "typescript": {
        "name": "TypeScript",
        "style_guide": "ESLint recommended + Prettier",
        "max_func_lines": 60,
        "max_params": 4,
        "linter": "eslint",
        "indent": 2,
        "naming": {
            "function": "camelCase",
            "class": "PascalCase",
            "variable": "camelCase",
            "constant": "UPPER_SNAKE_CASE",
            "interface": "PascalCase (no I-prefix)",
            "type": "PascalCase",
        },
        "prompt_suffix": (
            "\nLanguage: TypeScript\n"
            "Follow ESLint recommended rules.\n"
            "Check for: proper TypeScript types (avoid 'any'), "
            "interface naming (no I-prefix), const assertions, "
            "proper use of async/await, no unused variables, "
            "consistent code formatting, meaningful JSDoc comments."
        ),
    },
    "javascript": {
        "name": "JavaScript",
        "style_guide": "Airbnb",
        "max_func_lines": 50,
        "max_params": 4,
        "linter": "eslint",
        "indent": 2,
        "naming": {
            "function": "camelCase",
            "class": "PascalCase",
            "variable": "camelCase",
            "constant": "UPPER_SNAKE_CASE",
        },
        "prompt_suffix": (
            "\nLanguage: JavaScript\n"
            "Follow Airbnb JavaScript Style Guide.\n"
            "Check for: consistent naming (camelCase for variables/functions, "
            "PascalCase for classes/constructors), JSDoc comments, "
            "proper error handling, no console.log in production code, "
            "use of const/let over var, meaningful variable names."
        ),
    },
    "java": {
        "name": "Java",
        "style_guide": "Google Java Style",
        "max_func_lines": 60,
        "max_params": 4,
        "linter": "checkstyle",
        "indent": 2,
        "naming": {
            "function": "camelCase",
            "class": "PascalCase",
            "variable": "camelCase",
            "constant": "UPPER_SNAKE_CASE",
            "package": "lowercase",
        },
        "prompt_suffix": (
            "\nLanguage: Java\n"
            "Follow Google Java Style Guide.\n"
            "Check for: camelCase methods/variables, PascalCase classes, "
            "UPPER_SNAKE_CASE constants, meaningful Javadoc, "
            "proper exception handling, no System.out.println in production, "
            "single responsibility principle, meaningful class/package names."
        ),
    },
}


class StyleCheckerAgent(BaseReviewAgent):
    """代码风格审查 Agent。

    使用 AST 做结构化检查 + LLM 做语义级检查。
    支持多语言（Python/Go/TypeScript/JavaScript/Java）。
    使用本地 Qwen2.5-7B 模型（零成本、数据不出本机）。
    """

    agent_type = "style"
    display_name = "风格检查Agent"

    # AST 节点类型映射（按语言）
    _FUNC_NODE_TYPES = {
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

    @staticmethod
    def _get_func_name_ts_style(node, source: bytes) -> str:
        """Extract function name for TS/JS nodes."""
        for child in node.children:
            if child.type == "identifier":
                return child.text.decode("utf-8")
            # For method_definition, it's property_identifier -> identifier
            if child.type == "property_identifier":
                for grandchild in child.children:
                    if grandchild.type == "identifier":
                        return grandchild.text.decode("utf-8")
        return "<unknown>"

    def _get_func_name(self, node, language: str = "python") -> str:
        """从函数/方法定义的 AST 节点提取函数名。

        Args:
            node: Tree-sitter 节点
            language: 编程语言

        Returns:
            函数名，提取失败返回 "<unknown>"
        """
        if language in ("typescript", "javascript"):
            return self._get_func_name_ts_style(
                node, node.text if hasattr(node, 'text') else b""
            )

        source = node.text.decode("utf-8") if hasattr(node, 'text') else ""
        if language == "python":
            for child in node.children:
                if child.type == "def":
                    continue
                if child.type == "identifier":
                    return child.text.decode("utf-8")
                if child.type == "function_definition":
                    return self._get_func_name(child, language)
        elif language == "go":
            for child in node.children:
                if child.type == "identifier":
                    return child.text.decode("utf-8")
        elif language == "java":
            for child in node.children:
                if child.type == "identifier":
                    return child.text.decode("utf-8")

        return "<unknown>"

    # ---- AST 静态分析 ----

    def _ast_analyze(self, parsed_file: ParsedFile) -> list[dict]:
        """AST 静态分析：检查函数长度。

        根据语言选择不同的上限阈值。

        Args:
            parsed_file: 已解析的文件

        Returns:
            问题列表
        """
        issues: list[dict] = []

        if parsed_file.tree is None:
            return issues

        language = parsed_file.language
        rules = LANGUAGE_STYLE_RULES.get(language, LANGUAGE_STYLE_RULES["python"])
        max_func_lines = rules["max_func_lines"]
        func_node_types = self._FUNC_NODE_TYPES.get(
            language, ("function_definition", "method_definition")
        )

        root = parsed_file.tree.root_node

        def check_node(node):
            if node.type in func_node_types:
                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1
                func_lines = end_line - start_line + 1
                func_name = self._get_func_name(node, language)

                if func_lines > max_func_lines:
                    issues.append({
                        "agent_type": self.agent_type,
                        "severity": "medium",
                        "file_path": parsed_file.path,
                        "line_start": start_line,
                        "line_end": end_line,
                        "category": "function_length",
                        "title": (
                            f"[{language}] 函数 '{func_name}' 过长 "
                            f"({func_lines} 行)"
                        ),
                        "description": (
                            f"函数 '{func_name}' 包含 {func_lines} 行代码，"
                            f"超过 {rules['style_guide']} 推荐的 "
                            f"{max_func_lines} 行上限。长函数难以理解和测试。"
                        ),
                        "suggestion": (
                            "建议将长函数拆分为多个职责单一的小函数。"
                            "每个函数应只做一件事。考虑提取子逻辑到独立的辅助函数中。"
                        ),
                        "code_snippet": (
                            node.text.decode("utf-8")[:500]
                            if hasattr(node, 'text') else ""
                        ),
                    })

        self._walk(root, check_node)
        return issues

    # ---- LLM 分析 ----

    async def _llm_analyze_code(self, parsed_file: ParsedFile) -> list[dict]:
        """使用 LLM（本地 Qwen2.5-7B）检查代码风格问题。

        检查项：命名规范、注释质量、代码重复、导入顺序。
        根据语言使用不同的提示词后缀。

        Args:
            parsed_file: 已解析的文件

        Returns:
            问题列表
        """
        language = parsed_file.language
        rules = LANGUAGE_STYLE_RULES.get(language, LANGUAGE_STYLE_RULES["python"])
        prompt_suffix = rules.get("prompt_suffix", "")

        prompt = f"""Analyze the following {language} code for style issues. Check for:

1. Naming conventions: Are variables, functions, and classes using proper naming?
2. Comment quality: Are there missing docstrings/comments for functions and classes? Are comments meaningful?
3. Code duplication: Any repeated code blocks?
4. Code organization: Is the code well-structured and readable?

{prompt_suffix}

Return ONLY a JSON array of findings. Each finding must be:
{{
    "severity": "low|medium|high",
    "category": "naming|comment|duplication|organization|other",
    "line_start": <line number or 0>,
    "line_end": <line number or 0>,
    "title": "brief title",
    "description": "detailed explanation",
    "suggestion": "how to fix"
}}

If no issues found, return [].

Code to analyze:"""

        try:
            response = await self._llm_analyze(
                prompt=prompt,
                code_context=parsed_file.content[:8000],  # 限制长度
                use_reasoning=False,  # 使用本地 Qwen2.5-7B
            )

            # 尝试提取 JSON 数组
            json_match = re.search(r"\[.*\]", response, re.DOTALL)
            if json_match:
                findings = json.loads(json_match.group(0))
            else:
                findings = []

            # 添加文件路径信息
            for f in findings:
                f["agent_type"] = self.agent_type
                f["file_path"] = parsed_file.path
                f["line_start"] = f.get("line_start", 0)
                f["line_end"] = f.get("line_end", 0)
                f["code_snippet"] = ""

            return findings

        except (json.JSONDecodeError, Exception) as e:
            # LLM 调用失败时不中断流水线
            return [{
                "agent_type": self.agent_type,
                "severity": "info",
                "file_path": parsed_file.path,
                "line_start": 0,
                "line_end": 0,
                "category": "llm_error",
                "title": f"LLM 分析失败: {str(e)[:100]}",
                "description": "本地模型调用失败，仅完成 AST 静态分析",
                "suggestion": "请检查 Ollama 模型是否已部署",
                "code_snippet": "",
            }]

    # ---- 主 entry point ----

    async def review(self, parsed_files: list[ParsedFile]) -> list[dict]:
        """执行风格审查。

        分两步：
        1. 对所有文件执行 AST 静态分析（函数长度检查，多语言支持）
        2. 对每个文件执行 LLM 语义分析（命名/注释/重复/组织）

        根据 context.language 过滤文件，context.language="auto" 时审查所有文件。

        Args:
            parsed_files: ASTEngine 解析后的文件列表

        Returns:
            所有发现的问题列表
        """
        all_issues: list[dict] = []

        target_lang = self.context.language

        for pf in parsed_files:
            # 如果指定了具体语言，仅审查该语言的文件
            if target_lang and target_lang != "auto" and pf.language != target_lang:
                continue

            # 步骤 1: AST 静态分析
            ast_issues = self._ast_analyze(pf)
            all_issues.extend(ast_issues)

            # 步骤 2: LLM 语义分析
            llm_issues = await self._llm_analyze_code(pf)
            all_issues.extend(llm_issues)

        return all_issues
