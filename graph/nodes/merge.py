"""概念合并节点 - 去重与归并"""
from __future__ import annotations
from langchain_core.messages import SystemMessage, HumanMessage

from config import get_llm, MERGE_PROVIDER, SATURATION_ROUNDS
from models import MergeResponse, NodeTokenStats
from prompts.merge import MERGE_SYSTEM, MERGE_USER
from graph.state import CodingState
from token_utils import invoke_with_tokens


def _format_concept_list(concepts: dict) -> str:
    """格式化概念列表"""
    if not concepts:
        return "（空）"
    lines = []
    for name, data in concepts.items():
        lines.append(f"- {name}: {data.get('definition', '')} [子类属: {data.get('subcategory', '')}]")
    return "\n".join(lines)


def merge_node(state: CodingState) -> dict:
    """合并本轮新概念与已有概念库"""
    concepts = dict(state.get("concepts", {}))
    subcategories = dict(state.get("subcategories", {}))
    prev_count = state.get("prev_concept_count", 0)
    rounds_without_new = state.get("rounds_without_new", 0)
    logs: list[str] = []   # 只返回本节点新增的日志（reducer 负责累积）
    batch_start = state["current_batch_start"]
    batch_size = state["batch_size"]

    # 继承已有 token 统计（多轮循环累加）
    token_stats: dict = dict(state.get("token_stats", {}))
    prev_node = token_stats.get("merge", {})
    node_stats = NodeTokenStats(
        prompt_tokens=prev_node.get("prompt_tokens", 0),
        completion_tokens=prev_node.get("completion_tokens", 0),
        total_tokens=prev_node.get("total_tokens", 0),
        calls=prev_node.get("calls", 0),
    )

    current_count = len(concepts)
    new_concept_count = current_count - prev_count

    logs.append(f"[合并] 上轮概念数: {prev_count}, 当前概念数: {current_count}, 新增: {new_concept_count}")

    # 如果有足够多的概念（>10）且本轮有新概念，调用LLM做合并检查
    if current_count > 10 and new_concept_count > 0:
        llm = get_llm(MERGE_PROVIDER)
        structured_llm = llm.with_structured_output(MergeResponse)

        existing_text = _format_concept_list(
            {k: v for k, v in list(concepts.items())[:prev_count]}
        )
        new_text = _format_concept_list(
            {k: v for k, v in list(concepts.items())[prev_count:]}
        )

        messages = [
            SystemMessage(content=MERGE_SYSTEM),
            HumanMessage(content=MERGE_USER.format(
                existing_concepts=existing_text,
                new_concepts=new_text,
            )),
        ]

        response, prompt, completion, total = invoke_with_tokens(structured_llm, messages)
        node_stats.prompt_tokens += prompt
        node_stats.completion_tokens += completion
        node_stats.total_tokens += total
        node_stats.calls += 1

        # 执行合并
        merged_count = 0
        for merge in response.merged_concepts:
            src = merge.source_name
            tgt = merge.target_name
            if src in concepts and tgt in concepts:
                concepts[tgt]["frequency"] = (
                    concepts[tgt].get("frequency", 0) + concepts[src].get("frequency", 0)
                )
                concepts[tgt]["chunks"].extend(concepts[src].get("chunks", []))
                concepts[tgt]["evidence"].extend(concepts[src].get("evidence", []))

                src_subcat = concepts[src].get("subcategory", "")
                if src_subcat in subcategories and src in subcategories[src_subcat].get("concepts", []):
                    subcategories[src_subcat]["concepts"].remove(src)
                    if not subcategories[src_subcat]["concepts"]:
                        del subcategories[src_subcat]

                del concepts[src]
                merged_count += 1
                logs.append(f"[合并] '{src}' → '{tgt}' ({merge.reason})")

        token_info = f"  (+{total} tokens)" if total > 0 else ""
        logs.append(
            f"[合并] 合并了 {merged_count} 个概念，当前概念总数: {len(concepts)}{token_info}"
        )
        current_count = len(concepts)
        new_concept_count = current_count - prev_count

    # 饱和度统计（仅用于日志提示，不再作为终止条件）
    if new_concept_count <= 0:
        rounds_without_new += 1
    else:
        rounds_without_new = 0

    next_batch_start = batch_start + batch_size
    all_processed = next_batch_start >= len(state["chunks"])

    # 唯一终止条件：所有 chunk 已处理完
    is_saturated = all_processed

    if all_processed:
        logs.append("[合并] 所有chunk已处理完毕")
    elif rounds_without_new >= SATURATION_ROUNDS:
        logs.append(
            f"[合并] 提示：连续 {rounds_without_new} 轮无新概念（理论饱和信号，继续处理剩余chunk）"
        )

    token_stats["merge"] = node_stats.model_dump()

    return {
        "concepts": concepts,
        "subcategories": subcategories,
        "prev_concept_count": current_count,
        "rounds_without_new": rounds_without_new,
        "is_saturated": is_saturated,
        "current_batch_start": next_batch_start,
        "token_stats": token_stats,
        "current_step": "merge",
        "log": logs,
    }
