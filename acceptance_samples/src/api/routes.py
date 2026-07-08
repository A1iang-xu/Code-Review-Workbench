"""API routes module — 验收测试：与 user.py 形成循环依赖。

前端提交时 path 字段填：src/api/routes.py
"""
from src.models.user import get_user, save_user  # 循环依赖：routes → user → routes


def get_user_handler(user_id):
    """Handler 委托给 user model。"""
    user = get_user(user_id)
    return {"data": user}


def create_user_handler(name, email):
    """用户创建入口，委托给 user model。"""
    save_user(name, email)
    return {"status": "ok"}
