# LangGraph Qualitative Interview Coder

An LLM-assisted qualitative interview coding workflow built with LangGraph. It organizes timestamped transcripts into candidate concepts, subcategories, and higher-level categories through open coding, concept merging, and hierarchical axial coding.

English comes first and Chinese follows in every document. The current CLI messages, model prompts, and many code comments are in Chinese.

## Features

- Parse UTF-8 `.md` and `.txt` interview transcripts.
- Group utterances into question-and-answer chunks using an LLM.
- Extract concepts, definitions, preliminary subcategories, and supporting quotations.
- Reuse a concept library across input batches and merge proposed duplicates.
- Run parallel axial grouping through LangGraph `Send`, followed by global synthesis.
- Save SQLite workflow checkpoints, export JSON reports, and track token usage.
- Rerun axial coding independently from previously saved concepts.

## Workflow

```text
Transcript parsing -> LLM question/answer grouping
    -> [open coding -> concept merging] for every batch
    -> axial dispatch -> parallel grouping -> global category synthesis
    -> local knowledge base, JSON report, and transcript archive
```

LangGraph manages state and execution; the language model generates coding suggestions. Parallel branches process concept subsets and do not represent independent researchers reaching consensus.

## Quick start

Use Python 3.12 and run commands from the repository root. A backend compatible with OpenAI Chat Completions and LangChain structured output is required.

```bash
git clone https://github.com/LarryWu233/langgraph-qualitative-interview-coder.git
cd langgraph-qualitative-interview-coder
python -m venv .venv
```

Activate the environment:

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Copy the configuration template and create the input directory:

```powershell
# Windows PowerShell
Copy-Item .env.example .env
New-Item -ItemType Directory -Force raw_data
```

```bash
# macOS / Linux
cp .env.example .env
mkdir -p raw_data
```

Edit `.env` with your backend's key, base URL, and model ID. All four stages currently default to `glm` in `config.py`; configure `GLM_*` or change the stage provider constants. The aliases `claude`, `qwen`, and `glm` all use `ChatOpenAI`, so every endpoint must use the OpenAI-compatible protocol. Native Anthropic endpoints are not supported directly.

Place your own transcripts in `raw_data/`, then run:

```bash
python main.py
```

This format example is entirely fictional:

```text
[Interviewer 00:00]: How do you organize your weekly tasks?
[Participant_001 00:08]: I keep a shared calendar and review it every Monday.
```

Speaker labels cannot contain whitespace or square brackets. Timestamps accept `MM:SS` and `HH:MM:SS`; `:` and `：` are both accepted after the closing bracket.

## Commands and outputs

```bash
python main.py --status
python main.py --batch-size 10
python main.py --from-axial --axial-chunk-size 30
python main.py --resume-axial
```

Rerunning the normal command can resume an unfinished checkpoint for the same input file set. Results are stored locally in `db/coding_db.json`, `db/chunks/`, and `output/report_*.json`; successfully processed transcripts move to `processed/`.

## Source and documentation

| Path | Purpose |
| --- | --- |
| `main.py` | CLI, persistence, and report export |
| `graph/` | LangGraph topology, state, and coding nodes |
| `prompts/` | Chinese grouping and coding prompts |
| `models.py` | Pydantic structured-output models |
| `config.py`, `.env.example` | Provider settings and placeholder configuration |
| `parser.py`, `db_manager.py` | Transcript parsing and local storage |
| `progress.py`, `token_utils.py` | Progress display and token accounting |

- [Usage and configuration](docs/USAGE.md)
- [Architecture and methodological limitations](docs/ARCHITECTURE.md)
- [Private data and publication boundaries](docs/PRIVACY.md)

Runtime directories are excluded from version control. This public distribution contains no interview corpus, existing results, local tests, credentials, or previous Git history. Documentation examples are fictional.

## Research scope

Treat outputs as candidate interpretations for researcher review. `is_saturated` means all available chunks have been processed; it does not establish theoretical saturation. The workflow does not implement theoretical sampling or a complete selective-coding procedure and makes no state-of-the-art accuracy claim.

Model calls send interview content to the configured backend. The current HTTP client also disables TLS certificate verification; review `config.py` and the [privacy notes](docs/PRIVACY.md) before supplying sensitive material.

---

# 基于 LangGraph 的质性访谈辅助编码工具

本项目使用 LangGraph 编排大语言模型工作流，通过开放编码、概念合并和分层主轴编码，将带时间戳的访谈文本整理为候选概念、子类属及更高层次的类属。

所有文档均为英文在前、中文在后。当前命令行提示、模型提示词和较多代码注释使用中文。

## 功能

- 解析 UTF-8 `.md`、`.txt` 访谈文本。
- 使用 LLM 将发言组织为问答片段。
- 提取概念、定义、初步子类属及原文引文。
- 跨批次累积概念库，合并模型建议的重复概念。
- 通过 LangGraph `Send` 并行完成主轴分组，再全局归纳。
- 使用 SQLite 保存工作流检查点，导出 JSON 报告并统计 token 用量。
- 从已有概念库独立重跑主轴编码。

## 工作流程

```text
访谈解析 -> LLM 问答分组
    -> 按批次循环执行 [开放编码 -> 概念合并]
    -> 主轴任务分发 -> 并行分组 -> 全局类属归纳
    -> 本地知识库、JSON 报告、访谈归档
```

LangGraph 负责状态和流程调度，语言模型生成编码建议。并行分支处理概念子集，不代表独立研究者之间已经形成编码共识。

## 快速开始

建议使用 Python 3.12，并在仓库根目录运行。后端需要兼容 OpenAI Chat Completions 协议及 LangChain 结构化输出。

```bash
git clone https://github.com/LarryWu233/langgraph-qualitative-interview-coder.git
cd langgraph-qualitative-interview-coder
python -m venv .venv
```

激活环境：

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

安装依赖：

```bash
python -m pip install -r requirements.txt
```

复制配置模板并创建输入目录：

```powershell
# Windows PowerShell
Copy-Item .env.example .env
New-Item -ItemType Directory -Force raw_data
```

```bash
# macOS / Linux
cp .env.example .env
mkdir -p raw_data
```

在 `.env` 中填写后端密钥、Base URL 和模型 ID。`config.py` 中四个阶段当前默认使用 `glm`，需要填写 `GLM_*` 或修改各阶段供应商常量。`claude`、`qwen`、`glm` 均通过 `ChatOpenAI` 调用，服务必须兼容 OpenAI 协议，不能直接使用原生 Anthropic 接口。

将自己的访谈放入 `raw_data/`，然后运行：

```bash
python main.py
```

以下格式示例完全虚构：

```text
[访谈者 00:00]： 你怎样安排每周的任务？
[受访者001 00:08]： 我使用共享日历，每周一检查一次。
```

发言人标签不能包含空白字符或方括号。时间戳支持 `MM:SS`、`HH:MM:SS`，右方括号后支持英文冒号 `:` 或中文冒号 `：`。

## 命令与输出

```bash
python main.py --status
python main.py --batch-size 10
python main.py --from-axial --axial-chunk-size 30
python main.py --resume-axial
```

同一组输入文件对应的流程未完成时，重新运行普通命令可恢复检查点。结果保存在本地 `db/coding_db.json`、`db/chunks/` 和 `output/report_*.json`，成功处理的访谈移入 `processed/`。

## 源码与文档

| 路径 | 用途 |
| --- | --- |
| `main.py` | 命令行、结果保存和报告导出 |
| `graph/` | LangGraph 拓扑、状态及编码节点 |
| `prompts/` | 问答分组和编码的中文提示词 |
| `models.py` | Pydantic 结构化输出模型 |
| `config.py`、`.env.example` | 模型配置与占位模板 |
| `parser.py`、`db_manager.py` | 访谈解析与本地存储 |
| `progress.py`、`token_utils.py` | 进度展示与 token 统计 |

- [使用与配置](docs/USAGE.md)
- [架构与研究方法限制](docs/ARCHITECTURE.md)
- [私人数据与公开发布边界](docs/PRIVACY.md)

运行目录已加入 Git 忽略规则。公开版本不包含访谈语料、已有结果、本地测试、凭据及旧 Git 历史；文档示例均为虚构内容。

## 研究用途边界

输出应作为研究者复核的候选解释。`is_saturated` 仅表示现有片段处理完毕，不能证明理论饱和。工作流尚未实现理论抽样或完整选择性编码，也不宣称具有最先进的编码准确率。

模型调用会向配置的后端发送访谈内容。当前 HTTP 客户端也关闭了 TLS 证书校验；提供敏感材料前，请检查 `config.py` 并阅读[隐私说明](docs/PRIVACY.md)。
