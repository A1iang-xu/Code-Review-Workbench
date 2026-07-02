"""
Semantic Chunker

基于 Tree-sitter AST 的代码语义分块器。
按函数/类边界分块，保留代码语义完整性，避免在函数中间截断。
"""

from typing import Any


class ChunkInfo:
    """代码块信息。"""

    def __init__(
        self,
        content: str,
        start_line: int,
        end_line: int,
        symbols: list[str] | None = None,
    ):
        self.content = content
        self.start_line = start_line
        self.end_line = end_line
        self.symbols = symbols or []

    def __repr__(self) -> str:
        return (
            f"ChunkInfo(lines={self.start_line}-{self.end_line}, "
            f"symbols={self.symbols}, chars={len(self.content)})"
        )


class SemanticChunker:
    """AST 语义分块器。

    按函数/类边界拆分代码，每块不超过 max_chunk_tokens。
    记录每个块的符号列表（函数名/类名）。

    Usage:
        chunker = SemanticChunker()
        chunks = chunker.chunk_for_review(code, target_tokens=8000)
        for chunk in chunks:
            print(chunk.symbols, chunk.start_line, chunk.end_line)
    """

    def __init__(self):
        pass

    # ---- 公开方法 ----

    def chunk_by_function(
        self,
        code: str,
        max_chunk_tokens: int = 4000,
        language: str = "python",
    ) -> list[ChunkInfo]:
        """按函数/类边界分块。

        每块不超过 max_chunk_tokens（按字符数/4 估算），
        以函数/类定义为边界分割。

        Args:
            code: 源代码文本
            max_chunk_tokens: 每块最大 token 数
            language: 编程语言

        Returns:
            ChunkInfo 列表
        """
        if language == "python":
            return self._chunk_python(code, max_chunk_tokens)
        else:
            # 不支持的语言：回退到固定大小分块
            return self._chunk_fallback(code, max_chunk_tokens)

    def chunk_for_review(
        self,
        code: str,
        target_tokens: int = 8000,
        language: str = "python",
    ) -> list[ChunkInfo]:
        """审查场景分块策略。

        代码总量 < target_tokens 时直接返回整段（不分块），
        否则按函数分块。

        Args:
            code: 源代码文本
            target_tokens: 目标 token 数
            language: 编程语言

        Returns:
            ChunkInfo 列表（可能只含一个块）
        """
        estimated_tokens = self._estimate_tokens(code)

        if estimated_tokens <= target_tokens:
            # 代码总量未超限，直接返回整段
            lines = code.split("\n")
            return [
                ChunkInfo(
                    content=code,
                    start_line=1,
                    end_line=len(lines),
                    symbols=self._extract_symbols(code, language),
                )
            ]

        # 超出限制，按函数分块
        return self.chunk_by_function(code, target_tokens, language)

    # ---- Python 分块 ----

    def _chunk_python(self, code: str, max_chunk_tokens: int) -> list[ChunkInfo]:
        """Python 代码按函数/类边界分块。

        利用 Tree-sitter 定位函数/类定义的起止行，
        以这些边界为分割点。
        """
        lines = code.split("\n")
        total_lines = len(lines)

        # 查找所有函数/类定义的起始行
        boundaries = self._find_python_boundaries(code)

        if not boundaries:
            return self._chunk_fallback(code, max_chunk_tokens)

        chunks: list[ChunkInfo] = []
        current_start = 0  # 0-based line index
        current_content: list[str] = []
        current_tokens = 0
        chunk_symbols: list[str] = []

        for symbol, start_line, end_line in boundaries:
            # 获取从 current_start 到 start_line 之间的所有代码
            segment = "\n".join(lines[current_start:start_line])
            segment_tokens = self._estimate_tokens(segment)

            # 如果加上这段会超限，先提交当前块
            if current_content and current_tokens + segment_tokens > max_chunk_tokens:
                chunks.append(ChunkInfo(
                    content="\n".join(current_content),
                    start_line=chunks[-1].end_line + 1 if chunks else 1,
                    end_line=current_start,
                    symbols=list(chunk_symbols),
                ))
                current_content = []
                current_tokens = 0
                chunk_symbols = []

            # 添加当前段
            for line in lines[current_start:end_line]:
                current_content.append(line)
            current_tokens += self._estimate_tokens(segment)
            chunk_symbols.append(symbol)
            current_start = end_line

        # 处理末尾剩余代码
        if current_start < total_lines:
            remaining = "\n".join(lines[current_start:])
            remaining_tokens = self._estimate_tokens(remaining)

            if current_content and current_tokens + remaining_tokens > max_chunk_tokens:
                chunks.append(ChunkInfo(
                    content="\n".join(current_content),
                    start_line=chunks[-1].end_line + 1 if chunks else 1,
                    end_line=current_start,
                    symbols=list(chunk_symbols),
                ))
                chunks.append(ChunkInfo(
                    content=remaining,
                    start_line=current_start + 1,
                    end_line=total_lines,
                ))
            else:
                for line in lines[current_start:]:
                    current_content.append(line)
                chunks.append(ChunkInfo(
                    content="\n".join(current_content),
                    start_line=chunks[-1].end_line + 1 if chunks else 1,
                    end_line=total_lines,
                    symbols=list(chunk_symbols),
                ))
        elif current_content:
            chunks.append(ChunkInfo(
                content="\n".join(current_content),
                start_line=chunks[-1].end_line + 1 if chunks else 1,
                end_line=total_lines,
                symbols=list(chunk_symbols),
            ))

        return chunks

    def _find_python_boundaries(self, code: str) -> list[tuple[str, int, int]]:
        """查找 Python 代码中所有函数/类的起止行。

        Returns:
            [(symbol_name, start_line_0based, end_line_1based), ...]
        """
        boundaries: list[tuple[str, int, int]] = []

        try:
            import tree_sitter
            import tree_sitter_python as tspy
        except ImportError:
            return boundaries

        py_lang = tree_sitter.Language(tspy.language())
        parser = tree_sitter.Parser(py_lang)

        tree = parser.parse(code.encode("utf-8"))
        root = tree.root_node

        def _walk(node):
            if node.type == "function_definition":
                name = "<unknown function>"
                for child in node.children:
                    if child.type == "identifier":
                        name = child.text.decode("utf-8")
                        break
                boundaries.append(
                    (f"def {name}", node.start_point[0], node.end_point[0] + 1)
                )
            elif node.type == "class_definition":
                name = "<unknown class>"
                for child in node.children:
                    if child.type == "identifier":
                        name = child.text.decode("utf-8")
                        break
                boundaries.append(
                    (f"class {name}", node.start_point[0], node.end_point[0] + 1)
                )
            for child in node.children:
                _walk(child)

        _walk(root)
        # 按起始行排序
        boundaries.sort(key=lambda x: x[1])
        return boundaries

    # ---- 回退分块（不支持的语言） ----

    def _chunk_fallback(self, code: str, max_chunk_tokens: int) -> list[ChunkInfo]:
        """固定大小分块（作为不支持语言的回退方案）。"""
        lines = code.split("\n")
        chunks: list[ChunkInfo] = []
        current: list[str] = []
        current_tokens = 0

        for i, line in enumerate(lines):
            line_tokens = max(1, len(line) // 4)

            if current and current_tokens + line_tokens > max_chunk_tokens:
                chunks.append(ChunkInfo(
                    content="\n".join(current),
                    start_line=chunks[-1].end_line + 1 if chunks else 1,
                    end_line=i,  # 1-based
                ))
                current = []
                current_tokens = 0

            current.append(line)
            current_tokens += line_tokens

        if current:
            chunks.append(ChunkInfo(
                content="\n".join(current),
                start_line=chunks[-1].end_line + 1 if chunks else 1,
                end_line=len(lines),
            ))

        return chunks

    # ---- 工具方法 ----

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """粗略估算 token 数（字符数 / 4）。"""
        if not text:
            return 0
        return max(1, len(text) // 4)

    @staticmethod
    def _extract_symbols(code: str, language: str) -> list[str]:
        """从代码中提取符号列表（函数名/类名）。"""
        symbols: list[str] = []

        if language == "python":
            import re
            class_match = re.findall(r'^\s*class\s+(\w+)', code, re.MULTILINE)
            func_match = re.findall(r'^\s*(?:async\s+)?def\s+(\w+)', code, re.MULTILINE)
            symbols.extend(f"class {c}" for c in class_match)
            symbols.extend(f"def {f}" for f in func_match)

        return symbols
