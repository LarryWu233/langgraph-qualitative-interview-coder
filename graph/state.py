"""LangGraph State 定义"""
from __future__ import annotations
import operator
from typing import Annotated
from typing_extensions import TypedDict


# ── 自定义 Reducer：基于 axial_run_id 的版本号防抖方案 ──────────────────────
def merge_axial_results(
    left: list[dict] | None,
    right: list[dict] | None,
) -> list[dict]:
    """
    主轴编码 Map 阶段结果的自定义 Reducer。

    采用 run_id 版本号方案（而非 sentinel 哨兵），避免并发 Map 场景下的竞态条件：
    - 每条 Map 分支输出的 dict 中必须携带 "axial_run_id" 字段
    - 如果 right 中的 run_id 与 left 中已有的 run_id 不同，说明这是新一轮 axial 执行，
      直接用 right 覆盖 left（清空旧轮数据）
    - 如果 run_id 相同，则追加（Append），让同一轮的多个并行分支结果累积
    - 如果 right 为空，直接返回 left（保持幂等）
    """
    if not right:
        return left or []

    # 取 right 中第一条有效记录的 run_id
    new_run_id = None
    for item in right:
        if isinstance(item, dict) and item.get("axial_run_id"):
            new_run_id = item["axial_run_id"]
            break

    # 如果 right 没有 run_id（异常情况），直接追加
    if new_run_id is None:
        return (left or []) + right

    # 取 left 中已有的 run_id（取第一条）
    existing_run_id = None
    for item in (left or []):
        if isinstance(item, dict) and item.get("axial_run_id"):
            existing_run_id = item["axial_run_id"]
            break

    if existing_run_id != new_run_id:
        # 新的 run_id → 覆盖旧数据，开启新一轮收集
        return list(right)
    else:
        # 相同 run_id → 追加（同一轮并行分支的结果累积）
        return (left or []) + right


# ── State 定义 ────────────────────────────────────────────────────────────────
class CodingState(TypedDict):
    """整个编码工作流的状态"""

    # ── 原始数据 ──────────────────────────────────────
    files: dict[str, list[dict]]        # filename -> utterances（序列化后）

    # ── 问答分对结果 ──────────────────────────────────
    chunks: list[dict]                  # QAChunk 序列化后

    # ── 编码进度 ──────────────────────────────────────
    current_batch_start: int            # 当前批次起始索引
    batch_size: int

    # ── 已完成的 chunk id 集合（断点续跑时跳过已处理的 chunk）──
    completed_chunk_ids: list[str]

    # ── 概念库 ────────────────────────────────────────
    concepts: dict[str, dict]           # concept_name -> ConceptEntry 序列化
    subcategories: dict[str, dict]      # subcategory_name -> SubcategoryEntry 序列化

    # ── 编码结果（每个 chunk 的编码）──────────────────
    chunk_codings: dict[str, list[dict]]  # chunk_id -> [ConceptItem 序列化]

    # ── 饱和度追踪 ────────────────────────────────────
    rounds_without_new: int             # 连续无新概念的轮数
    prev_concept_count: int             # 上一轮的概念总数
    is_saturated: bool
    # Note: Here 'saturated' acts as an engineering flag (all chunks processed),
    # not strict theoretical saturation.

    # ── 主轴编码 Map-Reduce ───────────────────────────
    categories: dict[str, dict]         # category_name -> CategoryEntry 序列化
    axial_chunk_size: int               # Map 阶段切片大小，默认 50
    axial_run_id: str                   # 本轮主轴编码的唯一 run_id（用于 reducer 版本校验）
    axial_total: int                    # Map 阶段总切片数（由 dispatch 节点写入）
    axial_completed_count: Annotated[   # 已完成的 Map 分支数（并行累加）
        int,
        operator.add,
    ]
    axial_sub_results: Annotated[       # 各 Map 分支输出，通过 reducer 自动累积
        list[dict],
        merge_axial_results,
    ]
    # axial_sub_results 中每条 dict 的结构：
    # {
    #   "axial_run_id": str,            # 与 state.axial_run_id 一致
    #   "chunk_index": int,
    #   "subcategories": [AxialMapSubcategory.model_dump(), ...],
    #   "tokens": int,
    #   "prompt_tokens": int,
    #   "completion_tokens": int,
    #   "calls": int,
    # }

    # ── 流程控制 ──────────────────────────────────────
    entry_point: str                    # "full" | "axial"

    # ── Token 统计（各节点累计，序列化为 dict）──────────
    token_stats: dict                   # TokenStats.model_dump()

    # ── 当前进度信息（供 progress 面板读取）────────────
    current_step: str                   # 当前步骤名称
    current_file: str                   # 当前正在处理的文件名

    # ── 日志 ──────────────────────────────────────────
    # 使用 operator.add 作为 Reducer，允许并行 Map 分支同时追加日志（列表拼接）
    log: Annotated[list[str], operator.add]
