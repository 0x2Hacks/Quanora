"""Tests for Project Knowledge Cache system.

Tests cover:
1. Core module: generate, load, save, stale detection, context_boost generation
2. Tool handlers: generate_project_knowledge, load_project_knowledge
3. Context manager integration: _build_knowledge_cache_messages
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.infrastructure.persistence.project_knowledge_cache import (
    CACHE_VERSION,
    build_context_boost_from_cache,
    generate_knowledge_cache,
    get_cache_path,
    is_cache_stale,
    load_knowledge_cache,
    save_knowledge_cache,
)
from agent.infrastructure.tools.impl.tools.project_knowledge import (
    generate_project_knowledge,
    load_project_knowledge,
)


# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_project(tmp_path):
    """创建一个临时项目目录，包含基本文件结构."""
    # 创建目录结构
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".quanora" / "skills" / "test_skill").mkdir(parents=True)

    # 创建文件
    (tmp_path / "main.py").write_text("print('hello')")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    (tmp_path / "requirements.txt").write_text("fastapi\nanthropic\n")
    (tmp_path / "README.md").write_text("# Test Project")
    (tmp_path / "src" / "app.py").write_text("from fastapi import FastAPI")
    (tmp_path / ".quanora" / "skills" / "test_skill" / "SKILL.md").write_text("---\nname: test\n---\nbody")

    return tmp_path


@pytest.fixture
def git_project(tmp_project):
    """在临时项目中初始化 git."""
    import subprocess
    subprocess.run(["git", "init"], cwd=str(tmp_project), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(tmp_project), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_project), capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_project), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_project), capture_output=True)
    return tmp_project


# ── Core Module Tests ───────────────────────────────────────────────────

class TestGenerateKnowledgeCache:
    """测试 generate_knowledge_cache 核心函数."""

    def test_basic_generation(self, tmp_project):
        """基本生成测试."""
        cache = generate_knowledge_cache(
            str(tmp_project),
            description="测试项目",
            architecture_pattern="MVC",
            conventions=["使用 pytest"],
            important_patterns=["入口在 main.py"],
            context_boost="这是一个测试项目",
        )

        assert cache["version"] == CACHE_VERSION
        assert cache["project_root"] == str(tmp_project)
        assert cache["summary"]["description"] == "测试项目"
        assert cache["summary"]["language"] == "Python"
        assert cache["summary"]["architecture_pattern"] == "MVC"
        assert "使用 pytest" in cache["summary"]["conventions"]
        assert "入口在 main.py" in cache["summary"]["important_patterns"]
        assert cache["context_boost"] == "这是一个测试项目"

    def test_auto_detect_python_project(self, tmp_project):
        """自动检测 Python 项目类型."""
        cache = generate_knowledge_cache(str(tmp_project))

        assert cache["summary"]["project_type"] == "python"
        assert cache["summary"]["language"] == "Python"

    def test_auto_detect_key_files(self, tmp_project):
        """自动检测关键文件."""
        cache = generate_knowledge_cache(str(tmp_project))
        key_files = cache["summary"]["key_files"]

        assert "main.py" in key_files
        assert "pyproject.toml" in key_files
        assert "requirements.txt" in key_files
        assert "README.md" in key_files

    def test_auto_detect_directories(self, tmp_project):
        """自动检测关键目录."""
        cache = generate_knowledge_cache(str(tmp_project))
        dirs = cache["summary"]["key_directories"]

        assert "src" in dirs
        assert "tests" in dirs

    def test_dependencies_detected(self, tmp_project):
        """检测依赖."""
        cache = generate_knowledge_cache(str(tmp_project))
        deps = cache["summary"]["dependencies"]

        assert "fastapi" in deps
        assert "anthropic" in deps

    def test_git_head_detected(self, git_project):
        """检测 git HEAD."""
        cache = generate_knowledge_cache(str(git_project))

        assert cache["git_head"] is not None
        assert len(cache["git_head"]) == 12

    def test_file_hash_computed(self, tmp_project):
        """计算文件哈希."""
        cache = generate_knowledge_cache(str(tmp_project))

        assert cache["file_hash"].startswith("sha256:")

    def test_stale_markers_populated(self, tmp_project):
        """填充 stale markers."""
        cache = generate_knowledge_cache(str(tmp_project))

        assert len(cache["stale_markers"]) > 0

    def test_node_project_detection(self, tmp_path):
        """检测 Node.js 项目."""
        (tmp_path / "package.json").write_text('{"name": "test", "dependencies": {"express": "^4.0.0"}}')
        cache = generate_knowledge_cache(str(tmp_path))

        assert cache["summary"]["project_type"] == "node"
        assert cache["summary"]["language"] == "JavaScript/TypeScript"
        assert "express" in cache["summary"]["dependencies"]

    def test_go_project_detection(self, tmp_path):
        """检测 Go 项目."""
        (tmp_path / "go.mod").write_text("module test\n")
        cache = generate_knowledge_cache(str(tmp_path))

        assert cache["summary"]["project_type"] == "go"

    def test_key_files_override(self, tmp_project):
        """手动指定关键文件覆盖自动检测."""
        cache = generate_knowledge_cache(
            str(tmp_project),
            key_files_override={"custom.py": "自定义文件"},
        )

        assert "custom.py" in cache["summary"]["key_files"]


class TestLoadSaveKnowledgeCache:
    """测试加载和保存."""

    def test_save_and_load_roundtrip(self, tmp_project):
        """保存后加载的往返测试."""
        cache = generate_knowledge_cache(
            str(tmp_project),
            description="往返测试",
        )
        cache_path = os.path.join(str(tmp_project), ".quanora", "cache", "test.json")
        save_knowledge_cache(cache, cache_path)

        loaded = load_knowledge_cache(cache_path)

        assert loaded is not None
        assert loaded["version"] == cache["version"]
        assert loaded["summary"]["description"] == "往返测试"

    def test_load_nonexistent(self, tmp_path):
        """加载不存在的文件返回 None."""
        result = load_knowledge_cache(str(tmp_path / "nonexistent.json"))

        assert result is None

    def test_load_invalid_json(self, tmp_path):
        """加载无效 JSON 返回 None."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json")
        result = load_knowledge_cache(str(bad_file))

        assert result is None

    def test_load_wrong_version(self, tmp_path):
        """加载版本不匹配返回 None."""
        cache_file = tmp_path / "wrong_version.json"
        cache_file.write_text(json.dumps({"version": 999}))
        result = load_knowledge_cache(str(cache_file))

        assert result is None


class TestIsCacheStale:
    """测试 stale 检测."""

    def test_not_stale_when_unchanged(self, git_project):
        """未变更时不标记为 stale."""
        cache = generate_knowledge_cache(str(git_project))

        assert not is_cache_stale(cache, str(git_project))

    def test_stale_after_git_commit(self, git_project):
        """git commit 后标记为 stale."""
        import subprocess
        cache = generate_knowledge_cache(str(git_project))

        # 做一次新的 commit
        (git_project / "new_file.txt").write_text("new")
        subprocess.run(["git", "add", "-A"], cwd=str(git_project), capture_output=True)
        subprocess.run(["git", "commit", "-m", "new"], cwd=str(git_project), capture_output=True)

        assert is_cache_stale(cache, str(git_project))

    def test_stale_after_file_change(self, tmp_project):
        """关键文件变更后标记为 stale."""
        cache = generate_knowledge_cache(str(tmp_project))

        # 修改 pyproject.toml
        (tmp_project / "pyproject.toml").write_text("[project]\nname = 'changed'\n")

        assert is_cache_stale(cache, str(tmp_project))

    def test_not_stale_no_git(self, tmp_project):
        """无 git 时，仅文件哈希检测."""
        cache = generate_knowledge_cache(str(tmp_project))
        assert not is_cache_stale(cache, str(tmp_project))


class TestBuildContextBoost:
    """测试 context_boost 生成."""

    def test_basic_boost(self):
        """基本 boost 生成."""
        cache = {
            "project_root": "/test/project",
            "generated_at": "2026-05-26T06:00:00Z",
            "summary": {
                "description": "测试项目",
                "language": "Python",
                "framework": "FastAPI",
                "architecture_pattern": "DDD",
                "key_directories": {"src": "源代码", "tests": "测试"},
                "entry_points": ["main.py"],
                "key_files": {"main.py": "入口"},
                "important_patterns": ["DDD 分层"],
                "conventions": ["snake_case"],
                "dependencies": ["fastapi"],
            },
            "context_boost": "Agent 自定义摘要",
        }

        boost = build_context_boost_from_cache(cache)

        assert "Project Knowledge Cache" in boost
        assert "测试项目" in boost
        assert "Python" in boost
        assert "FastAPI" in boost
        assert "DDD" in boost
        assert "`src/`" in boost
        assert "`main.py`" in boost
        assert "DDD 分层" in boost
        assert "snake_case" in boost
        assert "Agent 自定义摘要" in boost

    def test_minimal_cache(self):
        """最小缓存也能生成 boost."""
        cache = {"summary": {}}

        boost = build_context_boost_from_cache(cache)

        assert "Project Knowledge Cache" in boost


class TestGetCachePath:
    """测试缓存路径生成."""

    def test_project_mode(self, tmp_path):
        """项目模式路径."""
        path = get_cache_path(str(tmp_path))
        assert path.endswith(".quanora/cache/project_knowledge.json")

    def test_self_dev_mode(self, tmp_path):
        """Self-dev 模式路径."""
        path = get_cache_path(str(tmp_path), self_dev=True)
        assert path.endswith(".quanora/cache/self_knowledge.json")


# ── Tool Handler Tests ──────────────────────────────────────────────────

class TestGenerateProjectKnowledgeTool:
    """测试 generate_project_knowledge 工具处理器."""

    def test_basic_generation(self, tmp_project):
        """基本工具调用."""
        result = generate_project_knowledge(
            project_root=str(tmp_project),
            description="工具测试项目",
            architecture_pattern="MVC",
            context_boost="这是工具测试",
        )

        assert '"ok": true' in result or '"tool": "generate_project_knowledge"' in result
        # 验证缓存文件已创建
        cache_path = get_cache_path(str(tmp_project))
        assert os.path.isfile(cache_path)

    def test_with_json_params(self, tmp_project):
        """带 JSON 参数的调用."""
        result = generate_project_knowledge(
            project_root=str(tmp_project),
            conventions='["约定1", "约定2"]',
            important_patterns='["模式1"]',
            key_files_override='{"custom.py": "自定义"}',
        )

        # 验证缓存
        cache_path = get_cache_path(str(tmp_project))
        cache = load_knowledge_cache(cache_path)
        assert cache is not None
        assert "约定1" in cache["summary"]["conventions"]
        assert "模式1" in cache["summary"]["important_patterns"]
        assert "custom.py" in cache["summary"]["key_files"]

    def test_self_dev_mode(self, tmp_project):
        """Self-dev 模式."""
        result = generate_project_knowledge(
            project_root=str(tmp_project),
            self_dev=True,
        )

        cache_path = get_cache_path(str(tmp_project), self_dev=True)
        assert os.path.isfile(cache_path)


class TestLoadProjectKnowledgeTool:
    """测试 load_project_knowledge 工具处理器."""

    def test_miss_when_no_cache(self, tmp_project):
        """无缓存时返回 miss."""
        result = load_project_knowledge(project_root=str(tmp_project))

        assert "miss" in result

    def test_hit_when_cache_valid(self, tmp_project):
        """有效缓存时返回 hit."""
        # 先生成缓存
        generate_project_knowledge(
            project_root=str(tmp_project),
            description="加载测试",
        )

        result = load_project_knowledge(project_root=str(tmp_project))

        assert "hit" in result
        assert "加载测试" in result

    def test_stale_when_cache_expired(self, git_project):
        """过期缓存时返回 stale."""
        # 生成缓存
        generate_project_knowledge(project_root=str(git_project))

        # 修改 git HEAD
        import subprocess
        (git_project / "new.txt").write_text("change")
        subprocess.run(["git", "add", "-A"], cwd=str(git_project), capture_output=True)
        subprocess.run(["git", "commit", "-m", "change"], cwd=str(git_project), capture_output=True)

        result = load_project_knowledge(project_root=str(git_project))

        assert "stale" in result


# ── Context Manager Integration Tests ───────────────────────────────────

class TestKnowledgeCacheContextIntegration:
    """测试 Context Manager 中的知识缓存集成."""

    def test_build_knowledge_cache_messages_miss(self, tmp_project):
        """无缓存时返回空消息列表."""
        from agent.application.services.context_manager import ContextManager

        # Mock Config.WORKSPACE_ROOT - Config is imported inside the method
        with patch("agent.infrastructure.config.Config.WORKSPACE_ROOT", str(tmp_project)):
            cm = ContextManager.__new__(ContextManager)
            messages, stats = cm._build_knowledge_cache_messages()

            assert stats["knowledge_cache_status"] == "miss"
            assert len(messages) == 0

    def test_build_knowledge_cache_messages_hit(self, tmp_project):
        """有效缓存时注入消息."""
        from agent.application.services.context_manager import ContextManager

        # 先生成缓存
        generate_project_knowledge(
            project_root=str(tmp_project),
            description="集成测试项目",
        )

        with patch("agent.infrastructure.config.Config.WORKSPACE_ROOT", str(tmp_project)):
            cm = ContextManager.__new__(ContextManager)
            messages, stats = cm._build_knowledge_cache_messages()

            assert stats["knowledge_cache_status"] == "hit"
            assert len(messages) == 1
            assert messages[0]["role"] == "system"
            assert "集成测试项目" in messages[0]["content"]

    def test_build_knowledge_cache_messages_stale(self, git_project):
        """过期缓存时注入带警告的消息."""
        from agent.application.services.context_manager import ContextManager

        # 生成缓存
        generate_project_knowledge(project_root=str(git_project))

        # 修改 git HEAD
        import subprocess
        (git_project / "new.txt").write_text("change")
        subprocess.run(["git", "add", "-A"], cwd=str(git_project), capture_output=True)
        subprocess.run(["git", "commit", "-m", "change"], cwd=str(git_project), capture_output=True)

        with patch("agent.infrastructure.config.Config.WORKSPACE_ROOT", str(git_project)):
            cm = ContextManager.__new__(ContextManager)
            messages, stats = cm._build_knowledge_cache_messages()

            assert stats["knowledge_cache_status"] == "stale"
            assert len(messages) == 1
            assert "可能已过时" in messages[0]["content"]
