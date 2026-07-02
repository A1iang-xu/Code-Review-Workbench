"""
Agent 基类与上下文

定义所有审查 Agent 的抽象接口和运行上下文。
- BaseReviewAgent: 抽象基类，所有 Agent 继承此类
- AgentContext: Agent 运行时上下文，包含 LLM、AST 引擎、记忆上下文和压缩组件
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.integrations.ast_engine import ASTEngine, ParsedFile
from app.integrations.llm import LLMProvider
from app.core.compression.chunker import SemanticChunker
from app.core.compression.summarizer import HierarchicalSummarizer
from app.core.compression.token_manager import ModelTier, TokenQuotaManager


@dataclass
class AgentContext:
    """Agent 运行时上下文。

    包含 LLM 提供者、AST 引擎、记忆上下文、压缩组件和配置参数。
    """

    llm: type[LLMProvider] = LLMProvider
    ast_engine: ASTEngine = field(default_factory=ASTEngine)
    memory_context: str = ""
    language: str = "python"  # 当前审查语言，默认 python
    config: dict = field(default_factory=dict)
    # 压缩系统组件
    chunker: SemanticChunker = field(default_factory=SemanticChunker)
    summarizer: HierarchicalSummarizer = field(default_factory=HierarchicalSummarizer)
    token_manager: TokenQuotaManager = field(default_factory=TokenQuotaManager)


class BaseReviewAgent(ABC):
    """审查 Agent 抽象基类。

    所有 Agent 必须：
    1. 定义 agent_type（如 "style"、"security"）
    2. 定义 display_name（如 "风格检查Agent"）
    3. 实现 review(parsed_files) 方法
    """

    agent_type: str
    display_name: str

    def __init__(self, context: AgentContext):
        self.context = context

    @staticmethod
    def _walk(node, callback):
        """递归遍历 AST 节点树（供子类使用）。"""
        callback(node)
        for child in node.children:
            BaseReviewAgent._walk(child, callback)

    @abstractmethod
    async def review(self, parsed_files: list[ParsedFile]) -> list[dict]:
        """执行审查，返回问题列表。

        Returns:
            list[dict]: 每个元素格式为
                {
                    "agent_type": str,
                    "severity": str,
                    "file_path": str,
                    "line_start": int,
                    "line_end": int,
                    "category": str,
                    "title": str,
                    "description": str,
                    "suggestion": str,
                    "code_snippet": str,
                }
        """
        ...

    async def _llm_analyze(
        self,
        prompt: str,
        code_context: str,
        *,
        use_reasoning: bool = False,
    ) -> str:
        """调用 LLM 进行代码分析。

        集成压缩系统：
        1. 根据模型层级（本地/云端）检查 token 配额
        2. 代码上下文超限时，使用 SemanticChunker 分块 + HierarchicalSummarizer 摘要压缩
        3. 分配 token 预算并记录用量

        Args:
            prompt: 分析提示词
            code_context: 代码上下文
            use_reasoning: True 使用推理模型，False 使用本地模型

        Returns:
            LLM 响应的文本内容

        行为：
        1. 优先按 use_reasoning 选择模型调用
        2. 工具模型不可用时，**自动降级到推理模型**（避免噪声）
        3. 任何其他异常向上传播，由 Agent 决定如何处理
        """
        system_content = (
            "You are a code review agent. "
            "Analyze the provided code and return results in valid JSON format. "
            "Each finding should include: severity, category, title, "
            "description, suggestion, line_start, line_end."
        )

        memory_ctx = self.context.memory_context
        if memory_ctx:
            system_content += "\n\n" + memory_ctx

        # ---- 压缩系统：检查 token 配额，超限时压缩代码上下文 ----
        tier = ModelTier.CLOUD if use_reasoning else ModelTier.LOCAL
        token_mgr = self.context.token_manager
        budget = token_mgr.get_budget(tier)

        # 估算 prompt + system + code 的 token 用量
        prompt_tokens = token_mgr._estimate_tokens(prompt) + token_mgr._estimate_tokens(system_content)
        code_tokens = token_mgr._estimate_tokens(code_context)
        reserved_output = 2000  # 预留输出 token

        # 如果代码上下文超出可用预算，使用 chunker + summarizer 压缩
        available_for_code = max(0, budget.total - prompt_tokens - reserved_output)
        if code_tokens > available_for_code and available_for_code > 0:
            code_context = await self._compress_code_context(
                code_context, available_for_code, tier
            )
            code_tokens = token_mgr._estimate_tokens(code_context)

        # 分配 token 预算
        token_mgr.allocate_system(tier, system_content)
        token_mgr.allocate_code(tier, code_context)

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": f"{prompt}\n\n```\n{code_context}\n```"},
        ]
        token_mgr.allocate_messages(tier, messages)

        # 如果 token 使用率过高，压缩消息
        if token_mgr.should_compress(tier):
            messages = token_mgr.compress_messages(messages, tier)

        if use_reasoning:
            resp = await LLMProvider.reasoning(messages=messages)
        else:
            # utility() 内部已实现 Ollama→推理模型的降级
            resp = await LLMProvider.utility(messages=messages)

        if not resp.choices:
            return []

        return resp.choices[0].message.content or ""

    async def _compress_code_context(
        self,
        code: str,
        target_tokens: int,
        tier: ModelTier,
    ) -> str:
        """压缩代码上下文以适配 token 配额。

        使用 SemanticChunker 按函数边界分块，
        再用 HierarchicalSummarizer 生成摘要替代原始代码。

        Args:
            code: 原始代码文本
            target_tokens: 目标 token 数
            tier: 模型层级

        Returns:
            压缩后的代码上下文（摘要 + 关键代码片段）
        """
        chunker = self.context.chunker
        summarizer = self.context.summarizer

        # 按函数边界分块
        chunks = chunker.chunk_by_function(
            code, max_chunk_tokens=target_tokens, language="python"
        )

        if len(chunks) <= 1:
            # 无法分块，直接截断
            max_chars = target_tokens * 4
            return code[:max_chars] + "\n# ... (truncated due to token limit)"

        # 对每个块生成摘要，保留最重要的代码片段
        summaries: list[str] = []
        total_chars = 0
        max_chars = target_tokens * 4

        for i, chunk in enumerate(chunks):
            # 为每个块生成简短摘要
            summary = await summarizer.summarize_code(chunk.content)
            chunk_header = f"--- Chunk {i + 1}/{len(chunks)} (L{chunk.start_line}-L{chunk.end_line}) ---"
            summary_line = f"{chunk_header}\n[Summary] {summary}"
            summaries.append(summary_line)
            total_chars += len(summary_line)

            # 如果还有空间，附加部分代码
            remaining = max_chars - total_chars
            if remaining > len(chunk.content) // 3:
                snippet = chunk.content[:remaining // max(1, len(chunks) - i)]
                summaries.append(f"[Code]\n{snippet}")
                total_chars += len(snippet)

        compressed = "\n\n".join(summaries)
        compressed += (
            f"\n\n# [Compression] Original code ({len(code)} chars) "
            f"compressed to {len(compressed)} chars via {len(chunks)} chunks."
        )
        return compressed
