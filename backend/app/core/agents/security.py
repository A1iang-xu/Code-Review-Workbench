"""
Security Auditor Agent

安全审计 Agent，分为两步：
1. 正则模式匹配：快速扫描硬编码密钥、命令注入、不安全反序列化、SQL 注入
2. LLM 深度推理：使用推理模型（GLM-5.2）检测 XSS、路径遍历、SSRF 等复杂漏洞

采用"正则先行 + LLM 深度分析"双层策略，正则排除注释行和误报场景。
"""

import json
import re

from app.core.agents.base import BaseReviewAgent
from app.integrations.ast_engine import ParsedFile


# ============================================================
# 系统提示词
# ============================================================

SECURITY_PROMPT = """You are a senior application security engineer conducting a thorough code review.
Analyze the provided code for the following 8 categories of security vulnerabilities:

1. **SQL Injection**: User input concatenated into SQL queries without parameterization
2. **XSS (Cross-Site Scripting)**: Unsanitized user input rendered into HTML/JS output
3. **Path Traversal**: User input used in file paths without sanitization (e.g., ../ attacks)
4. **Hardcoded Secrets**: API keys, tokens, passwords, private keys hardcoded in source
5. **Insecure Deserialization**: pickle.loads, yaml.load (unsafe), marshal.loads on user input
6. **Command Injection**: Shell command construction with user input (os.system, subprocess with shell=True)
7. **SSRF (Server-Side Request Forgery)**: User-controlled URLs passed to HTTP clients
8. **Missing Authorization**: Endpoints or functions lacking permission/role checks

For each finding, return a JSON object with the following fields:
{
    "severity": "critical|high|medium|low",
    "category": "sql_injection|xss|path_traversal|hardcoded_secret|insecure_deserialization|command_injection|ssrf|missing_auth",
    "title": "brief description of the vulnerability",
    "description": "detailed explanation of the risk",
    "suggestion": "specific remediation steps with code example if applicable",
    "line_start": <line number where the issue starts, or 0 if unknown>,
    "line_end": <line number where the issue ends, or 0 if unknown>
}

IMPORTANT:
- Return ONLY a valid JSON array of findings. No markdown, no extra text.
- If no vulnerabilities are found, return [].
- Severity levels: critical (immediate exploit risk), high (likely exploitable), medium (potential risk), low (best practice violation).
- Focus on real vulnerabilities, not theoretical concerns."""


# ============================================================
# 支持的语言
# ============================================================

SUPPORTED_LANGUAGES = {"python", "go", "typescript", "javascript", "java"}


# ============================================================
# 高危模式正则（按语言分组）
# ============================================================

# Python 高危模式
HIGH_RISK_PATTERNS_PYTHON: dict[str, tuple[str, str, str]] = {
    # category -> (pattern, title_template, suggestion)
    "hardcoded_secret": (
        # 匹配 API_KEY = "..."、SECRET = "..."、password = "..." 等模式
        r'(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|'
        r'private[_-]?key|password|passwd|jwt[_-]?secret|encryption[_-]?key)\s*[:=]\s*'
        r'["\'][A-Za-z0-9+/=_\-.@!]{8,}["\']',
        "硬编码密钥: {match}",
        "将密钥移至环境变量或密钥管理服务（如 Vault、AWS Secrets Manager）。使用 `os.getenv('KEY_NAME')` 替代硬编码。"
    ),
    "command_injection": (
        # 匹配 os.system(f"...{var}...")、subprocess.*(f"...{var}...", shell=True)
        r'(?i)(?:os\.(?:system|popen)\s*\(\s*(?:f["\']|["\'].*?\{)|'
        r'subprocess\.(?:call|run|Popen)\s*\([^)]*shell\s*=\s*True)',
        "命令注入风险: {match}",
        "使用 `subprocess.run([cmd, arg1, arg2], shell=False)` 参数化命令，避免 shell=True 和字符串拼接。对用户输入进行严格的白名单过滤。"
    ),
    "insecure_deserialization": (
        # 匹配 pickle.load(s/loads、yaml.load(（非 SafeLoader）、marshal.loads
        r'(?i)(?:pickle\.(?:load|loads)\s*\(|'
        r'yaml\.load\s*\((?!.*Loader\s*=\s*yaml\.(?:Safe|Base)Loader)|'
        r'marshal\.loads?\s*\()',
        "不安全反序列化: {match}",
        "使用 `yaml.safe_load()` 替代 `yaml.load()`。避免对不可信数据使用 `pickle.loads()`，改用 JSON 序列化。"
    ),
    "sql_injection": (
        # 匹配字符串拼接 SQL: f"SELECT ... {var}"、query = "SELECT ... " + var
        r'(?i)(?:f["\']\s*(?:SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE)\b[^"\']*\{|'
        r'["\']\s*(?:SELECT|INSERT|UPDATE|DELETE)\b[^"\']*["\']\s*\+)',
        "SQL 注入风险: {match}",
        "使用参数化查询：`cursor.execute('SELECT * FROM users WHERE id = %s', (user_id,))`。或使用 ORM 框架的安全查询方法。"
    ),
}

# Go 高危模式
HIGH_RISK_PATTERNS_GO: dict[str, tuple[str, str, str]] = {
    "hardcoded_secret": (
        r'(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|'
        r'private[_-]?key|password|passwd|jwt[_-]?secret|encryption[_-]?key)\s*[:=]\s*'
        r'`[^`]{8,}`',
        "硬编码密钥: {match}",
        "将密钥移至环境变量（os.Getenv）或密钥管理服务。避免在源码中硬编码敏感信息。"
    ),
    "command_injection": (
        r'(?i)exec\.Command\s*\(\s*(?:fmt\.Sprintf|.*?\+)',
        "命令注入风险: {match}",
        "使用 exec.Command 直接传参，避免通过字符串拼接构造命令。对用户输入进行严格校验。"
    ),
    "sql_injection": (
        r'(?i)(?:fmt\.Sprintf\s*\(\s*["\'](?:SELECT|INSERT|UPDATE|DELETE|DROP)\b[^"\']*\%[svd])',
        "SQL 注入风险: {match}",
        "使用 database/sql 的参数化查询（db.Query(sql, args...)），避免 fmt.Sprintf 拼接 SQL。"
    ),
    "path_traversal": (
        r'(?i)(?:os\.Open|os\.OpenFile|os\.ReadFile|filepath\.Join)\s*\([^)]*(?:req\.|r\.URL|args)',
        "路径遍历风险: {match}",
        "对用户输入的路径进行 filepath.Clean 和校验，确保不包含 ../ 等目录穿越字符。"
    ),
}

# TypeScript/JavaScript 高危模式
HIGH_RISK_PATTERNS_TS_JS: dict[str, tuple[str, str, str]] = {
    "hardcoded_secret": (
        r'(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|'
        r'private[_-]?key|password|passwd|jwt[_-]?secret|encryption[_-]?key)\s*[:=]\s*'
        r'["\'][A-Za-z0-9+/=_\-.@!]{8,}["\']',
        "硬编码密钥: {match}",
        "将密钥移至环境变量（process.env）或密钥管理服务。避免在源码中硬编码敏感信息。"
    ),
    "command_injection": (
        r'(?i)(?:child_process\.(?:exec|execSync)\s*\(\s*(?:`.*\$\{|.*\+)|'
        r'eval\s*\(\s*(?:`.*\$\{|.*\+))',
        "命令注入风险: {match}",
        "使用 child_process.execFile 参数化命令，避免 exec 和字符串拼接。禁止对用户输入使用 eval()。"
    ),
    "xss": (
        r'(?i)(?:\.innerHTML\s*=\s*(?:`.*\$\{|.*\+)|'
        r'dangerouslySetInnerHTML\s*=\s*\{)',
        "XSS 风险: {match}",
        "对用户输入进行 HTML 转义，使用 textContent 替代 innerHTML。在 React 中避免使用 dangerouslySetInnerHTML。"
    ),
    "sql_injection": (
        r'(?i)(?:`(?:SELECT|INSERT|UPDATE|DELETE|DROP)\b[^`]*\$\{)',
        "SQL 注入风险: {match}",
        "使用参数化查询库（如 prepared statements），避免模板字符串拼接 SQL。"
    ),
}

# Java 高危模式
HIGH_RISK_PATTERNS_JAVA: dict[str, tuple[str, str, str]] = {
    "hardcoded_secret": (
        r'(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|'
        r'private[_-]?key|password|passwd|jwt[_-]?secret|encryption[_-]?key)\s*[:=]\s*'
        r'"[A-Za-z0-9+/=_\-.@!]{8,}"',
        "硬编码密钥: {match}",
        "将密钥移至环境变量（System.getenv）或密钥管理服务。避免在源码中硬编码敏感信息。"
    ),
    "command_injection": (
        r'(?i)(?:Runtime\.getRuntime\(\)\.exec\s*\(\s*(?:.*\+)|'
        r'ProcessBuilder\s*\(\s*(?:.*\+))',
        "命令注入风险: {match}",
        "使用 ProcessBuilder 参数化命令，避免字符串拼接构造命令。对用户输入进行严格校验。"
    ),
    "sql_injection": (
        r'(?i)(?:["\'](?:SELECT|INSERT|UPDATE|DELETE|DROP)\b[^"\']*["\']\s*\+\s*\w+)',
        "SQL 注入风险: {match}",
        "使用 PreparedStatement 参数化查询（stmt.setString(1, value)），避免字符串拼接 SQL。"
    ),
    "insecure_deserialization": (
        r'(?i)(?:ObjectInputStream|XMLDecoder|SnakeYAML.*load\s*\()',
        "不安全反序列化: {match}",
        "避免对不可信数据使用 ObjectInputStream。使用 JSON 序列化，或对反序列化进行白名单校验。"
    ),
}

# 语言 -> 模式表映射
HIGH_RISK_PATTERNS_BY_LANG: dict[str, dict[str, tuple[str, str, str]]] = {
    "python": HIGH_RISK_PATTERNS_PYTHON,
    "go": HIGH_RISK_PATTERNS_GO,
    "typescript": HIGH_RISK_PATTERNS_TS_JS,
    "javascript": HIGH_RISK_PATTERNS_TS_JS,
    "java": HIGH_RISK_PATTERNS_JAVA,
}


class SecurityAuditorAgent(BaseReviewAgent):
    """安全审计 Agent。

    双层策略：
    1. 正则快速扫描（毫秒级），覆盖硬编码密钥、命令注入、不安全反序列化、SQL 注入
    2. LLM 深度推理（GLM-5.2），覆盖 XSS、路径遍历、SSRF、权限缺失等复杂场景
    """

    agent_type = "security"
    display_name = "安全审计Agent"

    # ---- 正则扫描 ----

    def _is_comment_or_env_line(self, line: str, language: str = "python") -> bool:
        """判断是否为注释行或环境变量读取行（应排除）。

        支持多语言注释语法：
        - Python: # 开头
        - Go/TS/JS/Java: // 或 /* 开头

        Args:
            line: 单行代码文本
            language: 编程语言

        Returns:
            True 表示应排除
        """
        stripped = line.strip()

        # 注释行（多语言）
        if language == "python":
            if stripped.startswith("#"):
                return True
        else:
            # Go/TS/JS/Java: // 或 /* 或 *
            if stripped.startswith(("//", "/*", "*")):
                return True

        # 环境变量读取（各语言）
        env_patterns = {
            "python": r'(?i)(?:os\.getenv|os\.environ(?:\[|\.get)|getenv\s*\()',
            "go": r'(?i)(?:os\.Getenv|viper\.Get)',
            "typescript": r'(?i)(?:process\.env|import\.meta\.env)',
            "javascript": r'(?i)(?:process\.env|require\s*\(\s*["\']dotenv)',
            "java": r'(?i)(?:System\.getenv|getProperty\s*\()',
        }
        env_re = env_patterns.get(language, env_patterns["python"])
        if re.search(env_re, stripped):
            return True

        # 类型注解中的字符串字面量（如 Literal["..."]）
        if re.match(r'^\s*\w+\s*:\s*str\s*=', stripped):
            return True
        return False

    def _pattern_scan(self, parsed_file: ParsedFile) -> list[dict]:
        """基于正则快速扫描高危安全模式。

        根据文件语言选择对应的模式表，排除注释行和环境变量读取等误报场景。

        Args:
            parsed_file: 已解析的文件

        Returns:
            发现的安全问题列表
        """
        issues: list[dict] = []
        lines = parsed_file.content.splitlines()
        language = parsed_file.language

        patterns = HIGH_RISK_PATTERNS_BY_LANG.get(language, {})
        if not patterns:
            return issues

        for category, (pattern, title_tmpl, suggestion) in patterns.items():
            for i, line in enumerate(lines):
                # 跳过注释行和环境变量读取
                if self._is_comment_or_env_line(line, language):
                    continue

                match = re.search(pattern, line)
                if match:
                    line_num = i + 1
                    matched_text = match.group(0)
                    # 截断过长匹配文本
                    if len(matched_text) > 80:
                        matched_text = matched_text[:80] + "..."

                    issues.append({
                        "agent_type": self.agent_type,
                        "severity": "high" if category != "sql_injection" else "critical",
                        "file_path": parsed_file.path,
                        "line_start": line_num,
                        "line_end": line_num,
                        "category": category,
                        "title": title_tmpl.format(match=matched_text),
                        "description": (
                            f"正则扫描发现第 {line_num} 行存在疑似 {category} 模式。"
                            f"匹配内容: {matched_text}"
                        ),
                        "suggestion": suggestion,
                        "code_snippet": line.strip()[:500],
                    })

        return issues

    # ---- LLM 深度分析 ----

    async def _llm_scan(self, parsed_file: ParsedFile) -> list[dict]:
        """使用推理模型（GLM-5.2）进行深度安全分析。

        专注于正则无法覆盖的复杂漏洞：XSS、路径遍历、SSRF、权限缺失等。

        Args:
            parsed_file: 已解析的文件

        Returns:
            LLM 发现的安全问题列表
        """
        content = parsed_file.content
        file_path = parsed_file.path
        language = parsed_file.language

        # 限制内容长度，避免超出 token 限制
        if len(content) > 12000:
            content = content[:12000] + "\n# ... (truncated)"

        prompt = (
            f"{SECURITY_PROMPT}\n\n"
            f"Analyze the following {language} file. "
            f"Focus on vulnerabilities that regex-based scanners might miss: "
            f"XSS, path traversal, SSRF, missing authorization, and complex injection patterns.\n\n"
            f"File path: {file_path}"
        )

        try:
            response = await self._llm_analyze(
                prompt=prompt,
                code_context=content,
                use_reasoning=True,  # 使用 GLM-5.2 推理模型
            )

            # 尝试提取 JSON 数组
            json_match = re.search(r"\[.*\]", response, re.DOTALL)
            if json_match:
                try:
                    findings = json.loads(json_match.group(0))
                except json.JSONDecodeError:
                    # 尝试修复常见的 JSON 问题
                    raw = json_match.group(0)
                    raw = re.sub(r",\s*]", "]", raw)  # trailing comma
                    try:
                        findings = json.loads(raw)
                    except json.JSONDecodeError:
                        findings = []
            else:
                findings = []

            # 添加文件路径信息
            for f in findings:
                f["agent_type"] = self.agent_type
                f["file_path"] = file_path
                f["line_start"] = f.get("line_start", 0)
                f["line_end"] = f.get("line_end", 0)
                f["code_snippet"] = f.get("code_snippet", "")
                # 确保 severity 有效
                if f.get("severity") not in ("critical", "high", "medium", "low", "info"):
                    f["severity"] = "medium"

            return findings

        except Exception as e:
            # LLM 失败时静默跳过，避免在问题列表中产生 llm_error 噪声
            print(f"[SecurityAuditor] LLM 分析失败，已跳过: {e}")
            return []

    # ---- 协作复查 ----

    async def collaborative_review(
        self,
        parsed_files: list[ParsedFile],
        signals: list[dict],
    ) -> list[dict]:
        """安全 Agent 协作复查。

        当收到架构 Agent 的循环依赖信号时，对相关模块的数据流做深度安全分析。
        第二轮使用 LOCAL tier 模型（use_reasoning=False），不挤占 CLOUD 预算。
        """
        if not signals:
            return []

        from app.config import get_settings
        max_files = get_settings().COLLABORATION_MAX_FILES_PER_REVIEW

        # 收集信号涉及的文件
        target_paths: set[str] = set()
        for sig in signals:
            for p in sig.get("file_paths", []):
                if p:
                    target_paths.add(p)

        relevant_files = [
            pf for pf in parsed_files
            if pf.path in target_paths and pf.language in SUPPORTED_LANGUAGES
        ][:max_files]

        if not relevant_files:
            return []

        collab_ctx = self._build_collab_context(signals)
        all_collab_findings: list[dict] = []

        for pf in relevant_files:
            content = pf.content
            if len(content) > 8000:
                content = content[:8000] + "\n# ... (truncated)"

            prompt = (
                f"{SECURITY_PROMPT}\n\n"
                f"Another agent has flagged this file as potentially risky. "
                f"Pay special attention to data flow, input validation, and "
                f"authorization boundaries in this module.\n\n"
                f"File path: {pf.path}{collab_ctx}"
            )

            try:
                response = await self._llm_analyze(
                    prompt=prompt,
                    code_context=content,
                    use_reasoning=False,  # 第二轮用本地模型，节省 CLOUD 预算
                )
                findings = self._parse_llm_response(response, pf)
                all_collab_findings.extend(findings)
            except Exception as e:
                print(f"[SecurityAuditor][Collab] 协作复查失败: {e}")

        return all_collab_findings

    def _parse_llm_response(self, response: str, parsed_file: ParsedFile) -> list[dict]:
        """解析 LLM 安全分析响应（复用 _llm_scan 的 JSON 解析逻辑）。"""
        json_match = re.search(r"\[.*\]", response, re.DOTALL)
        if not json_match:
            return []
        try:
            findings = json.loads(json_match.group(0))
        except json.JSONDecodeError:
            raw = re.sub(r",\s*]", "]", json_match.group(0))
            try:
                findings = json.loads(raw)
            except json.JSONDecodeError:
                return []
        for f in findings:
            f["agent_type"] = self.agent_type
            f["file_path"] = parsed_file.path
            f["line_start"] = f.get("line_start", 0)
            f["line_end"] = f.get("line_end", 0)
            f["code_snippet"] = f.get("code_snippet", "")
            if f.get("severity") not in ("critical", "high", "medium", "low", "info"):
                f["severity"] = "medium"
        return findings

    # ---- 主 entry point ----

    async def review(self, parsed_files: list[ParsedFile]) -> list[dict]:
        """执行安全审计。

        两步策略：
        1. 正则模式扫描（快速，覆盖常见模式）
        2. LLM 深度推理（覆盖复杂场景）

        两次结果合并，正则发现的模式不再送 LLM 重复分析。

        Args:
            parsed_files: ASTEngine 解析后的文件列表

        Returns:
            所有安全问题的列表
        """
        all_issues: list[dict] = []

        for pf in parsed_files:
            # 仅审查支持的语言
            if pf.language not in SUPPORTED_LANGUAGES:
                continue

            # 步骤 1: 正则模式扫描
            pattern_issues = self._pattern_scan(pf)
            all_issues.extend(pattern_issues)

            # 步骤 2: LLM 深度推理
            llm_issues = await self._llm_scan(pf)
            all_issues.extend(llm_issues)

        return all_issues
