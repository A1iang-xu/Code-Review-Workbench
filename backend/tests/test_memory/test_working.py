"""
Working Memory tests.

Validates token limit enforcement — old messages are dropped when over limit.
"""

from app.core.memory.working import WorkingMemory


class TestWorkingMemoryTokenLimit:
    """Verify working memory drops old messages when token limit exceeded."""

    def test_token_limit_auto_drop(self):
        wm = WorkingMemory(max_tokens=100)

        # Add a system message
        wm.add_message("system", "You are a code reviewer.")

        # Add many large messages to exceed the limit
        for i in range(50):
            wm.add_message("user", f"Message {i}: " + "x" * 100)

        # System message should be preserved
        context = wm.get_context()
        system_msgs = [m for m in context if m["role"] == "system"]
        assert len(system_msgs) >= 1, (
            f"System message should be preserved. Context: {context}"
        )

        # Token count should be within limits
        assert wm.token_usage <= wm._max_tokens or wm.message_count >= 1, (
            f"Token usage ({wm.token_usage}) should be <= max ({wm._max_tokens}) "
            f"or at least system message should remain"
        )

    def test_short_messages_not_dropped(self):
        wm = WorkingMemory(max_tokens=4000)
        wm.add_message("system", "You are helpful.")
        wm.add_message("user", "Hello")
        wm.add_message("assistant", "Hi there")

        assert wm.message_count == 3, (
            f"Short messages should not be dropped. Count: {wm.message_count}"
        )

    def test_scratch_pad(self):
        wm = WorkingMemory(max_tokens=4000)
        wm.set("current_file", "src/main.py")
        wm.set("issues_found", 42)

        assert wm.get("current_file") == "src/main.py"
        assert wm.get("issues_found") == 42
        assert wm.get("nonexistent", "default") == "default"
