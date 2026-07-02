"""
ComplexityCheckSkill

圈复杂度检查 Skill — 基于 Tree-sitter AST 计算函数复杂度。
支持 Python、Go、TypeScript、JavaScript、Java。
"""

import os
from typing import Any

from app.core.skills.registry import BaseSkill, SkillCategory, SkillMetadata, SkillResult


# 各语言分支节点类型
_BRANCH_NODES = {
    "python": {"if_statement", "elif_clause", "for_statement", "while_statement",
                "try_statement", "except_clause", "match_statement", "case_clause",
                "boolean_operator", "conditional_expression"},
    "go": {"if_statement", "for_statement", "switch_statement", "case_clause",
           "select_statement", "binary_expression"},
    "typescript": {"if_statement", "for_statement", "while_statement", "switch_case",
                    "try_statement", "catch_clause", "conditional_expression",
                    "binary_expression"},
    "javascript": {"if_statement", "for_statement", "while_statement", "switch_case",
                    "try_statement", "catch_clause", "conditional_expression",
                    "binary_expression"},
    "java": {"if_statement", "for_statement", "while_statement", "switch_case",
             "catch_clause", "conditional_expression", "binary_expression"},
}

_FUNC_NODES = {
    "python": ("function_definition",),
    "go": ("function_declaration", "method_declaration"),
    "typescript": ("function_declaration", "method_definition", "arrow_function"),
    "javascript": ("function_declaration", "method_definition", "arrow_function"),
    "java": ("method_declaration", "constructor_declaration"),
}

_EXT_TO_LANG = {
    ".py": "python", ".go": "go", ".ts": "typescript",
    ".tsx": "typescript", ".js": "javascript", ".jsx": "javascript", ".java": "java",
}


class ComplexityCheckSkill(BaseSkill):
    """圈复杂度检查 Skill。

    使用 Tree-sitter 解析 AST，计算每个函数的圈复杂度。
    阈值: >20 critical, >10 high, >5 medium。
    """

    metadata = SkillMetadata(
        name="complexity_check",
        display_name="圈复杂度检查",
        version="1.0.0",
        category=SkillCategory.STATIC_ANALYSIS,
        description="基于 AST 计算函数圈复杂度，识别高复杂度函数",
        author="Code Review Workbench",
        languages=["python", "go", "typescript", "javascript", "java"],
        tags=["complexity", "static-analysis", "maintainability"],
    )

    async def execute(
        self,
        code: str,
        file_path: str = "<string>",
        context: dict[str, Any] | None = None,
    ) -> SkillResult:
        """执行圈复杂度检查。"""
        # 确定语言
        ext = os.path.splitext(file_path)[1].lower()
        language = _EXT_TO_LANG.get(ext, "python")

        # 解析 AST
        tree = context.get("tree") if context else None
        if tree is None:
            tree = self._parse(code, language)
            if tree is None:
                return SkillResult(
                    success=False,
                    summary=f"无法解析 {language} 代码（tree-sitter 语言未安装）",
                )

        root = tree.root_node
        func_types = _FUNC_NODES.get(language, _FUNC_NODES["python"])
        branch_types = _BRANCH_NODES.get(language, _BRANCH_NODES["python"])

        findings: list[dict] = []
        self._walk_functions(root, func_types, branch_types, file_path, language, findings)

        severity_counts: dict[str, int] = {}
        for f in findings:
            sev = f["severity"]
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        summary_parts = [f"复杂度检查完成: {len(findings)} 个高复杂度函数"]
        for sev in ("critical", "high", "medium"):
            if sev in severity_counts:
                summary_parts.append(f"  {sev}: {severity_counts[sev]}")

        return SkillResult(
            success=True,
            findings=findings,
            summary="\n".join(summary_parts),
        )

    def _parse(self, code: str, language: str):
        """解析代码为 AST。"""
        try:
            import tree_sitter
            lang_modules = {
                "python": "tree_sitter_python",
                "go": "tree_sitter_go",
                "typescript": "tree_sitter_typescript",
                "javascript": "tree_sitter_javascript",
                "java": "tree_sitter_java",
            }
            mod_name = lang_modules.get(language)
            if not mod_name:
                return None
            mod = __import__(mod_name)
            lang = tree_sitter.Language(mod.language())
            parser = tree_sitter.Parser(lang)
            return parser.parse(code.encode("utf-8"))
        except ImportError:
            return None

    def _walk_functions(self, node, func_types, branch_types, file_path, language, findings):
        """递归遍历 AST，查找函数并计算复杂度。"""
        if node.type in func_types:
            complexity = self._count_branches(node, branch_types)
            if complexity > 5:
                func_name = self._get_name(node, language)
                sev = "critical" if complexity > 20 else "high" if complexity > 10 else "medium"
                findings.append({
                    "skill": "complexity_check",
                    "severity": sev,
                    "file_path": file_path,
                    "line_start": node.start_point[0] + 1,
                    "line_end": node.end_point[0] + 1,
                    "category": "cyclomatic_complexity",
                    "title": f"函数 '{func_name}' 圈复杂度过高 ({complexity})",
                    "description": f"圈复杂度 {complexity}，推荐 <= 10",
                    "suggestion": "提取条件分支到独立函数，使用策略模式替代 if-elif 链",
                })

        for child in node.children:
            self._walk_functions(child, func_types, branch_types, file_path, language, findings)

    @staticmethod
    def _count_branches(node, branch_types) -> int:
        """统计分支节点数。"""
        count = 0
        def walk(n):
            nonlocal count
            if n.type in branch_types:
                count += 1
            for c in n.children:
                walk(c)
        walk(node)
        return 1 + count

    @staticmethod
    def _get_name(node, language: str) -> str:
        """提取函数名。"""
        for child in node.children:
            if child.type == "identifier":
                return child.text.decode("utf-8")
        return "<unknown>"


# Skill 实例（供 SkillLoader 导入）
skill = ComplexityCheckSkill()
