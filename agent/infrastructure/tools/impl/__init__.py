"""Default tool implementations and generated schemas."""

from __future__ import annotations

from typing import Any, Callable

from .core import build_tool_schemas
from .tools import (
    bash,
    edit_file,
    fetch_web_page,
    grep,
    kill_shell,
    list_files,
    plan_close,
    plan_create,
    plan_get,
    plan_link_dependency,
    plan_next,
    plan_reorder,
    plan_update_step,
    read_file,
    search_web,
    write_file,
    # WorldQuant Brain
    wq_build_generation_prompt,
    wq_crossover_alpha,
    wq_distill_insight,
    wq_evaluate_alpha,
    wq_list_data_fields,
    wq_list_directions,
    wq_list_library,
    wq_list_my_alphas,
    wq_list_operators,
    wq_login,
    wq_memory_snapshot,
    wq_mutate_alpha,
    wq_simulate_alpha,
    wq_submit_alpha,
)

TOOLS: dict[str, Callable] = {
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "list_files": list_files,
    "grep": grep,
    "bash": bash,
    "kill_shell": kill_shell,
    "plan_create": plan_create,
    "plan_get": plan_get,
    "plan_update_step": plan_update_step,
    "plan_link_dependency": plan_link_dependency,
    "plan_reorder": plan_reorder,
    "plan_next": plan_next,
    "plan_close": plan_close,
    "search_web": search_web,
    "fetch_web_page": fetch_web_page,
    # WorldQuant Brain — 自动挖因子
    "wq_login": wq_login,
    "wq_list_operators": wq_list_operators,
    "wq_list_data_fields": wq_list_data_fields,
    "wq_list_directions": wq_list_directions,
    "wq_memory_snapshot": wq_memory_snapshot,
    "wq_build_generation_prompt": wq_build_generation_prompt,
    "wq_simulate_alpha": wq_simulate_alpha,
    "wq_evaluate_alpha": wq_evaluate_alpha,
    "wq_distill_insight": wq_distill_insight,
    "wq_list_library": wq_list_library,
    "wq_list_my_alphas": wq_list_my_alphas,
    "wq_submit_alpha": wq_submit_alpha,
    "wq_mutate_alpha": wq_mutate_alpha,
    "wq_crossover_alpha": wq_crossover_alpha,
}

_TOOL_SCHEMA_META: dict[str, dict[str, Any]] = {
    "read_file": {
        "description": "读取文本文件内容，支持行号和分页读取。Agent应通过此工具查看代码上下文。",
        "param_descriptions": {
            "file_path": "文件绝对或相对路径",
            "offset": "起始行号（默认 1）",
            "limit": "最多读取的行数（默认 1000 行，避免大文件超出上下文）",
        },
    },
    "write_file": {
        "description": "写入内容到文件（警告：此操作会完全覆盖原文件。修改已有大文件时请使用 edit_file）",
        "param_descriptions": {"file_path": "文件路径", "content": "内容"},
    },
    "edit_file": {
        "description": "精准替换文件中的文本块 (Search and Replace)。适用于修改已有文件，避免输出整个文件。必须保证 old_str 与文件中的文本完全一致（包括空格和缩进）。如果匹配到多处，将拒绝替换。",
        "param_descriptions": {
            "file_path": "文件绝对或相对路径",
            "old_str": "需要被替换的原文块。建议包含上下文以确保唯一。",
            "new_str": "用来替换 old_str 的新文本块。",
        },
    },
    "grep": {
        "description": "在文件中搜索正则表达式模式 (Search)。返回匹配的文件路径、行号和内容。这是查找代码定义、引用或特定模式的首选工具。",
        "param_descriptions": {
            "pattern": "要搜索的正则表达式 (Python re syntax)",
            "path": "搜索的根目录 (默认为当前目录 .)",
            "glob_pattern": "文件匹配模式 (如 **/*.py, src/*.ts)。默认为 **/*。",
            "case_sensitive": "是否区分大小写 (默认为 False)",
            "max_results": "最大返回结果数 (默认为 50)",
        },
    },
    "list_files": {
        "description": "列出目录中的文件（树形结构）",
        "param_descriptions": {
            "directory": "目录路径",
            "pattern": "文件匹配模式",
            "recursive": "是否递归",
            "max_depth": "最大深度",
        },
    },
    "bash": {
        "description": "执行 Shell 命令 (支持 cd 保持目录状态；部分危险命令需要用户确认或本地启用不安全模式)",
        "param_descriptions": {"command": "要执行的命令 (如: ls -la, git status)"},
    },
    "kill_shell": {"description": "重置 Shell 会话状态"},
    "plan_create": {
        "description": "创建一个 DAG 计划（支持并行步骤与阻塞）。",
        "param_descriptions": {
            "title": "计划标题",
            "goal": "计划目标",
            "steps": "步骤数组，每项含 title/depends_on/priority 等字段",
            "expected_version": "可选版本号。已有计划时用于乐观锁校验。",
        },
    },
    "plan_get": {"description": "读取当前会话计划。", "param_descriptions": {"plan_id": "可选计划 ID，用于校验读取对象。"}},
    "plan_update_step": {
        "description": "更新步骤状态或字段（严格状态机 + 乐观锁）。",
        "param_descriptions": {
            "step_id": "步骤 ID",
            "patch": "变更对象（如 status/blocked_reason/priority 等）",
            "expected_version": "必填版本号，用于乐观锁",
        },
    },
    "plan_link_dependency": {
        "description": "更新步骤依赖关系并校验环路。",
        "param_descriptions": {
            "step_id": "步骤 ID",
            "depends_on": "依赖步骤 ID 数组",
            "expected_version": "必填版本号，用于乐观锁",
        },
    },
    "plan_reorder": {
        "description": "重排步骤展示顺序（不改变依赖）。",
        "param_descriptions": {
            "step_orders": "完整的步骤 ID 顺序数组",
            "expected_version": "必填版本号，用于乐观锁",
        },
    },
    "plan_next": {
        "description": "获取下一步建议或并行可执行集合。",
        "param_descriptions": {
            "mode": "ready|focus|blocked_report",
            "expected_version": "可选版本号，用于一致性校验",
        },
    },
    "plan_close": {
        "description": "在所有步骤完成后关闭计划。",
        "param_descriptions": {
            "summary": "计划完成总结",
            "expected_version": "必填版本号，用于乐观锁",
        },
    },
    "search_web": {
        "description": "搜索互联网上的信息。当不知道具体问题的答案、需要最新信息或查找外部文档时使用。",
        "param_descriptions": {"query": "搜索关键词", "max_results": "最大结果数 (默认 5)"},
    },
    "fetch_web_page": {
        "description": "抓取并读取网页内容 (转换为 Markdown)。通常在 search_web 返回 URL 后使用，以获取详细信息。",
        "param_descriptions": {"url": "网页 URL"},
    },
    # ──────────────────────────────────────────────────────────────────
    # WorldQuant Brain 自动挖因子工具集
    # ──────────────────────────────────────────────────────────────────
    "wq_login": {
        "description": "登录 WorldQuant Brain 平台。凭证解析优先级:函数参数 > 环境变量(WQ_BRAIN_EMAIL/WQ_BRAIN_PASSWORD) > 工作目录下的 credential.txt。首次使用任何 wq_* 工具前必须调用。",
        "param_descriptions": {
            "email": "Brain 注册邮箱(留空则走环境变量/凭证文件)",
            "password": "Brain 登录密码(留空则走环境变量/凭证文件)",
        },
    },
    "wq_list_operators": {
        "description": "列出 Brain 平台支持的算子。use_cache=True 返回内置精选清单(零网络/即时返回),False 则在线查询完整列表。",
        "param_descriptions": {"use_cache": "是否使用内置缓存(默认 True)"},
    },
    "wq_list_data_fields": {
        "description": "列出 Brain 平台的数据字段(open/high/low/close/volume/vwap/cap 等)。use_cache=True 返回常用字段精选,False 在线查询完整字段池。",
        "param_descriptions": {
            "region": "区域(USA/CHN/GLB 等,默认 USA)",
            "universe": "股票池(TOP3000/TOP1000 等,默认 TOP3000)",
            "delay": "信号延迟,默认 1",
            "search": "字段名搜索关键字",
            "use_cache": "是否使用内置缓存",
            "limit": "最多返回多少条",
        },
    },
    "wq_list_directions": {
        "description": "列出内置的因子研究方向库(reversal_short_term / momentum_mid_term / volatility_regime / volume_price_divergence / high_order_moments / intraday_microstructure)。用于 diversified planning。",
        "param_descriptions": {},
    },
    "wq_memory_snapshot": {
        "description": "读取 Experience Memory 当前快照,返回 P_succ(成功模板) / P_fail(禁区) / I(策略洞察) / 因子库 Top10。生成新因子前**强烈建议**先调此工具。",
        "param_descriptions": {
            "tags": "按标签过滤(如 ['volume','short_term'])",
            "succ_k": "返回 Top-K 成功模板,默认 5",
            "fail_k": "返回 Top-K 禁区,默认 5",
            "insight_k": "返回 Top-K 洞察,默认 3",
        },
    },
    "wq_build_generation_prompt": {
        "description": "为指定研究方向构造一份带记忆注入的 alpha 生成 prompt。LLM 拿到 prompt 后**在自己后续的思考中**直接输出 alpha 表达式 JSON 数组,再调 wq_evaluate_alpha 验证。",
        "param_descriptions": {
            "direction_key": "wq_list_directions 中的 key,如 'reversal_short_term'",
            "hypothesis": "本轮要验证的假设(自然语言,可空)",
            "n": "希望生成的表达式数量,默认 5",
            "custom_direction": "自定义方向 dict,覆盖 direction_key",
        },
    },
    "wq_simulate_alpha": {
        "description": "在 Brain 平台执行单条 alpha 的回测(IS 模拟)。默认等待结果返回完整 IS 指标 + checks。该工具**不写本地库**,仅做模拟。",
        "param_descriptions": {
            "expression": "FASTEXPR 表达式,如 'rank(ts_delta(close, 5))'",
            "region": "区域,默认 USA",
            "universe": "股票池,默认 TOP3000",
            "delay": "信号延迟,默认 1",
            "decay": "线性衰减天数,默认 0",
            "neutralization": "中性化方式 NONE/MARKET/INDUSTRY/SUBINDUSTRY/SECTOR",
            "truncation": "权重截断,默认 0.08",
            "wait": "是否同步等待结果(默认 True)",
            "max_wait_seconds": "轮询最长等待秒数,默认 600",
        },
    },
    "wq_evaluate_alpha": {
        "description": "完整 4 阶段评估管线(本地语法 + Brain 模拟 + checks + 阈值)。通过则可选自动写入因子库 + 成功模板。失败时若是高自相关,自动写入禁区。这是日常挖因子最常用的工具。",
        "param_descriptions": {
            "expression": "FASTEXPR 表达式",
            "direction_tag": "所属研究方向标签(用于记忆 tag)",
            "region": "区域",
            "universe": "股票池",
            "delay": "信号延迟",
            "decay": "线性衰减",
            "neutralization": "中性化方式",
            "truncation": "截断",
            "min_sharpe": "Sharpe 阈值,默认 1.25",
            "min_fitness": "Fitness 阈值,默认 1.0",
            "max_turnover": "Turnover 阈值,默认 0.7",
            "admit_to_library": "通过后是否自动入库(默认 True)",
        },
    },
    "wq_distill_insight": {
        "description": "把本轮挖掘得到的策略级教训沉淀到 Experience Memory(I 区)。例如 'ts_rank 窗口超过 60 时容易出现 NaN'。这是 Ralph Loop 中 Distill 阶段的核心动作。",
        "param_descriptions": {
            "insight": "教训内容(自然语言)",
            "category": "operator|data_field|regime|general",
            "severity": "info|warning|critical",
            "tags": "关联方向标签",
        },
    },
    "wq_list_library": {
        "description": "列出本地 alpha 库内容(含 Brain 返回的 metrics),按 sharpe 降序排列。",
        "param_descriptions": {
            "min_sharpe": "最低 sharpe 过滤(默认 0 不过滤)",
            "limit": "返回数量上限,默认 50",
        },
    },
    "wq_list_my_alphas": {
        "description": "查询当前 Brain 账户上的 alpha 列表(已通过 simulate 留痕的所有 alpha)。",
        "param_descriptions": {
            "status": "状态过滤,如 UNSUBMITTED / SUBMITTED",
            "limit": "返回数量",
            "offset": "翻页偏移",
        },
    },
    "wq_submit_alpha": {
        "description": "把一个已通过质量检查的 alpha 正式提交到 Brain 比赛/Alphathon。注意每日有提交配额限制(Pre-Consultant 通常每日 1 条)。",
        "param_descriptions": {"alpha_id": "Brain 返回的 alpha_id"},
    },
    "wq_mutate_alpha": {
        "description": "对一个种子 alpha 做参数扰动,生成 N 个 mutation 候选(主要扰动数值常量/窗口期)。对应 QuantaAlpha 的 Mutation 进化算子。",
        "param_descriptions": {
            "seed_expression": "种子 FASTEXPR 表达式",
            "window_candidates": "数值候选集,如 [5,10,20,30,60]",
            "max_variants": "最多生成变体数,默认 6",
        },
    },
    "wq_crossover_alpha": {
        "description": "对两个 alpha 做交叉,生成新的杂交表达式。对应 QuantaAlpha 的 Crossover 进化算子。strategy 取值:wrap_b_in_a | rank_pair | add_pair | corr_pair。",
        "param_descriptions": {
            "expression_a": "表达式 A",
            "expression_b": "表达式 B",
            "strategy": "交叉策略",
        },
    },
}

TOOL_SCHEMAS = build_tool_schemas(TOOLS, _TOOL_SCHEMA_META)

__all__ = ["TOOLS", "TOOL_SCHEMAS"]
