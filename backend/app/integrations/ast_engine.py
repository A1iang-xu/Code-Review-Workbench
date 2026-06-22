"""
AST 解析引擎集成

基于 Tree-sitter 的多语言代码解析引擎。
- 支持 Python / Go / TypeScript / JavaScript / Java。
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

# 语言名 → Tree-sitter language module attribute name
SUPPORTED_LANGUAGES: dict[str, str] = {
    "python": "python",
    "go": "go",
    "typescript": "typescript",
    "javascript": "javascript",
    "java": "java",
}

# Tree-sitter 包名 → 语言名映射（用于懒加载）
_LANGUAGE_PACKAGES: dict[str, str] = {
    "python": "tree_sitter_python",
    "go": "tree_sitter_go",
    "typescript": "tree_sitter_typescript",
    "javascript": "tree_sitter_javascript",
    "java": "tree_sitter_java",
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
        self._languages: dict[str, Any] = {}  # language -> tree_sitter.Language object

    @staticmethod
    def _load_language_module(language: str) -> Any:
        """Dynamically load a tree-sitter language package.

        Uses a mapping from language name to Python package name.

        Args:
            language: Language name (python/go/typescript/javascript/java).

        Returns:
            The loaded language module.

        Raises:
            ImportError: If the tree-sitter package for the language is not installed.
        """
        pkg_name = _LANGUAGE_PACKAGES.get(language)
        if pkg_name is None:
            raise ValueError(f"Unsupported language: {language}")

        try:
            import importlib
            return importlib.import_module(pkg_name)
        except ImportError:
            raise ImportError(
                f"tree-sitter {language} parser 未安装，请运行: pip install {pkg_name}"
            )

    def _get_language(self, language: str) -> Any:
        """Get or cache a tree-sitter Language object for the given language.

        Args:
            language: Language name.

        Returns:
            tree_sitter.Language instance.
        """
        if language not in self._languages:
            import tree_sitter
            mod = self._load_language_module(language)
            # tree-sitter packages expose .language() as a function returning bytes/object
            self._languages[language] = tree_sitter.Language(mod.language())
        return self._languages[language]

    def _get_parser(self, language: str):
        """Get or cache a tree-sitter Parser for the given language.

        Args:
            language: Language name (python/go/typescript/javascript/java).

        Returns:
            tree_sitter.Parser instance, set to parse the given language.

        Raises:
            ImportError: If the tree-sitter package for the language is not installed.
            ValueError: If the language is not in SUPPORTED_LANGUAGES.
        """
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"不支持的语言: {language}。当前支持: {', '.join(SUPPORTED_LANGUAGES.keys())}"
            )

        if language not in self._parsers:
            import tree_sitter
            parser = tree_sitter.Parser()
            ts_lang = self._get_language(language)
            parser.set_language(ts_lang)
            self._parsers[language] = parser

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
