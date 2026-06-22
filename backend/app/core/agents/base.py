"""
Agent 基类与上下文

定义所有审查 Agent 的抽象接口和运行上下文。
- BaseReviewAgent: 抽象基类，所有 Agent 继承此类
- AgentContext: Agent 运行时上下文，包含 LLM 和 AST 引擎实例
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.integrations.ast_engine import ASTEngine, ParsedFile
from app.integrations.llm import LLMProvider


@dataclass
class AgentContext:
    """Agent 运行时上下文。

    包含 LLM 提供者、AST 引擎和配置参数。
    """

    llm: type[LLMProvider] = LLMProvider
    ast_engine: ASTEngine = field(default_factory=ASTEngine)
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

    @abstractmethod
    async def review(self, parsed_files: list[ParsedFile]) -> list[dict]:
        """执行审查，返回问题列表。

        Args:
            parsed_files: ASTEngine 解析后的文件列表

        Returns:
            list[dict]: 每个元素格式为
                {
                    "agent_type": str,
                    "severity": str,      # critical/high/medium/low/info
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
            code_context: 代码上下文（被分析的代码内容）
            use_reasoning: True 使用 GLM-5.2（推理），False 使用本地模型（工具）

        Returns:
            LLM 响应的文本内容
        """
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a code review agent. "
                    "Analyze the provided code and return results in valid JSON format. "
                    "Each finding should include: severity, category, title, description, suggestion, line_start, line_end."
                ),
            },
            {
                "role": "user",
                "content": f"{prompt}\n\n```\n{code_context}\n```",
            },
        ]

        if use_reasoning:
            resp = await self.context.llm.reasoning(messages=messages)
        else:
            resp = await self.context.llm.utility(messages=messages)

        return resp.choices[0].message.content or ""
