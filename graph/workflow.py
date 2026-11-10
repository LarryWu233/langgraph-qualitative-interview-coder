"""LangGraph 工作流定义（含 Hierarchical Axial Coding）"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from langgraph.graph import StateGraph, END
from langgraph.types import Send                        # ⭐ 动态分支调度 API
from langgraph.checkpoint.sqlite import SqliteSaver

from graph.state import CodingState
from graph.nodes.chunking import chunking_node
from graph.nodes.open_coding import open_coding_node
from graph.nodes.merge import merge_node
from graph.nodes.axial_coding import (
    axial_dispatch_node,
    axial_map_node,
    axial_reduce_node,
)


# ══════════════════════════════════════════════════════════════════════
# 路由节点
# ══════════════════════════════════════════════════════════════════════

def route_entry(state: CodingState) -> str:
    """
    入口分流：根据 state.entry_point 决定从哪个节点开始执行。

    - "axial"：直接跳到主轴编码（从 db/coding_db.json 加载的已有 concepts）
    - 其它（默认 "full"）：走完整流程 chunking → open_coding → merge → axial

    这样设计使得 Open Coding 和 Axial Coding 可以完全独立触发，互不干扰。
    """
    return "axial_dispatch" if state.get("entry_point") == "axial" else "chunking"


def should_continue_coding(state: CodingState) -> str:
    """
    开放编码 ⇄ 合并 循环的退出条件。

    Note: Here 'saturated' acts as an engineering flag (all chunks processed),
    not strict theoretical saturation.
    """
    return "axial_dispatch" if state.get("is_saturated", False) else "open_coding"


# ══════════════════════════════════════════════════════════════════════
# ⭐ Map 路由：动态切片 + Send 并行分发
# ══════════════════════════════════════════════════════════════════════

def map_router(state: CodingState) -> list[Send]:
    """
    Map 阶段路由：将 state.concepts 按 axial_chunk_size 切片，
    每片以 Send 形式触发一个 axial_map 实例（并行执行）。

    Send 特点：
    - LangGraph 会立即并行调度所有 Send，目标节点各自独立运行
    - 每个 Send 的返回值通过 merge_axial_results reducer 累积到 axial_sub_results
    - 等所有 Send 完成后，LangGraph 自动进入下一个节点（axial_reduce）

    axial_run_id 由 axial_dispatch_node 生成，Send payload 中携带它，
    确保 reducer 能正确区分新旧 run。
    """
    concepts = state.get("concepts", {})
    chunk_size = state.get("axial_chunk_size", 50) or 50
    axial_run_id = state.get("axial_run_id", "")

    # 将 concepts dict 展平为 list（便于切片）
    # 保留 name / definition / subcategory / frequency
    items = [
        {"name": name, **data}
        for name, data in concepts.items()
    ]

    sends: list[Send] = []
    for i in range(0, len(items), chunk_size):
        chunk_index = i // chunk_size
        sends.append(Send(
            "axial_map",          # 目标节点名（与 workflow.add_node 名一致）
            {
                "axial_run_id": axial_run_id,          # ⭐ 用于 reducer 版本校验
                "chunk_index": chunk_index,
                "concepts_slice": items[i:i + chunk_size],
            },
        ))

    return sends


# ══════════════════════════════════════════════════════════════════════
# 图构建
# ══════════════════════════════════════════════════════════════════════

def build_workflow(checkpoint_db: str | Path | None = None):
    """
    构建编码工作流。

    完整流程拓扑：

      start ─┬─[entry_point=full]─→ chunking → open_coding ⇄ merge
             │                                   ↓（is_saturated=True）
             └─[entry_point=axial]──→ axial_dispatch
                                              ↓（Send × N 并行）
                                    ┌─────────┼─────────┐
                                    ▼         ▼         ▼
                                axial_map axial_map  axial_map  （N 个并行分支）
                                    └─────────┬─────────┘
                                              ↓（等所有 Send 完成后进入）
                                         axial_reduce → END

    checkpoint_db: SQLite 文件路径，用于断点续跑。
                   传 None 则不启用 checkpoint（纯内存运行）。
    """
    workflow = StateGraph(CodingState)

    # ── 节点注册 ───────────────────────────────────────
    # start: 极简 passthrough，用于触发 route_entry 条件边
    # 不返回 log，避免触发 operator.add reducer 产生空列表拼接
    workflow.add_node("start", lambda state: {"current_step": "start"})

    workflow.add_node("chunking", chunking_node)
    workflow.add_node("open_coding", open_coding_node)
    workflow.add_node("merge", merge_node)
    workflow.add_node("axial_dispatch", axial_dispatch_node)
    # axial_map_node 接收 Send payload（dict），是 LangGraph Send API 的标准模式；
    # Pylance 不理解该约定，用 type: ignore 屏蔽误报
    workflow.add_node("axial_map", axial_map_node)  # type: ignore[arg-type]
    workflow.add_node("axial_reduce", axial_reduce_node)

    # ── 入口 ───────────────────────────────────────────
    workflow.set_entry_point("start")

    # 入口条件分流（start → chunking 或 start → axial_dispatch）
    workflow.add_conditional_edges(
        "start",
        route_entry,
        {
            "chunking": "chunking",
            "axial_dispatch": "axial_dispatch",
        },
    )

    # ── Open Coding 循环主链 ───────────────────────────
    workflow.add_edge("chunking", "open_coding")
    workflow.add_edge("open_coding", "merge")
    workflow.add_conditional_edges(
        "merge",
        should_continue_coding,
        {
            "open_coding": "open_coding",   # 继续下一批
            "axial_dispatch": "axial_dispatch",  # Note: 'saturated' = all chunks done
        },
    )

    # ── Axial Map-Reduce 拓扑 ───────────────────────────
    # dispatch → 动态 Send → 并行 Map 分支 → 自动 join → reduce → END
    #
    # add_conditional_edges 的 targets 参数为空列表 [] 表示没有静态后继节点，
    # 所有后继完全由 map_router 返回的 Send 决定。
    # LangGraph 内部处理：所有 Send 完成后，状态回到本节点，再流向下一静态节点。
    workflow.add_conditional_edges("axial_dispatch", map_router, [])
    workflow.add_edge("axial_map", "axial_reduce")   # 所有 Send join 后进入 reduce
    workflow.add_edge("axial_reduce", END)

    # ── Checkpointer 注入 ──────────────────────────────
    if checkpoint_db is not None:
        checkpoint_db = Path(checkpoint_db)
        checkpoint_db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(checkpoint_db), check_same_thread=False)
        checkpointer = SqliteSaver(conn)
        return workflow.compile(checkpointer=checkpointer)

    return workflow.compile()
