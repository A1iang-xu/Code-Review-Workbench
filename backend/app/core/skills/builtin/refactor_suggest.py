"""
RefactorSuggestSkill

重构建议 Skill — 基于 AST 检测代码坏味道。
检测过长函数、过多参数、深层嵌套等问题。
支持 Python、Go、TypeScript/JavaScript、Java。
"""

import os
from typing import Any

from app.core.skills.registry import BaseSkill, SkillCategory, SkillMetadata, SkillResult


_FUNC_NODES = {
    "python": ("function_definition",),
    "go": ("function_declaration", "method_declaration"),
    "typescript": ("function_declaration", "method_definition", "arrow_function"),
    "javascript": ("function_declaration", "method_definition", "arrow_function"),
    "java": ("method_declaration", "constructor_declaration"),
}

_NESTING_NODES = {
    "python": {"if_statement", "for_statement", "while_statement", "try_statement", "with_statement"},
    "go": {"if_statement", "for_statement", "switch_statement", "select_statement"},
    "typescript": {"if_statement", "for_statement", "while_statement", "switch_case", "try_statement"},
    "javascript": {"if_statement", "for_statement", "while_statement", "switch_case", "try_statement"},
    "java": {"if_statement", "for_statement", "while_statement", "switch_case", "try_statement"},
}

_EXT_TO_LANG = {
    ".py": "python", ".go": "go", ".ts": "typescript",
    ".tsx": "typescript", ".js": "javascript", ".jsx": "javascript", ".java": "java",
}


class RefactorSuggestSkill(BaseSkill):
    """重构建议 Skill。

    基于 AST 检测代码坏味道：
    - 过长函数（>100 行）
    - 过多参数（>5 个）
    - 深层嵌套（>4 层）
    """

    metadata = SkillMetadata(
        name="refactor_suggest",
        display_name="重构建议",
        version="1.0.0",
        category=SkillCategory.STATIC_ANALYSIS,
        description="检测过长函数、过多参数、深层嵌套等代码坏味道",
        author="Code Review Workbench",
        languages=["python", "go", "typescript", "javascript", "java"],
        tags=["refactor", "code-smell", "maintainability"],
    )

    async def execute(
        self,
        code: str,
        file_path: str = "<string>",
        context: dict[str, Any] | None = None,
    ) -> SkillResult:
        """执行重构建议检测。"""
        ext = os.path.splitext(file_path)[1].lower()
        language = _EXT_TO_LANG.get(ext, "python")

        tree = context.get("tree") if context else None
        if tree is None:
            tree = self._parse(code, language)
            if tree is None:
                return SkillResult(
                    success=False,
                    summary=f"无法解析 {language} 代码",
                )

        root = tree.root_node
        func_types = _FUNC_NODES.get(language, _FUNC_NODES["python"])
        nesting_types = _NESTING_NODES.get(language, _NESTING_NODES["python"])

        findings: list[dict] = []
        self._walk(root, func_types, nesting_types, file_path, language, findings, 0)

        summary = f"重构建议检测完成: {len(findings)} 个坏味道"
        return SkillResult(
            success=True,
            findings=findings,
            summary=summary,
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

    def _walk(self, node, func_types, nesting_types, file_path, language, findings, depth):
        """递归遍历 AST。"""
        if node.type in func_types:
            self._check_function(node, file_path, language, findings, nesting_types)

        # 检查深层嵌套
        if node.type in nesting_types:
            depth += 1
            if depth > 4:
                findings.append({
                    "skill": "refactor_suggest",
                    "severity": "medium",
                    "file_path": file_path,
                    "line_start": node.start_point[0] + 1,
                    "line_end": node.end_point[0] + 1,
                    "category": "deep_nesting",
                    "title": f"深层嵌套 ({depth} 层)",
                    "description": f"第 {node.start_point[0] + 1} 行嵌套深度 {depth}，超过 4 层",
                    "suggestion": "使用 Guard Clause 提前返回，减少嵌套层级",
                })

        for child in node.children:
            self._walk(child, func_types, nesting_types, file_path, language, findings, depth)

    def _check_function(self, node, file_path, language, findings, nesting_types):
        """检查单个函数的坏味道。"""
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        func_lines = end_line - start_line + 1
        func_name = self._get_name(node, language)

        # 过长函数
        if func_lines > 100:
            findings.append({
                "skill": "refactor_suggest",
                "severity": "high",
                "file_path": file_path,
                "line_start": start_line,
                "line_end": end_line,
                "category": "long_function",
                "title": f"函数 '{func_name}' 过长 ({func_lines} 行)",
                "description": f"函数 {func_name} 包含 {func_lines} 行，超过 100 行上限",
                "suggestion": "使用提取方法（Extract Method）拆分为多个小函数",
            })

        # 过多参数
        param_count = self._count_params(node, language)
        if param_count > 5:
            sev = "high" if param_count > 8 else "medium"
            findings.append({
                "skill": "refactor_suggest",
                "severity": sev,
                "file_path": file_path,
                "line_start": start_line,
                "line_end": end_line,
                "category": "too_many_params",
                "title": f"函数 '{func_name}' 参数过多 ({param_count} 个)",
                "description": f"函数 {func_name} 接收 {param_count} 个参数，超过 5 个上限",
                "suggestion": "将相关参数封装为数据类/struct",
            })

    @staticmethod
    def _get_name(node, language: str) -> str:
        for child in node.children:
            if child.type == "identifier":
                return child.text.decode("utf-8")
        return "<unknown>"

    @staticmethod
    def _count_params(node, language: str) -> int:
        """统计参数数量。"""
        param_list_types = {
            "python": "parameters",
            "go": "parameter_list",
            "typescript": "formal_parameters",
            "javascript": "formal_parameters",
            "java": "formal_parameters",
        }
        param_list_type = param_list_types.get(language, "parameters")
        for child in node.children:
            if child.type == param_list_type:
                return len([c for c in child.children if c.is_named])
        return 0


# Skill 实例（供 SkillLoader 导入）
skill = RefactorSuggestSkill()
