"""
Working Memory

管理当前审查任务的上下文窗口，维护 messages 列表和临时数据字典。
基于 tiktoken 的 cl100k_base 编码进行 token 统计，
超限时自动从最旧消息开始丢弃（保留 system prompt）。
"""

import tiktoken
from typing import Any


class WorkingMemory:
    """工作记忆 — 当前审查任务的上下文窗口。

    管理 messages 列表（对话历史）和 scratch_pad 字典（临时上下文数据）。
    自动追踪 token 用量，超限时触发压缩。

    Usage:
        wm = WorkingMemory(max_tokens=4000)
        wm.add_message("system", "You are a code reviewer...")
        wm.add_message("user", "Review this code: ...")
        wm.set("current_file", "src/main.py")
        print(wm.token_usage)
    """

    _MAX_SYSTEM_MESSAGES = 3  # 最多保留 system/developer 消息

    def __init__(self, max_tokens: int = 4000):
        self._max_tokens = max_tokens
        self._messages: list[dict[str, str]] = []
        self._scratch_pad: dict[str, Any] = {}
        self._token_count: int = 0

        try:
            self._encoder = tiktoken.get_encoding("cl100k_base")
        except Exception:
            # 降级：如果 tiktoken 模型不可用，使用 p50k_base
            try:
                self._encoder = tiktoken.get_encoding("p50k_base")
            except Exception:
                self._encoder = None

    # ---- Token 计算 ----

    def _count_tokens(self, text: str) -> int:
        """使用 tiktoken 精确计算文本 token 数。

        编码器不可用时回退到字符数/4 的粗略估算。
        """
        if self._encoder is not None:
            try:
                return len(self._encoder.encode(text))
            except Exception:
                pass
        # 降级估算
        return len(text) // 4

    def _count_message_tokens(self, message: dict[str, str]) -> int:
        """计算单条消息的 token 数（含 role 开销 ~4 tokens）。"""
        content = message.get("content", "")
        return self._count_tokens(content) + 4

    def _recalculate_tokens(self) -> None:
        """重新计算当前消息列表的总 token 数。"""
        self._token_count = sum(
            self._count_message_tokens(msg) for msg in self._messages
        )

    # ---- 消息管理 ----

    def add_message(self, role: str, content: str) -> None:
        """添加消息并统计 token 数。

        当 token 总数超过上限时，从最旧的非 system 消息开始丢弃。

        Args:
            role: 消息角色（system/user/assistant）
            content: 消息内容
        """
        self._messages.append({"role": role, "content": content})
        msg_tokens = self._count_tokens(self._messages[-1])
        self._token_count += msg_tokens

        # 超限压缩：从最旧的非 system 消息开始丢弃
        while self._token_count > self._max_tokens and len(self._messages) > self._MAX_SYSTEM_MESSAGES:
            # 找到第一个非 system 消息的索引
            drop_idx = None
            for i, msg in enumerate(self._messages):
                if msg["role"] not in ("system", "developer"):
                    drop_idx = i
                    break

            if drop_idx is None:
                break  # 所有消息都是 system，无法继续压缩

            removed = self._messages.pop(drop_idx)
            self._token_count -= self._count_message_tokens(removed)

    def get_context(self, max_messages: int | None = None) -> list[dict[str, str]]:
        """返回最近 N 条消息。

        Args:
            max_messages: 返回的最大消息数。None 返回全部。

        Returns:
            消息列表（按时间顺序）
        """
        if max_messages is None:
            return list(self._messages)
        return self._messages[-max_messages:]

    # ---- 临时上下文 ----

    def set(self, key: str, value: Any) -> None:
        """设置临时上下文数据。

        Args:
            key: 数据键名
            value: 任意可序列化数据
        """
        self._scratch_pad[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """获取临时上下文数据。

        Args:
            key: 数据键名
            default: 键不存在时的默认值

        Returns:
            存储的数据或默认值
        """
        return self._scratch_pad.get(key, default)

    # ---- 生命周期 ----

    def clear(self) -> None:
        """重置消息列表、临时数据和 token 计数。"""
        self._messages.clear()
        self._scratch_pad.clear()
        self._token_count = 0

    # ---- 属性 ----

    @property
    def token_usage(self) -> int:
        """当前 token 占用数。"""
        return self._token_count

    @property
    def usage_ratio(self) -> float:
        """当前 token 使用比例 (0.0 ~ 1.0)。"""
        if self._max_tokens == 0:
            return 0.0
        return self._token_count / self._max_tokens

    @property
    def message_count(self) -> int:
        """当前消息数量。"""
        return len(self._messages)

    def __repr__(self) -> str:
        return (
            f"WorkingMemory(messages={len(self._messages)}, "
            f"tokens={self._token_count}/{self._max_tokens}, "
            f"scratch_pad_keys={list(self._scratch_pad.keys())})"
        )
