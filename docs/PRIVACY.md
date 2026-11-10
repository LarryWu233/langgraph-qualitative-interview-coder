# Private data and publication boundaries

## Public contents

The public distribution contains reviewed application source, dependency declarations, placeholder configuration, and bilingual documentation. Examples are fictional. Existing local tests, interview files, generated results, model credentials, and original Git history are excluded.

## Local-only contents

- `.env` and private environment files; only `.env.example` is public.
- `raw_data/`, legacy `data/`, and archived transcripts in `processed/`.
- Everything in `db/`, including quotations, filenames, chunks, coding, and SQLite checkpoints.
- `output/`, `.last_axial_thread`, logs, and temporary exports.
- Local tests, fixtures, experiments, notebooks, environments, caches, and editor settings.

Outputs and checkpoints may be as sensitive as the original transcripts. Default-path ignore rules do not cover custom locations automatically; add them explicitly before committing. Keep private files out of source directories.

## Model processing

The application sends transcript text and coding context to the configured model endpoint. Local storage does not mean local inference. Review the provider's processing and retention arrangements and obtain appropriate authorization before submitting participant material. Anonymize identifiers and contextual details according to your research protocol.

The current client disables TLS certificate verification and clears standard HTTP proxy environment variables; review `config.py` before deployment. Model-generated quotation fields are not automatically verified as exact substrings of their source transcripts.

## Future commits

```bash
git status --short
git diff --cached --name-only
git diff --cached
```

Review filenames and staged contents. `.gitignore` does not remove tracked files or erase old commits. If an old repository contains private material, publish from an audited clean history. Do not push old branches or tags into the public repository.

Do not attach private data or personal test material to issues or pull requests. Use a minimal fictional example instead.

---

# 私人数据与公开发布边界

## 公开内容

公开版本仅包含审核后的应用源码、依赖声明、占位配置和双语文档，示例均为虚构内容。已有本地测试、访谈文件、生成结果、模型凭据及原始 Git 历史均不包含在内。

## 仅供本地保存的内容

- `.env` 等私人环境文件，仅 `.env.example` 公开。
- `raw_data/`、旧 `data/` 和 `processed/` 中的归档访谈。
- `db/` 的全部内容，包括引文、文件名、片段、编码及 SQLite 检查点。
- `output/`、`.last_axial_thread`、日志及临时导出。
- 本地测试、测试样例、实验、笔记本、环境、缓存和编辑器配置。

输出和检查点可能与原始访谈同样敏感。默认路径忽略规则不能自动覆盖自定义位置，提交前需明确添加规则。不要把私人文件放入源码目录。

## 模型处理

应用会向配置的模型服务发送访谈文本和编码上下文。本地保存不代表本地推理。提交受访者材料前，应审查服务商的数据处理与保留安排，取得相应授权，并按照研究方案匿名化标识符及上下文细节。

当前客户端关闭 TLS 证书校验，并清除标准 HTTP 代理环境变量，部署前请检查 `config.py`。模型生成的引文字段不会自动验证为来源访谈中的精确子串。

## 后续提交

```bash
git status --short
git diff --cached --name-only
git diff --cached
```

同时检查文件名和暂存内容。`.gitignore` 不会移除已经跟踪的文件或清除旧提交。旧仓库含私人材料时，应从审核过的干净历史发布。不要把旧分支或标签推入公开仓库。

不要在 issue 或 pull request 中附上私人数据或个人测试材料，应使用最小化的虚构示例。
