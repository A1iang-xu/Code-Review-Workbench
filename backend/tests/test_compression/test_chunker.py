"""
Semantic Chunker tests.

Validates function-boundary chunking.
"""

from app.core.compression.chunker import SemanticChunker


class TestSemanticChunkerByFunction:
    """Verify semantic chunker splits code at function boundaries."""

    def test_chunks_at_function_boundaries(self):
        code = (
            "def func_a():\n"
            "    pass\n"
            "\n"
            "def func_b():\n"
            "    return 1\n"
            "\n"
            "class MyClass:\n"
            "    def method(self):\n"
            "        pass\n"
        )

        chunker = SemanticChunker()
        chunks = chunker.chunk_by_function(code, max_chunk_tokens=100)

        assert len(chunks) >= 1, f"Should produce at least 1 chunk. Got {len(chunks)}"

        # At least one chunk should contain symbols
        symbols = []
        for c in chunks:
            symbols.extend(c.symbols)
        assert len(symbols) >= 1, f"Should find at least 1 symbol. Found: {symbols}"

    def test_small_code_returns_single_chunk(self):
        code = "x = 42\n"

        chunker = SemanticChunker()
        chunks = chunker.chunk_for_review(code, target_tokens=8000)

        assert len(chunks) == 1, f"Small code should be 1 chunk. Got {len(chunks)}"
        assert chunks[0].content == code, (
            f"Chunk content should match original. Got: {chunks[0].content}"
        )

    def test_fallback_for_unsupported_language(self):
        code = "line 1\n" * 100

        chunker = SemanticChunker()
        chunks = chunker.chunk_by_function(code, max_chunk_tokens=50, language="unknown")

        assert len(chunks) >= 1, f"Fallback should produce at least 1 chunk. Got {len(chunks)}"
