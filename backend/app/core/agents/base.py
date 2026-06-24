"""
Agent 基类与上下文

定义所有审查 Agent 的抽象接口和运行上下文。
- BaseReviewAgent: 抽象基类，所有 Agent 继承此类
- AgentContext: Agent 运行时上下文，包含 LLM、AST 引擎和记忆上下文
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.integrations.ast_engine import ASTEngine, ParsedFile
from app.integrations.llm import LLMProvider


@dataclass
class AgentContext:
    """Agent 运行时上下文。

    包含 LLM 提供者、AST 引擎、记忆上下文和配置参数。
    """

    llm: type[LLMProvider] = LLMProvider
    ast_engine: ASTEngine = field(default_factory=ASTEngine)
    memory_context: str = ""
    language: str = "python"  # 当前审查语言，默认 python
    config: dict = field(default_factory=dict)


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

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": f"{prompt}\n\n```\n{code_context}\n```"},
        ]

        if use_reasoning:
            resp = await LLMProvider.reasoning(messages=messages)
        else:
            # utility() 内部已实现 Ollama→推理模型的降级
            resp = await LLMProvider.utility(messages=messages)

        if not resp.choices:
            return []

        return resp.choices[0].message.content or ""
