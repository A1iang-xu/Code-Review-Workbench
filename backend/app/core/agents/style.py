"""
StyleChecker Agent

代码风格审查 Agent，分为两步：
1. AST 静态分析：检测函数长度（>50 行）、参数过多等问题
2. LLM 分析：使用本地模型（Qwen2.5-7B）检查命名规范、注释质量、
   代码重复、导入顺序等
"""

import json
import re

from app.core.agents.base import AgentContext, BaseReviewAgent
from app.integrations.ast_engine import CodeIssue, ParsedFile


class StyleCheckerAgent(BaseReviewAgent):
    """代码风格审查 Agent。

    使用 AST 做结构化检查 + LLM 做语义级检查。
    使用本地 Qwen2.5-7B 模型（零成本、数据不出本机）。
    """

    agent_type = "style"
    display_name = "风格检查Agent"

    # ---- AST 静态分析 ----

    def _walk(self, node, callback):
        """递归遍历 AST 节点树。

        Args:
            node: 当前 Tree-sitter 节点
            callback: 每个节点调用的回调函数
        """
        callback(node)
        for child in node.children:
            self._walk(child, callback)

    def _get_func_name(self, node) -> str:
        """从函数/方法定义的 AST 节点提取函数名。

        Args:
            node: function_definition 或 decorated_definition 节点

        Returns:
            函数名，提取失败返回 "<unknown>"
        """
        # Tree-sitter Python grammar:
        # function_definition: 'def' name parameters (':' body | '->' type ':')
        for child in node.children:
            if child.type == "def":
                continue  # 'def' 关键字
            if child.type == "identifier":
                return child.text.decode("utf-8")
            # 对于 decorated_definition，递归查找
            if child.type == "function_definition":
                return self._get_func_name(child)
        return "<unknown>"

    def _ast_analyze(self, parsed_file: ParsedFile) -> list[dict]:
        """AST 静态分析：检查函数长度。

        Args:
            parsed_file: 已解析的文件

        Returns:
            问题列表
        """
        issues: list[dict] = []

        if parsed_file.tree is None:
            return issues

        root = parsed_file.tree.root_node

        def check_node(node):
            if node.type in ("function_definition", "method_definition"):
                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1
                func_lines = end_line - start_line + 1
                func_name = self._get_func_name(node)

                if func_lines > 50:
                    issues.append({
                        "agent_type": self.agent_type,
                        "severity": "medium",
                        "file_path": parsed_file.path,
                        "line_start": start_line,
                        "line_end": end_line,
                        "category": "function_length",
                        "title": f"函数 '{func_name}' 过长 ({func_lines} 行)",
                        "description": (
                            f"函数 '{func_name}' 包含 {func_lines} 行代码，"
                            f"超过推荐的 50 行上限。长函数难以理解和测试。"
                        ),
                        "suggestion": (
                            "建议将长函数拆分为多个职责单一的小函数。"
                            "每个函数应只做一件事。考虑提取子逻辑到独立的辅助函数中。"
                        ),
                        "code_snippet": node.text.decode("utf-8")[:500],
                    })

        self._walk(root, check_node)
        return issues

    # ---- LLM 分析 ----

    async def _llm_analyze_code(self, parsed_file: ParsedFile) -> list[dict]:
        """使用 LLM（本地 Qwen2.5-7B）检查代码风格问题。

        检查项：命名规范、注释质量、代码重复、导入顺序。

        Args:
            parsed_file: 已解析的文件

        Returns:
            问题列表
        """
        prompt = """Analyze the following Python code for style issues. Check for:

1. Naming conventions: Are variables, functions, and classes using proper Python naming (snake_case for functions/variables, PascalCase for classes)?
2. Comment quality: Are there missing docstrings for functions and classes? Are comments meaningful?
3. Code duplication: Any repeated code blocks?
4. Import order: Are imports properly grouped (stdlib -> third-party -> local)?

Return ONLY a JSON array of findings. Each finding must be:
{
    "severity": "low|medium|high",
    "category": "naming|comment|duplication|import_order|other",
    "title": "brief title",
    "description": "detailed explanation",
    "suggestion": "how to fix"
}

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
        1. 对所有 Python 文件执行 AST 静态分析（函数长度检查）
        2. 对每个文件执行 LLM 语义分析（命名/注释/重复/导入）

        Args:
            parsed_files: ASTEngine 解析后的文件列表

        Returns:
            所有发现的问题列表
        """
        all_issues: list[dict] = []

        for pf in parsed_files:
            if pf.language != "python":
                continue

            # 步骤 1: AST 静态分析
            ast_issues = self._ast_analyze(pf)
            all_issues.extend(ast_issues)

            # 步骤 2: LLM 语义分析
            llm_issues = await self._llm_analyze_code(pf)
            all_issues.extend(llm_issues)

        return all_issues
