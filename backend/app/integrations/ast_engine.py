"""
AST 解析引擎集成

基于 Tree-sitter 的多语言代码解析引擎。
- 第一阶段仅支持 Python，后续扩展 Go/TS/JS/Java。
- 提供 ParsedFile 和 CodeIssue 数据结构。
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ============================================================
# Data Structures
# ============================================================

@dataclass
class CodeIssue:
    """代码审查发现的问题。"""

    file_path: str
    line_start: int
    line_end: int
    severity: str  # critical/high/medium/low/info
    category: str
    title: str
    description: str = ""
    suggestion: str = ""
    code_snippet: str = ""


@dataclass
class ParsedFile:
    """已解析的代码文件。"""

    path: str
    content: str
    language: str
    tree: Any | None = None  # tree_sitter.Tree
    issues: list[CodeIssue] = field(default_factory=list)


# ============================================================
# Language Support
# ============================================================

SUPPORTED_LANGUAGES: dict[str, str] = {
    "python": "python",
}

# 文件扩展名 → 语言名映射
_EXTENSION_MAP: dict[str, str] = {
    ".py": "python",
    ".go": "go",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".java": "java",
}


def detect_language(file_path: str | Path) -> str:
    """根据文件扩展名推断编程语言。

    Args:
        file_path: 文件路径

    Returns:
        语言名 (python/go/typescript/javascript/java)，未知则返回 "unknown"
    """
    ext = Path(file_path).suffix.lower()
    return _EXTENSION_MAP.get(ext, "unknown")


# ============================================================
# AST Engine
# ============================================================


class ASTEngine:
    """Tree-sitter AST 解析引擎。

    维护解析器缓存，避免重复创建 Tree-sitter Language 对象。
    第一阶段仅支持 Python。

    Usage:
        engine = ASTEngine()
        parsed = engine.parse(code, "example.py")
        for issue in parsed.issues:
            print(issue.title)
    """

    def __init__(self):
        self._parsers: dict[str, Any] = {}  # language -> Parser

    def _get_parser(self, language: str):
        """获取或缓存 Tree-sitter Parser。

        Args:
            language: 语言名（仅 'python' 在第一阶段被支持）

        Returns:
            tree_sitter.Parser 实例
        """
        if language not in self._parsers:
            if language == "python":
                try:
                    import tree_sitter_python as tspy
                    import tree_sitter
                except ImportError:
                    raise ImportError(
                        "tree-sitter-python 未安装，请运行: pip install tree-sitter-python"
                    )
                parser = tree_sitter.Parser()
                py_lang = tree_sitter.Language(tspy.language())
                parser.set_language(py_lang)
                self._parsers[language] = parser
            else:
                raise ValueError(
                    f"不支持的语言: {language}。当前仅支持: python"
                )
        return self._parsers[language]

    def parse(
        self,
        code: str,
        file_path: str | Path = "<string>",
        language: str | None = None,
    ) -> ParsedFile:
        """解析代码字符串，返回 ParsedFile 对象。

        Args:
            code: 源代码文本
            file_path: 文件路径（用于问题定位和语言推断）
            language: 语言名，为 None 时从 file_path 推断

        Returns:
            ParsedFile 对象，包含 AST 树和解析期间发现的基础问题
        """
        file_path = str(file_path)

        if language is None:
            language = detect_language(file_path)

        if language not in SUPPORTED_LANGUAGES:
            # 不支持的语言仍返回 ParsedFile，但 tree 为 None
            return ParsedFile(
                path=file_path,
                content=code,
                language=language,
                tree=None,
            )

        parser = self._get_parser(language)
        tree = parser.parse(code.encode("utf-8"))

        return ParsedFile(
            path=file_path,
            content=code,
            language=language,
            tree=tree,
        )
