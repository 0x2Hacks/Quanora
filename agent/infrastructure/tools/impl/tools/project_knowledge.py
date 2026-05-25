"""Project Knowledge Cache tools — 供 agent 调用的工具函数.

提供两个工具：
1. generate_project_knowledge — 首次探索项目后生成知识缓存
2. load_project_knowledge — 加载已有缓存，返回项目上下文摘要
"""

from __future__ import annotations

import json as _json
import os
from typing import Any

from agent.domain import tool_error, tool_ok
from agent.infrastructure.persistence.project_knowledge_cache import (
    build_context_boost_from_cache,
    generate_knowledge_cache,
    get_cache_path,
    is_cache_stale,
    load_knowledge_cache,
    save_knowledge_cache,
)


def generate_project_knowledge(
    project_root: str,
    description: str = "",
    architecture_pattern: str = "",
    conventions: str = "",
    important_patterns: str = "",
    key_files_override: str = "",
    context_boost: str = "",
    self_dev: bool = False,
) -> str:
    """生成项目知识缓存并保存到磁盘。agent 首次探索完项目后调用此工具，将理解结果压缩为结构化缓存，后续会话可直接加载。

    Args:
        project_root: 项目根目录绝对路径
        description: 一句话项目描述（agent 总结）
        architecture_pattern: 架构模式，如 DDD / MVC / 分层架构
        conventions: 项目约定列表，JSON 数组字符串，如 '["使用DDD分层","统一返回格式"]'
        important_patterns: 重要模式列表，JSON 数组字符串，如 '["工具注册在__init__.py"]'
        key_files_override: 手动指定的关键文件映射，JSON 对象字符串，如 '{"app.py":"主入口"}'
        context_boost: 可直接注入 system prompt 的压缩摘要文本
        self_dev: 是否为 self-dev 模式
    """
    # 解析 JSON 字符串参数
    conv_list: list[str] = []
    if conventions:
        try:
            conv_list = _json.loads(conventions)
        except _json.JSONDecodeError:
            conv_list = [conventions]

    pattern_list: list[str] = []
    if important_patterns:
        try:
            pattern_list = _json.loads(important_patterns)
        except _json.JSONDecodeError:
            pattern_list = [important_patterns]

    kf_dict: dict[str, str] = {}
    if key_files_override:
        try:
            kf_dict = _json.loads(key_files_override)
        except _json.JSONDecodeError:
            kf_dict = {}

    try:
        cache = generate_knowledge_cache(
            project_root,
            description=description,
            architecture_pattern=architecture_pattern,
            conventions=conv_list,
            important_patterns=pattern_list,
            key_files_override=kf_dict or None,
            context_boost=context_boost,
        )
        cache_path = get_cache_path(project_root, self_dev=self_dev)
        save_knowledge_cache(cache, cache_path)

        return tool_ok(
            "generate_project_knowledge",
            {
                "cache_path": cache_path,
                "key_files_count": len(cache["summary"]["key_files"]),
                "directories_count": len(cache["summary"]["key_directories"]),
                "git_head": cache.get("git_head"),
                "stale_markers_count": len(cache.get("stale_markers", [])),
            },
            meta={"hint": "缓存已生成。后续会话将自动加载，无需重复探索。"},
        )
    except Exception as exc:
        return tool_error("generate_project_knowledge", str(exc), error_type=type(exc).__name__)


def load_project_knowledge(
    project_root: str,
    self_dev: bool = False,
) -> str:
    """加载项目知识缓存。如果缓存存在且未过期，返回项目上下文摘要，agent 可直接使用该摘要理解项目。

    Args:
        project_root: 项目根目录绝对路径
        self_dev: 是否为 self-dev 模式
    """
    cache_path = get_cache_path(project_root, self_dev=self_dev)
    cache = load_knowledge_cache(cache_path)

    if cache is None:
        return tool_ok(
            "load_project_knowledge",
            {"status": "miss", "cache_path": cache_path},
            meta={"hint": "缓存不存在。请先探索项目（list_files / read_file / grep），然后调用 generate_project_knowledge 生成缓存。"},
        )

    # 检测是否过期
    stale = is_cache_stale(cache, project_root)

    if stale:
        return tool_ok(
            "load_project_knowledge",
            {
                "status": "stale",
                "cache_path": cache_path,
                "old_git_head": cache.get("git_head"),
                "generated_at": cache.get("generated_at"),
            },
            meta={"hint": "缓存已过期（git HEAD 或关键文件变更）。建议重新探索项目并更新缓存。"},
        )

    # 缓存有效，返回上下文摘要
    context_boost = build_context_boost_from_cache(cache)

    return tool_ok(
        "load_project_knowledge",
        {
            "status": "hit",
            "cache_path": cache_path,
            "context_boost": context_boost,
            "generated_at": cache.get("generated_at"),
            "git_head": cache.get("git_head"),
        },
        meta={"hint": "缓存有效。可直接使用 context_boost 理解项目，无需重新探索。"},
    )
