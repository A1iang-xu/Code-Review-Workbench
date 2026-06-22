# Skill 开发指南

本指南介绍如何创建自定义 Skill，扩展开箱即用的代码分析能力。

## 概述

Skill 是代码审查工坊的可插拔分析模块。每个 Skill 封装一种代码分析能力，Agent 运行时按需加载。

### 内置 Skill (10 个)

| Skill | 说明 | 分类 |
|-------|------|------|
| `ast_scan` | AST 结构化扫描 (Tree-sitter) | static_analysis |
| `semgrep_scan` | Semgrep 模式匹配 | pattern_match |
| `cve_check` | CVE 漏洞扫描 | security |
| `dep_analyze` | 依赖关系分析 | architecture |
| `complexity_check` | 圈复杂度计算 (radon) | performance |
| `sql_injection_detect` | SQL 注入检测 | security |
| `secret_leak_detect` | 密钥泄露检测 (detect-secrets) | security |
| `style_check` | 代码风格检查 | style |
| `refactor_suggest` | 重构建议生成 | style |
| `diff_context` | Git Diff 上下文增强 | utility |

## 快速开始

### 1. 创建 Skill 文件

在 `skills/` 目录下创建新的 Python 文件：

```python
# skills/my_custom_skill.py
from app.core.skills.registry import (
    BaseSkill, SkillMetadata, SkillResult, SkillCategory
)


class MyCustomSkill(BaseSkill):
    """自定义代码分析 Skill。"""

    metadata = SkillMetadata(
        name="my_custom_skill",
        display_name="我的自定义 Skill",
        version="1.0.0",
        category=SkillCategory.STATIC_ANALYSIS,
        description="检查代码中的特定模式",
        author="Your Name",
        languages=["python", "go"],
        tags=["custom", "example"],
        requires=[],  # 依赖的其他 Skill
    )

    async def execute(
        self,
        code: str,
        file_path: str = "<string>",
        context: dict | None = None,
    ) -> SkillResult:
        """执行分析逻辑。

        Args:
            code: 源代码文本
            file_path: 文件路径
            context: 可选的上下文信息

        Returns:
            SkillResult 对象
        """
        findings = []
        lines = code.split("\n")

        for i, line in enumerate(lines):
            # 自定义检测逻辑
            if "TODO" in line:
                findings.append({
                    "type": "todo",
                    "file_path": file_path,
                    "line": i + 1,
                    "message": f"发现 TODO: {line.strip()}",
                })

        return SkillResult(
            success=True,
            findings=findings,
            summary=f"发现 {len(findings)} 个 TODO 注释",
        )

    async def validate(self) -> bool:
        """可选：验证执行环境。"""
        # 检查依赖工具是否可用
        return True

    async def cleanup(self) -> None:
        """可选：清理资源。"""
        pass
```

### 2. 启用 Skill

Skill 放在 `skills/` 目录后，通过 API 重新加载：

```bash
curl -X POST http://localhost:8000/api/v1/skills/reload
```

或重启后端容器：

```bash
docker compose restart backend
```

### 3. 测试 Skill

```bash
curl -X POST http://localhost:8000/api/v1/skills/execute \
  -H "Content-Type: application/json" \
  -d '{
    "skill_name": "my_custom_skill",
    "code": "# TODO: refactor this\ndef main():\n    pass\n",
    "file_path": "main.py"
  }'
```

## SkillMetadata 字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | str | 是 | 唯一标识符 (snake_case) |
| display_name | str | 是 | 显示名称 |
| version | str | 否 | 版本号 (默认 "1.0.0") |
| category | SkillCategory | 是 | 分类 |
| description | str | 是 | 简要描述 |
| author | str | 否 | 作者 |
| languages | list[str] | 否 | 支持的语言 (默认 ["python"]) |
| tags | list[str] | 否 | 标签 |
| requires | list[str] | 否 | 依赖的其他 Skill 名称 |

## SkillCategory 枚举

| 值 | 说明 |
|----|------|
| `static_analysis` | 静态分析 (AST/语法树) |
| `pattern_match` | 模式匹配 (正则/Semgrep) |
| `security` | 安全检测 |
| `architecture` | 架构分析 |
| `performance` | 性能分析 |
| `style` | 代码风格 |
| `utility` | 工具/辅助 |

## SkillResult 字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| success | bool | 是 | 执行是否成功 |
| findings | list[dict] | 否 | 发现列表 |
| summary | str | 否 | 执行摘要 |
| raw_output | str | 否 | 原始输出 (调试用) |
| execution_time_ms | float | 否 | 执行时间 (毫秒) |
| tokens_used | int | 否 | LLM Token 消耗量 |

## 生命周期钩子

### validate()

执行前环境验证。在此检查：
- 外部工具是否可用 (`shutil.which("tool")`)
- API Key 是否已配置
- 依赖的数据文件是否存在

```python
async def validate(self) -> bool:
    import shutil
    if not shutil.which("semgrep"):
        return False
    return True
```

### cleanup()

执行后清理。在此释放：
- 临时文件
- 网络连接
- 进程句柄

```python
async def cleanup(self) -> None:
    if self._temp_dir:
        shutil.rmtree(self._temp_dir, ignore_errors=True)
```

## 上下文对象

`context` 参数可以接收任意数据。常用场景：

```python
async def execute(self, code, file_path, context=None):
    # 获取 AST 树 (如果已解析)
    ast_tree = context.get("ast_tree") if context else None

    # 获取 Agent 上下文
    agent_context = context.get("agent_context") if context else None

    # 获取前一个 Skill 的结果 (链式执行时)
    prev_result = context.get("_previous_result") if context else None
```

## 最佳实践

1. **单一职责** — 每个 Skill 只做一件事，通过链式执行串联复杂分析
2. **快速返回** — Skill 应尽可能快，避免长时间阻塞
3. **容错设计** — execute() 内部捕获异常，不应导致审查流水线中断
4. **详细摘要** — summary 应包含足够信息，让用户无需查看 findings 就能了解结果
5. **结构化输出** — findings 列表中每个元素应包含一致的关键字段 (type, line, message 等)
6. **版本管理** — 每次修改 Skill 逻辑时递增 version 号

## 链式执行示例

多个 Skill 可以链式执行，前一个 Skill 的结果注入后一个的上下文：

```python
from app.core.skills.executor import SkillExecutor

executor = SkillExecutor()
results = await executor.execute_pipeline(
    skill_names=["ast_scan", "complexity_check", "refactor_suggest"],
    code=source_code,
    file_path="main.py",
)
# results[0] 的输出可通过 context["_previous_result"] 在 results[1] 中访问
```

## 并行执行示例

```python
results = await executor.execute_all(
    skill_names=["ast_scan", "semgrep_scan", "secret_leak_detect"],
    code=source_code,
    file_path="main.py",
)
# 返回 {"ast_scan": SkillResult, "semgrep_scan": SkillResult, ...}
```

## 调试技巧

```python
# 在 Skill 中添加日志
import logging
logger = logging.getLogger(__name__)

class MySkill(BaseSkill):
    async def execute(self, code, file_path, context=None):
        logger.info(f"Executing {self.metadata.name} on {file_path}")
        logger.debug(f"Code length: {len(code)} chars")
```
