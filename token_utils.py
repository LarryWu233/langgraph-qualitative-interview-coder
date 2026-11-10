"""
Token 统计工具
从 langchain_core AIMessage 的 usage_metadata 中提取 token 用量。
不依赖 langchain_community，仅使用 langchain_core。
"""
from __future__ import annotations
from typing import Any


def extract_tokens(ai_message: Any) -> tuple[int, int, int]:
    """
    从 AIMessage 中提取 (prompt_tokens, completion_tokens, total_tokens)。
    支持多种 API 返回格式，提取失败时返回 (0, 0, 0)。
    """
    if ai_message is None:
        return 0, 0, 0

    # 方式1：langchain-core 0.2+ 的 usage_metadata 字段
    usage = getattr(ai_message, "usage_metadata", None)
    if usage and isinstance(usage, dict):
        prompt = usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0)
        completion = usage.get("output_tokens", 0) or usage.get("completion_tokens", 0)
        total = usage.get("total_tokens", 0) or (prompt + completion)
        return prompt, completion, total

    # 方式2：response_metadata（部分模型）
    meta = getattr(ai_message, "response_metadata", None)
    if meta and isinstance(meta, dict):
        token_usage = meta.get("token_usage") or meta.get("usage") or {}
        if token_usage:
            prompt = token_usage.get("prompt_tokens", 0) or token_usage.get("input_tokens", 0)
            completion = token_usage.get("completion_tokens", 0) or token_usage.get("output_tokens", 0)
            total = token_usage.get("total_tokens", 0) or (prompt + completion)
            return prompt, completion, total

    return 0, 0, 0


def invoke_with_tokens(structured_llm: Any, messages: list) -> tuple[Any, int, int, int]:
    """
    调用结构化 LLM 并返回 (result, prompt_tokens, completion_tokens, total_tokens)。

    with_structured_output 返回的 chain 最终输出是 Pydantic 对象，
    没有 usage_metadata。这里改用底层 llm 先 invoke 拿到 AIMessage，
    再用 output_parser 解析，从而同时获得结构化结果和 token 统计。
    """
    # structured_llm 是 RunnableSequence: llm | parser
    # 尝试直接调用并从最后一步的 AIMessage 获取 token
    # 由于 with_structured_output 封装了 parser，我们需要访问底层
    try:
        # 获取底层 llm（第一步）和 parser（最后一步）
        steps = list(structured_llm.steps) if hasattr(structured_llm, "steps") else []
        if len(steps) >= 2:
            llm_step = steps[0]
            parser_step = steps[-1]
            # 先用底层 llm invoke 拿到 AIMessage
            ai_msg = llm_step.invoke(messages)
            prompt, completion, total = extract_tokens(ai_msg)
            # 再用 parser 解析
            result = parser_step.invoke(ai_msg)
            return result, prompt, completion, total
    except Exception:
        pass

    # 降级：直接调用 structured_llm，token 统计为 0
    result = structured_llm.invoke(messages)
    return result, 0, 0, 0
