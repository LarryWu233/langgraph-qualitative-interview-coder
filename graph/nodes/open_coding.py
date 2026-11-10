"""开放编码节点 - 概念提取 + 初步子类属分类"""
from __future__ import annotations
from langchain_core.messages import SystemMessage, HumanMessage

from config import get_llm, OPEN_CODING_PROVIDER
from models import OpenCodingResponse, ConceptEntry, SubcategoryEntry, NodeTokenStats
from prompts.open_coding import OPEN_CODING_SYSTEM, OPEN_CODING_USER
from graph.state import CodingState
from token_utils import invoke_with_tokens


def _format_existing_concepts(concepts: dict, subcategories: dict) -> str:
    """格式化已有概念库供 prompt 使用"""
    if not concepts:
        return "（暂无已有概念，这是第一轮编码）"

    lines = []
    for subcat_name, subcat_data in subcategories.items():
        lines.append(f"\n### 子类属: {subcat_name}")
        if subcat_data.get("definition"):
            lines.append(f"  定义: {subcat_data['definition']}")
        for c_name in subcat_data.get("concepts", []):
            c = concepts.get(c_name, {})
            lines.append(
                f"  - 概念: {c_name} | 定义: {c.get('definition', '')} | 出现次数: {c.get('frequency', 0)}"
            )

    return "\n".join(lines) if lines else "（暂无已有概念，这是第一轮编码）"


def _format_chunk(chunk: dict) -> str:
    """格式化单个chunk供 prompt 使用"""
    lines = [f"### Chunk ID: {chunk['chunk_id']}"]
    lines.append(f"\n**提问:**\n{chunk['question_text']}")
    lines.append(f"\n**回答:**\n{chunk['answer_text']}")
    return "\n".join(lines)


def open_coding_node(state: CodingState) -> dict:
    """对当前批次的chunk进行开放编码（支持断点续跑：跳过已完成的 chunk）"""
    llm = get_llm(OPEN_CODING_PROVIDER)
    structured_llm = llm.with_structured_output(OpenCodingResponse)

    chunks = state["chunks"]
    batch_start = state["current_batch_start"]
    batch_size = state["batch_size"]
    batch_end = min(batch_start + batch_size, len(chunks))

    concepts = dict(state.get("concepts", {}))
    subcategories = dict(state.get("subcategories", {}))
    chunk_codings = dict(state.get("chunk_codings", {}))
    logs: list[str] = []   # 只返回本节点新增的日志（reducer 负责累积）

    # 已完成的 chunk id（断点续跑时跳过）
    completed_chunk_ids = list(state.get("completed_chunk_ids", []))
    completed_set = set(completed_chunk_ids)

    # 继承已有 token 统计（多轮循环累加）
    token_stats: dict = dict(state.get("token_stats", {}))
    prev_node = token_stats.get("open_coding", {})
    node_stats = NodeTokenStats(
        prompt_tokens=prev_node.get("prompt_tokens", 0),
        completion_tokens=prev_node.get("completion_tokens", 0),
        total_tokens=prev_node.get("total_tokens", 0),
        calls=prev_node.get("calls", 0),
    )

    batch_chunks = chunks[batch_start:batch_end]

    # 过滤掉已完成的 chunk
    pending_chunks = [c for c in batch_chunks if c["chunk_id"] not in completed_set]
    skipped = len(batch_chunks) - len(pending_chunks)

    if skipped > 0:
        logs.append(f"[开放编码] 跳过 {skipped} 个已完成的 chunk（断点续跑）")

    logs.append(
        f"[开放编码] 处理第 {batch_start+1}-{batch_end} 个chunk（共 {len(chunks)} 个）"
        f"，本批次待处理: {len(pending_chunks)} 个"
    )

    existing_text = _format_existing_concepts(concepts, subcategories)

    batch_tokens = 0
    for chunk in pending_chunks:
        chunk_text = _format_chunk(chunk)

        messages = [
            SystemMessage(content=OPEN_CODING_SYSTEM),
            HumanMessage(content=OPEN_CODING_USER.format(
                existing_concepts=existing_text,
                chunk_text=chunk_text,
            )),
        ]

        response, prompt, completion, total = invoke_with_tokens(structured_llm, messages)
        node_stats.prompt_tokens += prompt
        node_stats.completion_tokens += completion
        node_stats.total_tokens += total
        node_stats.calls += 1
        batch_tokens += total

        # 记录本chunk的编码结果
        chunk_codings[chunk["chunk_id"]] = [c.model_dump() for c in response.concepts]

        # 更新概念库和子类属
        for concept in response.concepts:
            c_name = concept.name
            if c_name in concepts:
                concepts[c_name]["frequency"] = concepts[c_name].get("frequency", 0) + 1
                concepts[c_name]["chunks"].append(chunk["chunk_id"])
                concepts[c_name]["evidence"].extend(concept.evidence)
            else:
                concepts[c_name] = ConceptEntry(
                    name=c_name,
                    definition=concept.definition,
                    subcategory=concept.subcategory,
                    frequency=1,
                    chunks=[chunk["chunk_id"]],
                    evidence=concept.evidence,
                ).model_dump()

            subcat = concept.subcategory
            if subcat not in subcategories:
                subcategories[subcat] = SubcategoryEntry(
                    name=subcat,
                    concepts=[c_name],
                ).model_dump()
            elif c_name not in subcategories[subcat]["concepts"]:
                subcategories[subcat]["concepts"].append(c_name)

        # 标记该 chunk 已完成（写入 state，触发 checkpoint 保存）
        completed_chunk_ids.append(chunk["chunk_id"])

    token_info = f"  (+{batch_tokens} tokens)" if batch_tokens > 0 else ""
    logs.append(
        f"[开放编码] 当前概念总数: {len(concepts)}, 子类属总数: {len(subcategories)}{token_info}"
    )

    token_stats["open_coding"] = node_stats.model_dump()

    return {
        "concepts": concepts,
        "subcategories": subcategories,
        "chunk_codings": chunk_codings,
        "completed_chunk_ids": completed_chunk_ids,
        "token_stats": token_stats,
        "current_step": "open_coding",
        "log": logs,
    }
