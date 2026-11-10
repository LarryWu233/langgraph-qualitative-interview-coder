# Architecture and methodological limitations

## Execution

`graph/workflow.py` builds a `StateGraph(CodingState)` with full-workflow and axial-only entry routes. The full route runs `chunking -> open_coding -> merge`, repeating coding and merging until every chunk has been processed.

Axial dispatch assigns a run ID. `map_router` slices the concept dictionary and issues LangGraph `Send` tasks. Each Map task proposes preliminary subcategories. A state reducer collects the current run's results; Reduce synthesizes higher-level categories and textual relations. `SqliteSaver` provides optional checkpoint persistence.

## Modules

| Module | Responsibility |
| --- | --- |
| `parser.py` | Extract timestamped utterances |
| `graph/nodes/chunking.py` | Group utterance indices into question/answer chunks |
| `graph/nodes/open_coding.py` | Extract concepts and quotations |
| `graph/nodes/merge.py` | Apply proposed duplicate merges and advance batches |
| `graph/nodes/axial_coding.py` | Dispatch, parallel grouping, and global synthesis |
| `graph/state.py` | Shared state and reducers |
| `models.py` | Pydantic schemas |
| `main.py`, `db_manager.py` | CLI, reports, and local persistence |

Concept entries store definitions, preliminary subcategories, frequencies, source chunk IDs, and quotations. Subcategories list concepts and optional parent categories; categories contain definitions, subcategory lists, and free-text relations. Pydantic validates output structure, not interpretive validity.

## Limitations

- `is_saturated` means processing completion. No-new-concept rounds are heuristic log signals, not theoretical-saturation tests.
- Preferring existing concepts can anchor later interpretation and conceal novel phenomena.
- Map requests 5–10 preliminary subcategories with single membership; Reduce requests 3–5 higher-level categories. These are prompt constraints rather than data-established findings.
- Axial Map receives concept names, definitions, preliminary labels, and frequencies; Reduce receives subcategory summaries and concept names. Neither receives original transcript quotations directly. Generated relations require evidence review.
- Open-coding labels and axial regrouping are maintained separately and can diverge. Review hierarchy links before downstream use.
- There is no dedicated researcher-review interface, theoretical sampling, full selective coding, systematic negative-case analysis, or analytical memo workflow.
- No evaluation corpus or local test material is included. The project makes no benchmark or state-of-the-art performance claim.

Researchers remain responsible for the unit of analysis, coding decisions, interpretation, and reporting. Record the model, endpoint, prompt version, parameters, and human revisions when using the tool in research.

---

# 架构与研究方法限制

## 执行方式

`graph/workflow.py` 使用 `StateGraph(CodingState)` 构建完整流程与独立主轴编码两种入口。完整流程执行 `chunking -> open_coding -> merge`，循环编码与合并，直至所有片段处理完毕。

主轴分发节点生成运行 ID，`map_router` 将概念字典切片，通过 LangGraph `Send` 分发任务。各 Map 任务提出初步子类属，状态 reducer 收集本轮结果，Reduce 归纳更高层次类属及文字关系。`SqliteSaver` 提供可选检查点持久化。

## 模块

| 模块 | 职责 |
| --- | --- |
| `parser.py` | 提取带时间戳的发言 |
| `graph/nodes/chunking.py` | 按发言索引生成问答分组 |
| `graph/nodes/open_coding.py` | 提取概念与引文 |
| `graph/nodes/merge.py` | 执行重复概念合并建议并推进批次 |
| `graph/nodes/axial_coding.py` | 分发、并行分组和全局归纳 |
| `graph/state.py` | 共享状态与 reducers |
| `models.py` | Pydantic 结构 |
| `main.py`、`db_manager.py` | 命令行、报告及本地存储 |

概念记录保存定义、初步子类属、频次、来源片段 ID 和引文。子类属保存概念列表及可选上级类属；类属保存定义、子类属列表和文字关系。Pydantic 只验证输出结构，不能证明解释成立。

## 限制

- `is_saturated` 表示处理完成，连续无新概念只是启发式日志信号，不是理论饱和检验。
- 优先使用已有概念可能锚定后续解释，遮蔽新现象。
- Map 要求 5～10 个初步子类属且采用单一归属，Reduce 要求 3～5 个更高层次类属。这些是提示词约束，不是数据已经支持的结论。
- 主轴 Map 读取概念名称、定义、初步标签和频次，Reduce 读取子类属摘要及概念名称，两者均不直接读取原始访谈引文。生成关系需要回到证据复核。
- 开放编码标签和主轴重分组分别维护，可能出现差异，下游使用前应检查层级链接。
- 尚未提供专门的研究者复核界面、理论抽样、完整选择性编码、系统反例分析或分析备忘录流程。
- 不包含评估语料或本地测试材料，也不宣称具有基准领先效果。

研究者仍需负责分析单位、编码决策、解释及报告。在研究中使用本工具时，应记录模型、服务地址、提示词版本、参数和人工修订过程。
