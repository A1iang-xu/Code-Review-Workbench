"""
Hierarchical Summarizer

分层摘要生成器，对代码块 → 文件 → 模块 → 项目逐层生成摘要。
使用 LLM utility 模型减少 token 消耗。
"""

from typing import Any


class HierarchicalSummarizer:
    """分层摘要生成器。

    对代码进行分层级摘要：代码块 → 文件 → 模块 → 项目。
    使用 LLM utility 模型（本地 Qwen）降低成本。

    Usage:
        hs = HierarchicalSummarizer()
        block_summary = await hs.summarize_code("def foo(): ...")
        file_summary = await hs.summarize_file([chunk1, chunk2])
    """

    def __init__(self):
        pass

    # ---- 代码块级摘要 ----

    async def summarize_code(self, code: str, max_tokens: int = 100) -> str:
        """对单段代码生成 1-2 句功能摘要。

        Args:
            code: 代码文本
            max_tokens: 摘要最大 token 数

        Returns:
            代码功能摘要
        """
        if not code or not code.strip():
            return "(空代码)"

        # 限制输入长度
        if len(code) > 6000:
            code = code[:6000] + "\n# ... (truncated)"

        try:
            from app.integrations.llm import LLMProvider

            response = await LLMProvider.utility(
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"用 1 句中文总结以下代码的功能（不超过 30 字）：\n\n```\n{code}\n```"
                        ),
                    }
                ],
                max_tokens=max_tokens,
                temperature=0.1,
            )
            return (
                response.choices[0].message.content.strip()
                if response.choices
                else self._fallback_summary(code)
            )
        except Exception:
            return self._fallback_summary(code)

    @staticmethod
    def _fallback_summary(code: str) -> str:
        """降级摘要：返回前几个非空行。"""
        lines = [l.strip() for l in code.split("\n") if l.strip()]
        if not lines:
            return "(空代码)"
        first = lines[0]
        if len(first) > 80:
            first = first[:80] + "..."
        return first

    # ---- 文件级摘要 ----

    async def summarize_file(self, code_chunks: list[str]) -> str:
        """对文件的所有代码块摘要进行汇总，生成文件级摘要。

        Args:
            code_chunks: 代码块内容列表

        Returns:
            文件级摘要（2-3 句）
        """
        if not code_chunks:
            return "(空文件)"

        # 先对各块生成摘要
        block_summaries: list[str] = []
        for chunk in code_chunks[:10]:  # 最多 10 个块
            summary = await self.summarize_code(chunk)
            if summary:
                block_summaries.append(summary)

        if not block_summaries:
            return "(无法生成摘要)"

        # 汇总为文件级摘要
        combined = "\n".join(f"- {s}" for s in block_summaries)

        try:
            from app.integrations.llm import LLMProvider

            response = await LLMProvider.utility(
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"以下是一个文件中各代码块的功能描述。"
                            f"请用 2-3 句中文总这个文件做了什么：\n\n{combined}"
                        ),
                    }
                ],
                max_tokens=150,
                temperature=0.1,
            )
            return (
                response.choices[0].message.content.strip()
                if response.choices
                else "包含 " + "、".join(block_summaries[:3])
            )
        except Exception:
            return "包含 " + "、".join(block_summaries[:3])
