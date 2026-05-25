"""Project Knowledge Cache — 会话间项目理解加速系统.

首次探索项目后生成压缩知识库，后续会话直接加载，避免重复理解。

存储位置：
  - 项目级：<workspace>/.quanora/cache/project_knowledge.json
  - Self-dev级：<quanora_repo>/.quanora/cache/self_knowledge.json

内容格式：
  {
    "version": 1,
    "generated_at": "2026-05-26T06:00:00Z",
    "project_root": "/path/to/project",
    "git_head": "abc1234",           // 可选，无 git 则 null
    "file_hash": "sha256:...",       // 关键文件集合的哈希，用于 stale 检测
    "summary": {
      "project_type": "python|node|...",
      "description": "一句话描述",
      "language": "Python",
      "framework": "FastAPI",
      "key_directories": { "src": "源代码", "tests": "测试" },
      "entry_points": ["main.py", "app.py"],
      "key_files": {
        "agent/prompts.py": "系统提示词定义",
        "agent/basic_agent.py": "Agent 主循环"
      },
      "dependencies": ["fastapi", "anthropic"],
      "conventions": ["使用 DDD 分层", "tool_result 统一返回"],
      "architecture_pattern": "DDD / MVC / ...",
      "important_patterns": ["工具注册在 __init__.py", "Skill 注入通过 context_manager"]
    },
    "context_boost": "一段可直接注入 system prompt 的压缩摘要文本，供 agent 快速理解项目",
    "stale_markers": ["pyproject.toml", "package.json"]  // 变更时触发重新生成
  }
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── Schema version ──────────────────────────────────────────────────────
CACHE_VERSION = 1

# ── Default stale markers ───────────────────────────────────────────────
DEFAULT_STALE_MARKERS = [
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "requirements.txt",
    "Pipfile",
    ".quanora/",
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_git_head(project_root: str) -> str | None:
    """获取项目 git HEAD commit hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()[:12]
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def _compute_file_hash(project_root: str, file_paths: list[str]) -> str:
    """计算一组文件的 SHA256 哈希，用于 stale 检测."""
    h = hashlib.sha256()
    for fp in file_paths:
        full = os.path.join(project_root, fp)
        if os.path.isfile(full):
            try:
                h.update(Path(full).read_bytes())
            except OSError:
                pass
        else:
            # 文件不存在也算一种状态
            h.update(b"<missing>")
    return f"sha256:{h.hexdigest()[:24]}"


def _collect_key_files(project_root: str, max_depth: int = 3) -> dict[str, str]:
    """收集项目关键文件及其简要描述.

    通过启发式规则识别关键文件：入口文件、配置文件、README 等。
    """
    key_files: dict[str, str] = {}
    root = Path(project_root)

    # 常见入口文件
    entry_candidates = [
        "main.py", "app.py", "manage.py", "run.py", "server.py",
        "index.ts", "index.js", "index.tsx", "index.jsx",
        "main.ts", "main.js", "main.go", "main.rs",
        "src/main.py", "src/app.py", "src/index.ts",
    ]
    for ec in entry_candidates:
        if (root / ec).is_file():
            key_files[ec] = "项目入口文件"

    # 配置文件
    config_candidates = [
        ("pyproject.toml", "Python 项目配置"),
        ("setup.py", "Python 包配置"),
        ("setup.cfg", "Python 包配置"),
        ("requirements.txt", "Python 依赖"),
        ("package.json", "Node.js 项目配置"),
        ("tsconfig.json", "TypeScript 配置"),
        ("Cargo.toml", "Rust 项目配置"),
        ("go.mod", "Go 模块配置"),
        (".env.example", "环境变量示例"),
        ("Dockerfile", "容器构建配置"),
        ("docker-compose.yml", "容器编排配置"),
    ]
    for fname, desc in config_candidates:
        if (root / fname).is_file():
            key_files[fname] = desc

    # README
    for readme in ["README.md", "README.rst", "README.txt", "README"]:
        if (root / readme).is_file():
            key_files[readme] = "项目说明文档"
            break

    # .quanora 目录下的关键文件
    quanora_dir = root / ".quanora"
    if quanora_dir.is_dir():
        for skill_dir in quanora_dir.rglob("SKILL.md"):
            rel = str(skill_dir.relative_to(root))
            key_files[rel] = "Quanora Skill 定义"
        for plan_file in quanora_dir.rglob("plan.json"):
            rel = str(plan_file.relative_to(root))
            key_files[rel] = "Quanora 计划文件"

    return key_files


def _detect_project_type(project_root: str) -> dict[str, Any]:
    """自动检测项目类型、语言、框架等元信息."""
    root = Path(project_root)
    info: dict[str, Any] = {
        "project_type": "unknown",
        "language": "unknown",
        "framework": "",
        "dependencies": [],
    }

    # Python
    if (root / "pyproject.toml").is_file() or (root / "setup.py").is_file():
        info["project_type"] = "python"
        info["language"] = "Python"
        # 尝试提取依赖
        try:
            pyproject = root / "pyproject.toml"
            if pyproject.is_file():
                content = pyproject.read_text(encoding="utf-8", errors="ignore")
                for kw in ["fastapi", "flask", "django", "pydantic", "anthropic", "openai"]:
                    if kw in content.lower():
                        info["framework"] = info.get("framework", "") or kw
        except OSError:
            pass
        # requirements.txt
        req_file = root / "requirements.txt"
        if req_file.is_file():
            try:
                deps = [
                    line.strip().split("==")[0].split(">=")[0].split("<=")[0]
                    for line in req_file.read_text(encoding="utf-8", errors="ignore").splitlines()
                    if line.strip() and not line.startswith("#")
                ]
                info["dependencies"] = deps[:30]  # 限制数量
            except OSError:
                pass

    # Node.js
    elif (root / "package.json").is_file():
        info["project_type"] = "node"
        info["language"] = "JavaScript/TypeScript"
        try:
            pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))
            deps = list(pkg.get("dependencies", {}).keys()) + list(pkg.get("devDependencies", {}).keys())
            info["dependencies"] = deps[:30]
            for fw in ["next", "react", "vue", "express", "nestjs"]:
                if fw in deps or fw in pkg.get("devDependencies", {}):
                    info["framework"] = fw
                    break
        except (json.JSONDecodeError, OSError):
            pass

    # Go
    elif (root / "go.mod").is_file():
        info["project_type"] = "go"
        info["language"] = "Go"

    # Rust
    elif (root / "Cargo.toml").is_file():
        info["project_type"] = "rust"
        info["language"] = "Rust"

    return info


def _collect_key_directories(project_root: str, max_depth: int = 2) -> dict[str, str]:
    """收集关键目录及其用途描述."""
    root = Path(project_root)
    dirs: dict[str, str] = {}

    known_dirs = {
        "src": "源代码",
        "lib": "库代码",
        "app": "应用代码",
        "agent": "Agent 核心逻辑",
        "tests": "测试代码",
        "test": "测试代码",
        "docs": "文档",
        "scripts": "脚本工具",
        "data": "数据文件",
        "config": "配置",
        "migrations": "数据库迁移",
        "models": "数据模型",
        "views": "视图层",
        "controllers": "控制器",
        "services": "业务服务层",
        "infrastructure": "基础设施层",
        "domain": "领域层",
        "application": "应用层",
        "interfaces": "接口层",
        "api": "API 接口",
        "utils": "工具函数",
        "helpers": "辅助函数",
        "core": "核心模块",
        "plugins": "插件",
        "extensions": "扩展",
        "public": "静态资源",
        "static": "静态文件",
        "templates": "模板文件",
        ".quanora": "Quanora 配置和 Skills",
    }

    for d in root.iterdir():
        if d.is_dir() and not d.name.startswith("."):
            if d.name in known_dirs:
                dirs[d.name] = known_dirs[d.name]
            elif d.name in ("__pycache__", "node_modules", ".git", "venv", ".venv", "dist", "build"):
                continue
            else:
                # 检查子目录是否有内容
                try:
                    has_py = any(d.rglob("*.py"))
                    has_ts = any(d.rglob("*.ts"))
                    if has_py or has_ts:
                        dirs[d.name] = "代码目录"
                except (OSError, PermissionError):
                    pass

    return dirs


def generate_knowledge_cache(
    project_root: str,
    *,
    description: str = "",
    architecture_pattern: str = "",
    conventions: list[str] | None = None,
    important_patterns: list[str] | None = None,
    key_files_override: dict[str, str] | None = None,
    context_boost: str = "",
) -> dict[str, Any]:
    """生成项目知识缓存.

    此函数由 agent 调用，在首次探索项目后将理解结果压缩为结构化缓存。
    agent 应该在探索完项目后，将它的理解作为参数传入。

    Args:
        project_root: 项目根目录绝对路径
        description: 一句话项目描述（agent 总结）
        architecture_pattern: 架构模式（DDD / MVC / ...）
        conventions: 项目约定列表
        important_patterns: 重要模式列表
        key_files_override: 手动指定的关键文件映射（覆盖自动检测）
        context_boost: 可直接注入 system prompt 的压缩摘要

    Returns:
        生成的知识缓存 dict
    """
    project_root = os.path.abspath(project_root)

    # 自动检测元信息
    meta = _detect_project_type(project_root)
    auto_key_files = _collect_key_files(project_root)
    auto_dirs = _collect_key_directories(project_root)
    git_head = _get_git_head(project_root)

    # 合并：手动覆盖 > 自动检测
    key_files = {**auto_key_files, **(key_files_override or {})}

    # 计算 stale 检测哈希
    stale_files = [f for f in DEFAULT_STALE_MARKERS if os.path.isfile(os.path.join(project_root, f))]
    # 也包含 .quanora/ 下的关键文件
    quanora_dir = os.path.join(project_root, ".quanora")
    if os.path.isdir(quanora_dir):
        for root_d, _dirs, files in os.walk(quanora_dir):
            for f in files:
                if f.endswith((".md", ".json")):
                    rel = os.path.relpath(os.path.join(root_d, f), project_root)
                    stale_files.append(rel)
    file_hash = _compute_file_hash(project_root, stale_files)

    cache: dict[str, Any] = {
        "version": CACHE_VERSION,
        "generated_at": _utc_now_iso(),
        "project_root": project_root,
        "git_head": git_head,
        "file_hash": file_hash,
        "summary": {
            "project_type": meta["project_type"],
            "description": description or f"{meta['language']} 项目",
            "language": meta["language"],
            "framework": meta["framework"],
            "key_directories": auto_dirs,
            "entry_points": [k for k, v in key_files.items() if "入口" in v],
            "key_files": key_files,
            "dependencies": meta["dependencies"],
            "conventions": conventions or [],
            "architecture_pattern": architecture_pattern,
            "important_patterns": important_patterns or [],
        },
        "context_boost": context_boost,
        "stale_markers": stale_files,
    }

    return cache


def load_knowledge_cache(cache_path: str) -> dict[str, Any] | None:
    """从磁盘加载知识缓存.

    Returns:
        缓存 dict，或 None（文件不存在或格式无效）
    """
    path = Path(cache_path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != CACHE_VERSION:
            return None
        return data
    except (json.JSONDecodeError, OSError):
        return None


def save_knowledge_cache(cache: dict[str, Any], cache_path: str) -> None:
    """将知识缓存保存到磁盘."""
    path = Path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def is_cache_stale(cache: dict[str, Any], project_root: str) -> bool:
    """检测缓存是否过期.

    过期条件：
    1. git HEAD 变更
    2. stale_markers 中的文件哈希变更
    """
    project_root = os.path.abspath(project_root)

    # 检查 git HEAD
    current_head = _get_git_head(project_root)
    cached_head = cache.get("git_head")
    if current_head and cached_head and current_head != cached_head:
        return True

    # 检查文件哈希
    stale_markers = cache.get("stale_markers", [])
    if stale_markers:
        current_hash = _compute_file_hash(project_root, stale_markers)
        if current_hash != cache.get("file_hash"):
            return True

    return False


def build_context_boost_from_cache(cache: dict[str, Any]) -> str:
    """从缓存生成可注入 system prompt 的压缩文本.

    这是最关键的函数——它决定了 agent 在新会话中能获得多少项目上下文。
    """
    s = cache.get("summary", {})
    lines: list[str] = []

    lines.append(f"## Project Knowledge Cache ({cache.get('project_root', 'unknown')})")
    lines.append(f"生成时间: {cache.get('generated_at', 'unknown')}")

    if s.get("description"):
        lines.append(f"\n**项目描述**: {s['description']}")
    if s.get("language"):
        lines.append(f"**语言**: {s['language']}")
    if s.get("framework"):
        lines.append(f"**框架**: {s['framework']}")
    if s.get("architecture_pattern"):
        lines.append(f"**架构模式**: {s['architecture_pattern']}")

    # 关键目录
    dirs = s.get("key_directories", {})
    if dirs:
        lines.append("\n### 目录结构")
        for d, desc in dirs.items():
            lines.append(f"- `{d}/` — {desc}")

    # 入口文件
    entries = s.get("entry_points", [])
    if entries:
        lines.append(f"\n### 入口文件: {', '.join(f'`{e}`' for e in entries)}")

    # 关键文件
    kf = s.get("key_files", {})
    if kf:
        lines.append("\n### 关键文件")
        for f, desc in kf.items():
            lines.append(f"- `{f}` — {desc}")

    # 重要模式
    patterns = s.get("important_patterns", [])
    if patterns:
        lines.append("\n### 重要模式")
        for p in patterns:
            lines.append(f"- {p}")

    # 约定
    convs = s.get("conventions", [])
    if convs:
        lines.append("\n### 项目约定")
        for c in convs:
            lines.append(f"- {c}")

    # 依赖
    deps = s.get("dependencies", [])
    if deps:
        lines.append(f"\n### 核心依赖: {', '.join(deps[:15])}")

    # 如果 agent 提供了自定义的 context_boost，直接使用
    custom_boost = cache.get("context_boost", "")
    if custom_boost:
        lines.append(f"\n### Agent 摘要\n{custom_boost}")

    return "\n".join(lines)


def get_cache_path(project_root: str, *, self_dev: bool = False) -> str:
    """获取缓存文件路径.

    Args:
        project_root: 项目根目录
        self_dev: 是否是 self-dev 模式
    """
    root = Path(os.path.abspath(project_root))
    if self_dev:
        return str(root / ".quanora" / "cache" / "self_knowledge.json")
    return str(root / ".quanora" / "cache" / "project_knowledge.json")
