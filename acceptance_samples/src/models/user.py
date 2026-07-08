"""User model module — 验收测试：循环依赖 + 安全问题。

前端提交时 path 字段填：src/models/user.py
"""
import sqlite3
from src.api.routes import get_user_handler  # 循环依赖：user → routes → user

# 硬编码密钥（安全 Agent 第一轮应检测到）
API_KEY = "sk-proj-abc123def456ghi789jkl012mno345pqr678stu901vwx234yz"


def get_user(user_id):
    """SQL 注入漏洞（安全 Agent 第一轮应检测到）。"""
    conn = sqlite3.connect("users.db")
    query = f"SELECT * FROM users WHERE id = {user_id}"
    return conn.execute(query).fetchall()


def save_user(name, email):
    """另一个 SQL 注入点，供 routes 调用。"""
    conn = sqlite3.connect("users.db")
    conn.execute(f"INSERT INTO users (name, email) VALUES ('{name}', '{email}')")
    conn.commit()
