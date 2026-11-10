"""问答分对节点 - LLM智能分组"""
from __future__ import annotations
from langchain_core.messages import SystemMessage, HumanMessage

from config import get_llm, CHUNKING_PROVIDER
from models import Utterance, QAChunk, ChunkingResponse, NodeTokenStats
from prompts.chunking import CHUNKING_SYSTEM, CHUNKING_USER
from graph.state import CodingState
from token_utils import invoke_with_tokens


def chunking_node(state: CodingState) -> dict:
    """将所有文件的发言列表进行LLM智能问答分组"""
    llm = get_llm(CHUNKING_PROVIDER)
    all_chunks: list[dict] = []
    logs: list[str] = []   # 只返回本节点新增的日志（reducer 负责累积）

    # 继承已有 token 统计
    token_stats: dict = dict(state.get("token_stats", {}))
    node_stats = NodeTokenStats()

    structured_llm = llm.with_structured_output(ChunkingResponse)

    for filename, utterance_dicts in state["files"].items():
        utterances = [Utterance(**u) for u in utterance_dicts]
        logs.append(f"[分组] 处理文件: {filename}, 共 {len(utterances)} 条发言")

        utterances_text = "\n".join(
            f"[{i}] [{u.speaker} {u.timestamp}]: {u.text}"
            for i, u in enumerate(utterances)
        )

        messages = [
            SystemMessage(content=CHUNKING_SYSTEM),
            HumanMessage(content=CHUNKING_USER.format(
                utterances_text=utterances_text,
                max_index=len(utterances) - 1,
            )),
        ]

        response, prompt, completion, total = invoke_with_tokens(structured_llm, messages)
        node_stats.prompt_tokens += prompt
        node_stats.completion_tokens += completion
        node_stats.total_tokens += total
        node_stats.calls += 1

        # 将分组结果转为 QAChunk
        for group_idx, group in enumerate(response.groups):
            chunk_id = f"{filename.replace('.md', '')}_{group_idx + 1:03d}"

            q_utterances = [utterances[i] for i in group.question_indices if i < len(utterances)]
            a_utterances = [utterances[i] for i in group.answer_indices if i < len(utterances)]

            chunk = QAChunk(
                chunk_id=chunk_id,
                file=filename,
                question=q_utterances,
                answer=a_utterances,
                question_text=" ".join(u.text for u in q_utterances),
                answer_text=" ".join(u.text for u in a_utterances),
            )
            all_chunks.append(chunk.model_dump())

        token_info = f"  (+{total} tokens)" if total > 0 else ""
        logs.append(f"[分组] {filename} 分为 {len(response.groups)} 组问答{token_info}")

    token_stats["chunking"] = node_stats.model_dump()

    return {
        "chunks": all_chunks,
        "current_batch_start": 0,
        "token_stats": token_stats,
        "current_step": "chunking",
        "log": logs,
    }
