"""
测试样本文件 — 用于验证 Skill 和 Agent 联合审查功能

包含以下问题类型：
- 硬编码 API 密钥 (security)
- SQL 注入漏洞 (security)
- 超长函数 (style)
- 命名不规范 (style)
- 高圈复杂度 (complexity)
- 嵌套循环 (performance)
"""

API_KEY = "sk-proj-abc123def456ghi789jkl012mno345pqr678stu901vwx234yz"

import sqlite3
import os


def get_user(user_id):
    """Vulnerable to SQL injection."""
    conn = sqlite3.connect("users.db")
    query = f"SELECT * FROM users WHERE id = {user_id}"
    return conn.execute(query).fetchall()


def long_function():
    """A function that is intentionally long for testing."""
    result = []
    for i in range(10):
        result.append(i)
    for i in range(10):
        result.append(i * 2)
    for i in range(10):
        result.append(i * 3)
    for j in range(10):
        result.append(j)
    for j in range(10):
        result.append(j * 2)
    for j in range(10):
        result.append(j * 3)
    for k in range(10):
        result.append(k)
    for k in range(10):
        result.append(k * 2)
    for k in range(10):
        result.append(k * 3)
    for m in range(10):
        result.append(m)
    for m in range(10):
        result.append(m * 2)
    for m in range(10):
        result.append(m * 3)
    for n in range(10):
        result.append(n)
    for n in range(10):
        result.append(n * 2)
    for n in range(10):
        result.append(n * 3)
    for x in range(10):
        result.append(x)
    for x in range(10):
        result.append(x * 2)
    for x in range(10):
        result.append(x * 3)
    for y in range(10):
        result.append(y)
    for y in range(10):
        result.append(y * 2)
    for y in range(10):
        result.append(y * 3)
    for a in range(5):
        for b in range(5):
            for c in range(5):
                result.append((a, b, c))
    return result


def good_function():
    """A well-structured function."""
    return sum(range(100))