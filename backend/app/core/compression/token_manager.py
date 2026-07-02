"""
Token 管理 — 配额分配与消息压缩

提供 ModelTier 枚举、TokenBudget 数据类和 TokenQuotaManager，
管理本地模型和云端模型的 token 预算分配与压缩策略。
"""

from dataclasses import dataclass
from enum import Enum


class ModelTier(str, Enum):
    """模型层级枚举。"""
    LOCAL = "local"   # 本地模型（Ollama），预算 4000 tokens
    CLOUD = "cloud"   # 云端模型（GLM/DeepSeek），预算 16000 tokens


@dataclass
class TokenBudget:
    """Token 预算数据类。

    描述一次 LLM 调用的 token 分配方案。

    Attributes:
        total: 总 token 预算
        system_prompt: 系统提示词占用
        code_context: 代码上下文占用
        agent_messages: Agent 消息占用
        reserved: 预留给输出的 token
    """
    total: int
    system_prompt: int = 0
    code_context: int = 0
    agent_messages: int = 0
    reserved: int = 0  # 预留给模型输出

    @property
    def used(self) -> int:
        """已使用的 token 数。"""
        return self.system_prompt + self.code_context + self.agent_messages

    @property
    def available(self) -> int:
        """可用的 token 数。"""
        return max(0, self.total - self.used - self.reserved)

    @property
    def usage_ratio(self) -> float:
        """token 使用比例 (0.0 ~ 1.0)。"""
        if self.total == 0:
            return 0.0
        return self.used / self.total


# 预算表：各层级模型的 token 限额
BUDGET_TABLE: dict[ModelTier, int] = {
    ModelTier.LOCAL: 4000,
    ModelTier.CLOUD: 16000,
}


class TokenQuotaManager:
    """Token 配额管理器。

    管理不同模型层级的 token 预算分配，
    在用量超过 70% 时触发消息压缩。

    Usage:
        tqm = TokenQuotaManager()
        tqm.allocate_code(ModelTier.LOCAL, code)
        tqm.allocate_system(ModelTier.LOCAL, system_prompt)
        if tqm.should_compress(ModelTier.LOCAL):
            compressed = tqm.compress_messages(messages, ModelTier.LOCAL)
    """

    _COMPRESS_THRESHOLD = 0.7  # 用量超过 70% 触发压缩
    _KEEP_RECENT = 6  # 压缩时保留最近的消息数

    def __init__(self):
        self._budgets: dict[ModelTier, TokenBudget] = {
            tier: TokenBudget(total=limit)
            for tier, limit in BUDGET_TABLE.items()
        }
        self._stored_messages: dict[ModelTier, list[dict[str, str]]] = {
            tier: [] for tier in ModelTier
        }

    # ---- 预算分配 ----

    def allocate_code(self, tier: ModelTier, code: str) -> int:
        """为代码上下文分配 token。

        Args:
            tier: 模型层级
            code: 代码文本

        Returns:
            分配的 token 数
        """
        tokens = self._estimate_tokens(code)
        self._budgets[tier].code_context += tokens
        return tokens

    def allocate_system(self, tier: ModelTier, system_prompt: str) -> int:
        """为系统提示词分配 token。

        Args:
            tier: 模型层级
            system_prompt: 系统提示词文本

        Returns:
            分配的 token 数
        """
        tokens = self._estimate_tokens(system_prompt)
        self._budgets[tier].system_prompt += tokens
        return tokens

    def allocate_messages(self, tier: ModelTier, messages: list[dict[str, str]]) -> int:
        """为消息列表分配 token。

        Args:
            tier: 模型层级
            messages: 消息列表

        Returns:
            分配的 token 数
        """
        tokens = sum(
            self._estimate_tokens(m.get("content", "")) + 4
            for m in messages
        )
        self._budgets[tier].agent_messages += tokens
        self._stored_messages[tier] = list(messages)
        return tokens

    # ---- 压缩判断 ----

    def should_compress(self, tier: ModelTier) -> bool:
        """判断是否需要压缩。

        Args:
            tier: 模型层级

        Returns:
            True 表示 token 使用率超过 70%，需要压缩
        """
        budget = self._budgets[tier]
        return budget.usage_ratio > self._COMPRESS_THRESHOLD

    def compress_messages(
        self, messages: list[dict[str, str]], tier: ModelTier
    ) -> list[dict[str, str]]:
        """压缩消息列表。

        当 usage_ratio > 0.7 时：
        - 保留 system prompt
        - 保留最近 6 条消息
        - 中间消息用摘要替代（一行 "[...上下文已压缩...]" 占位）

        Args:
            messages: 原始消息列表
            tier: 模型层级

        Returns:
            压缩后的消息列表
        """
        if not self.should_compress(tier):
            return list(messages)

        # 分离 system 消息和非 system 消息
        system_msgs = [m for m in messages if m["role"] in ("system", "developer")]
        other_msgs = [m for m in messages if m["role"] not in ("system", "developer")]

        # 如果非 system 消息不多，不需要压缩
        if len(other_msgs) <= self._KEEP_RECENT + 2:
            return list(messages)

        # 保留最近的消息 + 插入摘要占位
        kept = other_msgs[-self._KEEP_RECENT:]
        summary_msg = {
            "role": "system",
            "content": (
                "[上下文摘要] 之前的对话已压缩。"
                f"共省略 {len(other_msgs) - self._KEEP_RECENT} 条消息。"
            ),
        }

        result = system_msgs + [summary_msg] + kept

        # 更新 token 预算
        self._budgets[tier].agent_messages = sum(
            self._estimate_tokens(m.get("content", "")) + 4
            for m in result
        )

        return result

    # ---- 工具方法 ----

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """粗略估算 token 数（字符数 / 4）。

        快速估算方法，用于高频调用场景。
        tiktoken 精确计算在 WorkingMemory 中使用。
        """
        if not text:
            return 0
        return max(1, len(text) // 4)

    # ---- 属性 ----

    def get_budget(self, tier: ModelTier) -> TokenBudget:
        """获取指定层级的当前预算。"""
        return self._budgets[tier]

    def reset_tier(self, tier: ModelTier) -> None:
        """重置指定层级的预算。"""
        self._budgets[tier] = TokenBudget(
            total=BUDGET_TABLE[tier]
        )
        self._stored_messages[tier] = []
