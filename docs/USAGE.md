# Usage and configuration

## Providers

Copy `.env.example` to `.env` and configure the selected provider's API key, OpenAI-compatible base URL, and model ID. The aliases `claude`, `qwen`, and `glm` all use `ChatOpenAI`. Structured output support is required.

Select each stage in `config.py`: `CHUNKING_PROVIDER`, `OPEN_CODING_PROVIDER`, `MERGE_PROVIDER`, and `AXIAL_CODING_PROVIDER`. All currently default to `glm`. `BATCH_SIZE` controls open-coding batch size; `SATURATION_ROUNDS` controls only a no-new-concepts log signal.

The current HTTP client disables TLS certificate verification (`verify=False`) and removes standard HTTP proxy environment variables during model initialization. Review these settings and enable certificate verification for your deployment before transmitting sensitive material.

## Input and incremental runs

Use UTF-8 `.md` or `.txt` files in `raw_data/`, with utterances such as `[Participant_001 00:08]: Text`. Speaker labels cannot contain whitespace or square brackets. Timestamps accept `MM:SS` or `HH:MM:SS`; the separator can be `:` or `：`.

```bash
python main.py
python main.py --batch-size 10
python main.py --status
```

New files are selected by filename; editing an already processed file does not automatically recode it. Each run reuses the concept library and regenerates axial categories. Successful input files move to `processed/`.

Run from the repository root. `--raw-data` changes input scanning, but legacy migration and archiving still use `RAW_DATA_DIR` in `config.py`; update the constants together when using custom directories. `--output` changes report storage, not the knowledge base or reset locations. Add custom private paths to your own ignore rules.

## Recovery and axial-only mode

```bash
python main.py
python main.py --discard-checkpoint
python main.py --from-axial --axial-chunk-size 30
python main.py --resume-axial
python main.py --resume-axial AXIAL_THREAD_ID
```

Normal runs derive the checkpoint thread ID from input filenames. Rerun with the same file set to recover an unfinished run. `--discard-checkpoint` starts from fresh input state without erasing the accumulated knowledge base. Recovery uses persisted workflow boundaries; unfinished work may repeat.

`--from-axial` requires concepts in `db/coding_db.json` and uses a separate checkpoint thread. `--resume-axial` accepts the printed thread ID or reads `.last_axial_thread`. Checkpoints may contain complete research text and must remain local.

## Reports and dry runs

| Local path | Contents |
| --- | --- |
| `db/coding_db.json` | Concept library, categories, processed files, chunk coding, and statistics |
| `db/chunks/` | Per-file chunks and coding |
| `db/checkpoints.sqlite` | Normal-workflow checkpoints |
| `db/axial_checkpoints.sqlite` | Axial-only checkpoints |
| `output/report_*.json` | Metadata, chunks with coding, concepts, subcategories, and categories |
| `processed/` | Archived transcripts |

```bash
python main.py --dry-run
```

Normal dry runs still call the model, may incur charges, read the existing concept library, and export reports. They skip main knowledge-base writes and archiving and disable normal checkpoints. Legacy `data/` migration still runs. Axial-only mode creates checkpoint and thread files even with `--dry-run`. These artifacts are private too.

## Reset

Both commands request terminal confirmation. Back up local work first.

```bash
python main.py --reset
python main.py --reset-db-only
```

`--reset` clears `db/` and `output/` and moves archived transcripts to `raw_data/`. `--reset-db-only` clears `db/` and `output/` but leaves `processed/` untouched; move desired inputs back yourself before recoding. Reset uses configured default storage, not arbitrary `--output` locations.

---

# 使用与配置

## 模型配置

将 `.env.example` 复制为 `.env`，填写所选供应商的 API Key、兼容 OpenAI 协议的 Base URL 和模型 ID。`claude`、`qwen`、`glm` 都通过 `ChatOpenAI` 调用，后端需要支持结构化输出。

在 `config.py` 中设置 `CHUNKING_PROVIDER`、`OPEN_CODING_PROVIDER`、`MERGE_PROVIDER`、`AXIAL_CODING_PROVIDER`，当前均默认使用 `glm`。`BATCH_SIZE` 控制开放编码批次大小；`SATURATION_ROUNDS` 只控制无新概念时的日志提示。

当前 HTTP 客户端关闭 TLS 证书校验（`verify=False`），初始化模型时也会移除标准 HTTP 代理环境变量。传输敏感材料前，请检查这些设置，并根据部署环境开启证书校验。

## 输入与增量运行

将 UTF-8 `.md` 或 `.txt` 文件放入 `raw_data/`，发言格式例如 `[受访者001 00:08]： 内容`。发言人标签不能含空白或方括号，时间戳支持 `MM:SS`、`HH:MM:SS`，分隔符支持 `:` 和 `：`。

```bash
python main.py
python main.py --batch-size 10
python main.py --status
```

系统按文件名选择新文件，修改已经处理的文件不会自动触发重编码。每次运行沿用概念库并重新归纳主轴类属，成功处理的输入移入 `processed/`。

请从仓库根目录运行。`--raw-data` 改变扫描位置，但旧目录迁移和归档仍使用 `config.py` 中的 `RAW_DATA_DIR`；自定义目录时应同步修改常量。`--output` 只改变报告位置，不改变知识库或重置目录。自定义私人路径需自行加入忽略规则。

## 恢复与独立主轴编码

```bash
python main.py
python main.py --discard-checkpoint
python main.py --from-axial --axial-chunk-size 30
python main.py --resume-axial
python main.py --resume-axial AXIAL_THREAD_ID
```

普通流程根据输入文件名生成检查点线程 ID，使用同一文件集合重新运行可以恢复未完成流程。`--discard-checkpoint` 从新的输入状态开始，不清空累积知识库。恢复依赖已经持久化的工作流边界，未保存的工作可能重复执行。

`--from-axial` 需要 `db/coding_db.json` 已有概念，使用独立检查点线程。`--resume-axial` 可指定终端打印的线程 ID，或自动读取 `.last_axial_thread`。检查点可能含完整研究文本，应保留在本地。

## 报告与试运行

| 本地路径 | 内容 |
| --- | --- |
| `db/coding_db.json` | 概念库、类属、已处理文件、片段编码及统计 |
| `db/chunks/` | 各文件的片段与编码 |
| `db/checkpoints.sqlite` | 普通流程检查点 |
| `db/axial_checkpoints.sqlite` | 独立主轴检查点 |
| `output/report_*.json` | 元数据、含编码的片段、概念、子类属及类属 |
| `processed/` | 归档访谈 |

```bash
python main.py --dry-run
```

普通试运行仍调用模型、可能产生费用、读取已有概念库并导出报告，但不写入主知识库、不归档文件，也不启用普通检查点。旧 `data/` 目录迁移仍会执行。独立主轴模式即使使用 `--dry-run`，也会创建检查点和线程文件。这些产物同样属于私人数据。

## 重置

两个命令均在终端请求确认，使用前请先备份本地工作。

```bash
python main.py --reset
python main.py --reset-db-only
```

`--reset` 清空 `db/` 和 `output/`，并将归档访谈移回 `raw_data/`。`--reset-db-only` 清空 `db/` 和 `output/`，保留 `processed/`，重编码前需自行移回输入文件。重置使用配置中的默认目录，不会自动清空任意 `--output` 目录。
