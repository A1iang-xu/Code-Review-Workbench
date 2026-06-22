"""
ASTScanSkill

基于 Tree-sitter 的 AST 结构化扫描 Skill。
统计函数/类数量、嵌套深度、超长函数检测。
"""

from typing import Any

from app.core.skills.registry import BaseSkill, SkillCategory, SkillMetadata, SkillResult


class ASTScanSkill(BaseSkill):
    """AST 结构化扫描 Skill。

    使用 Tree-sitter 遍历 AST，统计：
    - 函数和类数量
    - 最大嵌套深度
    - 超长函数（>100 行）列表
    """

    metadata = SkillMetadata(
        name="ast_scan",
        display_name="AST 结构化扫描",
        version="1.0.0",
        category=SkillCategory.STATIC_ANALYSIS,
        description="基于 Tree-sitter 的 AST 统计：函数/类计数、嵌套深度、超长函数检测",
        author="Code Review Workbench",
        languages=["python"],
        tags=["ast", "static-analysis", "metrics"],
    )

    async def execute(
        self,
        code: str,
        file_path: str = "<string>",
        context: dict[str, Any] | None = None,
    ) -> SkillResult:
        """执行 AST 扫描。

        Args:
            code: 源代码文本
            file_path: 文件路径
            context: 可选的上下文（可包含 tree 对象）

        Returns:
            SkillResult 包含扫描统计结果
        """
        # 尝试从上下文获取已有的 tree
        tree = None
        if context and "tree" in context:
            tree = context["tree"]

        # 如果没有 tree，尝试解析
        if tree is None:
            try:
                import tree_sitter
                import tree_sitter_python as tspy
            except ImportError:
                return SkillResult(
                    success=False,
                    summary="tree-sitter 或 tree-sitter-python 未安装",
                )

            parser = tree_sitter.Parser()
            py_lang = tree_sitter.Language(tspy.language())
            parser.set_language(py_lang)
            tree = parser.parse(code.encode("utf-8"))

        if tree is None:
            return SkillResult(
                success=False,
                summary="无法解析代码",
            )

        root = tree.root_node

        # --- 统计 ---
        stats = {
            "total_lines": len(code.split("\n")),
            "functions": 0,
            "methods": 0,
            "classes": 0,
            "max_nesting_depth": 0,
            "long_functions": [],  # >100 行
        }

        def walk(node, depth=0):
            nonlocal stats

            if node.type == "function_definition":
                stats["functions"] += 1
                func_lines = node.end_point[0] - node.start_point[0] + 1
                if func_lines > 100:
                    # 提取函数名
                    func_name = "<unknown>"
                    for child in node.children:
                        if child.type == "identifier":
                            func_name = child.text.decode("utf-8")
                            break
                    stats["long_functions"].append({
                        "name": func_name,
                        "lines": func_lines,
                        "line_start": node.start_point[0] + 1,
                        "line_end": node.end_point[0] + 1,
                    })

            elif node.type in ("class_definition", "decorated_definition"):
                stats["classes"] += 1

            stats["max_nesting_depth"] = max(stats["max_nesting_depth"], depth)

            for child in node.children:
                if child.type in ("function_definition", "method_definition", "class_definition",
                                  "if_statement", "for_statement", "while_statement",
                                  "try_statement", "with_statement", "match_statement"):
                    walk(child, depth + 1)
                else:
                    walk(child, depth)

        walk(root)

        # 构建 summary
        parts = [
            f"文件: {file_path}",
            f"总行数: {stats['total_lines']}",
            f"函数: {stats['functions']}, 方法: {stats['methods']}, 类: {stats['classes']}",
            f"最大嵌套深度: {stats['max_nesting_depth']}",
        ]
        if stats["long_functions"]:
            parts.append(f"超长函数 (>100 行): {len(stats['long_functions'])} 个")
            for lf in stats["long_functions"]:
                parts.append(
                    f"  - {lf['name']} (L{lf['line_start']}-{lf['line_end']}, {lf['lines']} 行)"
                )

        return SkillResult(
            success=True,
            findings=stats["long_functions"],
            summary="\n".join(parts),
            raw_output=str(stats),
        )


# Skill 实例（供 SkillLoader 导入）
skill = ASTScanSkill()
