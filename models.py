"""Pydantic 数据模型定义"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


# ── 解析阶段 ──────────────────────────────────────────
class Utterance(BaseModel):
    """单条发言"""
    speaker: str
    timestamp: str
    text: str


# ── 问答分对 ──────────────────────────────────────────
class QAChunk(BaseModel):
    """一组问答对"""
    chunk_id: str
    file: str
    question: list[Utterance] = Field(default_factory=list)
    answer: list[Utterance] = Field(default_factory=list)
    question_text: str = ""
    answer_text: str = ""


# ── 开放编码 ──────────────────────────────────────────
class ConceptItem(BaseModel):
    """单个概念"""
    name: str = Field(description="概念名称")
    definition: str = Field(description="概念定义")
    subcategory: str = Field(description="所属子类属")
    evidence: list[str] = Field(default_factory=list, description="原文依据")


class OpenCodingResult(BaseModel):
    """单个chunk的开放编码结果"""
    chunk_id: str
    concepts: list[ConceptItem] = Field(default_factory=list)


# ── 概念库 ────────────────────────────────────────────
class ConceptEntry(BaseModel):
    """概念库中的一个概念"""
    name: str
    definition: str
    subcategory: str
    frequency: int = 1
    chunks: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class SubcategoryEntry(BaseModel):
    """子类属"""
    name: str
    definition: str = ""
    concepts: list[str] = Field(default_factory=list)
    category: Optional[str] = None


class CategoryEntry(BaseModel):
    """核心类属"""
    name: str
    definition: str = ""
    subcategories: list[str] = Field(default_factory=list)
    relations: list[str] = Field(default_factory=list)


# ── Token 统计 ────────────────────────────────────────
class NodeTokenStats(BaseModel):
    """单个节点的 token 统计"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    calls: int = 0


class TokenStats(BaseModel):
    """全局 token 统计"""
    chunking: NodeTokenStats = Field(default_factory=NodeTokenStats)
    open_coding: NodeTokenStats = Field(default_factory=NodeTokenStats)
    merge: NodeTokenStats = Field(default_factory=NodeTokenStats)
    axial_coding: NodeTokenStats = Field(default_factory=NodeTokenStats)

    @property
    def total_tokens(self) -> int:
        return (
            self.chunking.total_tokens
            + self.open_coding.total_tokens
            + self.merge.total_tokens
            + self.axial_coding.total_tokens
        )

    @property
    def total_calls(self) -> int:
        return (
            self.chunking.calls
            + self.open_coding.calls
            + self.merge.calls
            + self.axial_coding.calls
        )

    def add(self, node: str, prompt: int, completion: int) -> None:
        """累加某节点的 token 消耗"""
        entry: NodeTokenStats = getattr(self, node)
        entry.prompt_tokens += prompt
        entry.completion_tokens += completion
        entry.total_tokens += prompt + completion
        entry.calls += 1


# ── 已处理文件记录 ────────────────────────────────────
class ProcessedFileEntry(BaseModel):
    """已处理文件的元数据记录"""
    file: str
    processed_at: str
    chunks: int = 0
    tokens_used: int = 0


# ── LLM 结构化输出 ────────────────────────────────────
class ChunkingResponse(BaseModel):
    """LLM 问答分组响应"""
    groups: list[QAGroup] = Field(default_factory=list)


class QAGroup(BaseModel):
    """一组问答的索引"""
    question_indices: list[int] = Field(description="属于问题的发言索引")
    answer_indices: list[int] = Field(description="属于回答的发言索引")
    topic_summary: str = Field(description="这组问答的主题摘要")


# 修复前向引用
ChunkingResponse.model_rebuild()


class OpenCodingResponse(BaseModel):
    """LLM 开放编码响应"""
    concepts: list[ConceptItem] = Field(default_factory=list)


class MergeResponse(BaseModel):
    """LLM 概念合并响应"""
    merged_concepts: list[MergedConcept] = Field(default_factory=list)
    new_concepts: list[ConceptItem] = Field(default_factory=list)


class MergedConcept(BaseModel):
    """合并建议"""
    source_name: str = Field(description="新提取的概念名")
    target_name: str = Field(description="应合并到的已有概念名")
    reason: str = Field(description="合并理由")


MergeResponse.model_rebuild()


class AxialCodingResponse(BaseModel):
    """LLM 主轴编码响应（Reduce 阶段：最终核心类属）"""
    categories: list[CategoryResult] = Field(default_factory=list)


class CategoryResult(BaseModel):
    """主轴编码结果中的一个核心类属"""
    name: str
    definition: str
    subcategories: list[str]
    relations: list[str] = Field(default_factory=list, description="与其他类属的关系")


AxialCodingResponse.model_rebuild()


# ── 主轴编码 Map 阶段输出 ─────────────────────────────
class AxialMapSubcategory(BaseModel):
    """Map 阶段产出的初步子类属"""
    name: str = Field(description="初步子类属名称")
    definition: str = Field(default="", description="初步子类属定义")
    concepts: list[str] = Field(default_factory=list, description="归入该子类属的概念名称列表")


class AxialMapResponse(BaseModel):
    """LLM 主轴编码 Map 阶段响应（单切片聚类结果）"""
    subcategories: list[AxialMapSubcategory] = Field(default_factory=list)


AxialMapResponse.model_rebuild()
