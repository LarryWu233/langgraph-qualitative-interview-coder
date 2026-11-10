"""主轴编码节点 - 分层归纳（Hierarchical Map-Reduce）

三个节点职责：
1. axial_dispatch_node   — 计算切片数量，生成新的 axial_run_id，触发 reducer 重置
2. axial_map_node        — Map 阶段：单切片（约 50 概念）聚类为 5~10 个初步子类属
3. axial_reduce_node     — Reduce 阶段：聚合所有 Map 输出，归纳为 3~5 个核心类属 + relations
"""
from __future__ import annotations

import time
from langchain_core.messages import SystemMessage, HumanMessage

from config import get_llm, AXIAL_CODING_PROVIDER
from models import (
    AxialMapResponse,
    AxialCodingResponse,
    CategoryEntry,
    SubcategoryEntry,
    NodeTokenStats,
)
from prompts.axial_coding import (
    AXIAL_MAP_SYSTEM,
    AXIAL_MAP_USER,
    AXIAL_REDUCE_SYSTEM,
    AXIAL_REDUCE_USER,
)
from graph.state import CodingState
from token_utils import invoke_with_tokens


# ══════════════════════════════════════════════════════════════════════
# 节点 A：Dispatcher（不调 LLM，纯计算）
# ══════════════════════════════════════════════════════════════════════
def axial_dispatch_node(state: CodingState) -> dict:
    """
    主轴编码入口节点（Dispatcher）：

    职责：
    1. 从 state.concepts 数量计算切片数量
    2. 生成新的 axial_run_id（时间戳），用于 reducer 版本校验
       — 每次新 run 都生成新 run_id，确保 reducer 在新 run 时清空旧数据
    3. 写入 axial_total（切片总数）供进度面板读取
    4. 重置 axial_completed_count 为 0（通过写入负数再加回来不可行，
       直接在 initial_state 里初始化为 0，dispatch 不写该字段）

    注意：
    - 此节点不调 LLM，纯状态准备
    - 后续 map_router 会读取这里的 axial_run_id 来给每个 Send payload 注入 run_id
    """
    concepts = state.get("concepts", {})
    chunk_size = state.get("axial_chunk_size", 50) or 50

    total = len(concepts)
    n_chunks = (total + chunk_size - 1) // chunk_size if total > 0 else 0

    # 生成新的 run_id：每次新触发 axial 都用新 ID
    # reducer 见到新 run_id 会自动覆盖旧数据（无需 sentinel）
    run_id = f"axial-{int(time.time() * 1000)}"

    logs: list[str] = []   # 只返回本节点新增的日志（reducer 负责累积）
    logs.append(
        f"[主轴-Dispatch] 概念总数={total}, 切片大小={chunk_size}, "
        f"将并行触发 {n_chunks} 个 Map 分支（run_id={run_id}）"
    )

    return {
        "axial_run_id": run_id,
        "axial_chunk_size": chunk_size,
        "axial_total": n_chunks,          # 供进度面板读取总切片数
        # axial_sub_results 留空，由 map_router 的 Send 填充
        "current_step": "axial_dispatch",
        "log": logs,
    }


# ══════════════════════════════════════════════════════════════════════
# 节点 B：Map（并行调度，每个分支处理一个切片）
# ══════════════════════════════════════════════════════════════════════
def axial_map_node(task: dict) -> dict:
    """
    Map 阶段节点（被并行调度）：

    输入 task（来自 Send payload）：
        {
            "axial_run_id": str,           # 用于 reducer 校验
            "chunk_index": int,            # 切片序号（从 0 开始）
            "concepts_slice": [dict, ...], # 本次要处理的概念列表
        }

    职责：
    - 调用 LLM 对 ~50 个概念做小规模聚类，输出 5~10 个初步子类属
    - 返回的 axial_sub_results 由 reducer 自动累积到主 state

    注意：
    - 每个分支独立调 LLM，max_tokens=4096（切片小，上下文短）
    - 概念按 subcategory 预分组以降低 LLM 认知负担
    """
    axial_run_id = task.get("axial_run_id", "")
    chunk_index = task.get("chunk_index", 0)
    concepts_slice = task.get("concepts_slice", [])

    llm = get_llm(AXIAL_CODING_PROVIDER)
    structured_llm = llm.with_structured_output(AxialMapResponse)

    # ── 按 Open Coding 阶段已有的 subcategory 粗分组展示，
    #    帮助 LLM 快速理解概念语义，降低认知负担 ──
    #    格式：概念名 + 定义 + 预分类 + 频次
    lines = []
    for c in concepts_slice:
        subcat = c.get("subcategory", "未分类")
        freq = c.get("frequency", 1)
        lines.append(
            f"- 概念: {c['name']} | 定义: {c.get('definition', '')} "
            f"| 预分类: {subcat} | 出现次数: {freq}"
        )
    concepts_text = "\n".join(lines)

    messages = [
        SystemMessage(content=AXIAL_MAP_SYSTEM),
        HumanMessage(content=AXIAL_MAP_USER.format(
            chunk_index=chunk_index,
            concepts_text=concepts_text,
        )),
    ]

    response, prompt, completion, total = invoke_with_tokens(structured_llm, messages)

    # ── 构建单分支结果（携带 run_id，由 reducer 合并）──
    sub_result = {
        "axial_run_id": axial_run_id,        # ⭐ reducer 版本校验依赖此字段
        "chunk_index": chunk_index,
        "subcategories": [s.model_dump() for s in response.subcategories],
        "tokens": total,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "calls": 1,
    }

    return {
        # reducer merge_axial_results 会自动累积到 state.axial_sub_results
        "axial_sub_results": [sub_result],
        # axial_completed_count 用 operator.add reducer 自动累加，进度面板读取
        "axial_completed_count": 1,
        "log": [
            f"[主轴-Map#{chunk_index:02d}] "
            f"输入 {len(concepts_slice)} 概念 → "
            f"产出 {len(response.subcategories)} 个初步子类属 (+{total} tokens)"
        ],
    }


# ══════════════════════════════════════════════════════════════════════
# 节点 C：Reduce（等所有 Map 完成后执行）
# ══════════════════════════════════════════════════════════════════════
def axial_reduce_node(state: CodingState) -> dict:
    """
    Reduce 阶段节点（LangGraph 自动等所有 Send 分支完成后进入）：

    职责：
    1. 从 state.axial_sub_results 聚合所有 Map 产出的初步子类属
    2. 调用 LLM 进行最终融合：~N×10 个初步子类属 → 3~5 个核心类属 + relations
    3. 同步更新 state.subcategories（以 Map 结果为准重建）
    4. 累加 Map + Reduce 的 token 消耗到 token_stats

    注意：
    - state.axial_sub_results 已在 reducer 阶段由 merge_axial_results 合并完毕
    - 仅回写 subcategories，不修改 concepts（Open Coding 产出保持不变）
    """
    sub_results = state.get("axial_sub_results", [])
    axial_run_id = state.get("axial_run_id", "")
    logs: list[str] = []   # 只返回本节点新增的日志（reducer 负责累积）

    # ── 聚合所有初步子类属 ──
    all_subcats = []
    for sr in sub_results:
        if isinstance(sr, dict) and sr.get("axial_run_id") == axial_run_id:
            all_subcats.extend(sr.get("subcategories", []))

    logs.append(
        f"[主轴-Reduce] 聚合 {len(sub_results)} 个 Map 分支，"
        f"共 {len(all_subcats)} 个初步子类属，开始最终融合"
    )

    # ── 格式化给 LLM ──
    sub_results_text = "\n".join(
        f"- 子类属: {sc.get('name', '')} | 定义: {sc.get('definition', '')} "
        f"| 包含概念: {', '.join(sc.get('concepts', []))}"
        for sc in all_subcats
    )

    # ── LLM 融合 ──
    llm = get_llm(AXIAL_CODING_PROVIDER)
    structured_llm = llm.with_structured_output(AxialCodingResponse)

    messages = [
        SystemMessage(content=AXIAL_REDUCE_SYSTEM),
        HumanMessage(content=AXIAL_REDUCE_USER.format(
            sub_results_text=sub_results_text,
            target_min=3,
            target_max=5,
        )),
    ]

    response, prompt, completion, total = invoke_with_tokens(structured_llm, messages)

    # ── 重建 subcategories（以 Map 结果为准，每个子类属记录其归属的 category）──
    new_subcategories: dict[str, dict] = {}
    for sc in all_subcats:
        name = sc.get("name", "")
        if not name:
            continue
        if name in new_subcategories:
            # 合并概念列表（去重）
            merged = list({*new_subcategories[name].get("concepts", []), *sc.get("concepts", [])})
            new_subcategories[name]["concepts"] = merged
        else:
            new_subcategories[name] = SubcategoryEntry(
                name=name,
                definition=sc.get("definition", ""),
                concepts=sc.get("concepts", []),
            ).model_dump()

    # ── 构建核心类属 + 回填 subcategories.category ──
    categories: dict[str, dict] = {}
    for cat in response.categories:
        categories[cat.name] = CategoryEntry(
            name=cat.name,
            definition=cat.definition,
            subcategories=cat.subcategories,
            relations=cat.relations,
        ).model_dump()

        # 回填每个子类属的 category 归属
        for subcat_name in cat.subcategories:
            if subcat_name in new_subcategories:
                new_subcategories[subcat_name]["category"] = cat.name

    # ── Token 累加（Map 分支总计 + Reduce 自身）──
    map_tokens = sum(
        sr.get("tokens", 0)
        for sr in sub_results
        if isinstance(sr, dict) and sr.get("axial_run_id") == axial_run_id
    )
    map_prompt = sum(
        sr.get("prompt_tokens", 0)
        for sr in sub_results
        if isinstance(sr, dict) and sr.get("axial_run_id") == axial_run_id
    )
    map_completion = sum(
        sr.get("completion_tokens", 0)
        for sr in sub_results
        if isinstance(sr, dict) and sr.get("axial_run_id") == axial_run_id
    )
    map_calls = sum(
        sr.get("calls", 0)
        for sr in sub_results
        if isinstance(sr, dict) and sr.get("axial_run_id") == axial_run_id
    )

    token_stats = dict(state.get("token_stats", {}))
    token_stats["axial_coding"] = NodeTokenStats(
        prompt_tokens=map_prompt + prompt,
        completion_tokens=map_completion + completion,
        total_tokens=map_tokens + total,
        calls=map_calls + 1,
    ).model_dump()

    # ── 日志 ──
    logs.append(
        f"[主轴-Reduce] 归纳出 {len(categories)} 个核心类属 "
        f"(Map: +{map_tokens} tokens, Reduce: +{total} tokens)"
    )
    for cat_name, cat_data in categories.items():
        logs.append(
            f"  · {cat_name}: 含 {len(cat_data['subcategories'])} 个子类属, "
            f"{len(cat_data['relations'])} 条关系"
        )

    return {
        "categories": categories,
        "subcategories": new_subcategories,
        "token_stats": token_stats,
        "current_step": "axial_reduce",
        "log": logs,
    }
