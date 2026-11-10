"""
知识库管理器
负责：加载/保存累积知识库、归档已处理文件、迁移旧 data/ 目录
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from config import DB_FILE, DB_DIR, CHUNKS_DIR, PROCESSED_DIR, RAW_DATA_DIR


# ── 空知识库模板 ──────────────────────────────────────
def _empty_db() -> dict:
    return {
        "version": 1,
        "created_at": datetime.now().isoformat(),
        "last_updated": datetime.now().isoformat(),
        "processed_files": [],          # list[ProcessedFileEntry]
        "concepts": {},
        "subcategories": {},
        "categories": {},
        "chunk_codings": {},            # chunk_id -> [ConceptItem]
        "stats": {
            "total_tokens": 0,
            "chunking_tokens": 0,
            "open_coding_tokens": 0,
            "merge_tokens": 0,
            "axial_coding_tokens": 0,
            "total_calls": 0,
        },
    }


# ── 加载知识库 ────────────────────────────────────────
def load_db() -> dict:
    """加载 coding_db.json；不存在则返回空库"""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)

    if DB_FILE.exists():
        try:
            data = json.loads(DB_FILE.read_text(encoding="utf-8"))
            # 兼容旧版本：补全缺失字段
            data.setdefault("chunk_codings", {})
            data.setdefault("stats", {
                "total_tokens": 0,
                "chunking_tokens": 0,
                "open_coding_tokens": 0,
                "merge_tokens": 0,
                "axial_coding_tokens": 0,
                "total_calls": 0,
            })
            return data
        except (json.JSONDecodeError, KeyError):
            print("[警告] coding_db.json 格式异常，将使用空库")
            return _empty_db()
    return _empty_db()


# ── 保存知识库 ────────────────────────────────────────
def save_db(db: dict) -> None:
    """将知识库写回 coding_db.json"""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    db["last_updated"] = datetime.now().isoformat()
    DB_FILE.write_text(
        json.dumps(db, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── 保存单文件 chunks ─────────────────────────────────
def save_file_chunks(filename: str, chunks: list[dict], chunk_codings: dict) -> None:
    """将单个文件的 chunks 及其编码结果保存到 db/chunks/<file>.json"""
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    stem = Path(filename).stem
    out_path = CHUNKS_DIR / f"{stem}.json"
    payload = {
        "file": filename,
        "saved_at": datetime.now().isoformat(),
        "chunks": [c for c in chunks if c.get("file") == filename],
        "chunk_codings": {
            cid: coding
            for cid, coding in chunk_codings.items()
            if cid.startswith(stem)
        },
    }
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── 归档已处理文件 ────────────────────────────────────
def archive_file(filename: str, tokens_used: int = 0, chunks_count: int = 0) -> None:
    """将 raw_data/<filename> 移动到 processed/<filename>"""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    src = RAW_DATA_DIR / filename
    dst = PROCESSED_DIR / filename
    if src.exists():
        shutil.move(str(src), str(dst))


def record_processed_file(
    db: dict,
    filename: str,
    tokens_used: int = 0,
    chunks_count: int = 0,
) -> None:
    """在 db 的 processed_files 列表中记录该文件"""
    # 避免重复记录
    existing = {e["file"] for e in db.get("processed_files", [])}
    if filename not in existing:
        db.setdefault("processed_files", []).append({
            "file": filename,
            "processed_at": datetime.now().isoformat(),
            "chunks": chunks_count,
            "tokens_used": tokens_used,
        })


# ── 查询已处理文件集合 ────────────────────────────────
def get_processed_files(db: dict) -> set[str]:
    """返回已处理文件名的集合"""
    return {e["file"] for e in db.get("processed_files", [])}


# ── 更新 token 统计 ───────────────────────────────────
def update_token_stats(db: dict, token_stats: dict) -> None:
    """将本次运行的 token 统计累加到 db.stats"""
    stats = db.setdefault("stats", {
        "total_tokens": 0,
        "chunking_tokens": 0,
        "open_coding_tokens": 0,
        "merge_tokens": 0,
        "axial_coding_tokens": 0,
        "total_calls": 0,
    })

    for node in ("chunking", "open_coding", "merge", "axial_coding"):
        node_data = token_stats.get(node, {})
        key = f"{node}_tokens"
        stats[key] = stats.get(key, 0) + node_data.get("total_tokens", 0)
        stats["total_tokens"] = stats.get("total_tokens", 0) + node_data.get("total_tokens", 0)
        stats["total_calls"] = stats.get("total_calls", 0) + node_data.get("calls", 0)


# ── 迁移旧 data/ 目录 ─────────────────────────────────
def migrate_legacy_data_dir() -> int:
    """
    如果存在旧的 data/ 目录且其中有 .md 或 .txt 文件，
    自动将文件迁移到 raw_data/，返回迁移文件数量。
    """
    legacy = Path("data")
    if not legacy.exists():
        return 0

    interview_files = list(legacy.glob("*.md")) + list(legacy.glob("*.txt"))
    if not interview_files:
        return 0

    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    count = 0
    for f in interview_files:
        dst = RAW_DATA_DIR / f.name
        if not dst.exists():
            shutil.copy2(str(f), str(dst))
            count += 1

    return count


# ── 重置操作 ──────────────────────────────────────────
def reset_full(restore_to_raw: bool = True) -> None:
    """
    软重置：清空 db/（含 checkpoints.sqlite）和 output/，
    如果 restore_to_raw=True，将 processed/ 中的文件移回 raw_data/
    """
    import shutil as _shutil

    # 清空 db/（包含 coding_db.json、checkpoints.sqlite、chunks/）
    if DB_DIR.exists():
        _shutil.rmtree(str(DB_DIR))
    DB_DIR.mkdir(parents=True, exist_ok=True)
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)

    # 清空 output/
    output_dir = Path("output")
    if output_dir.exists():
        _shutil.rmtree(str(output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)

    # 将 processed/ 文件移回 raw_data/
    if restore_to_raw and PROCESSED_DIR.exists():
        RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
        for pattern in ("*.md", "*.txt"):
            for f in PROCESSED_DIR.glob(pattern):
                dst = RAW_DATA_DIR / f.name
                if not dst.exists():
                    _shutil.move(str(f), str(dst))


def reset_db_only() -> None:
    """仅清空 db/（含 checkpoints.sqlite）和 output/，不移动 processed/ 中的文件"""
    import shutil as _shutil

    if DB_DIR.exists():
        _shutil.rmtree(str(DB_DIR))
    DB_DIR.mkdir(parents=True, exist_ok=True)
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)

    output_dir = Path("output")
    if output_dir.exists():
        _shutil.rmtree(str(output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)
