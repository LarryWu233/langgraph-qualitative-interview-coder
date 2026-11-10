"""访谈数据编码工作流入口"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

from parser import load_all_files
from config import BATCH_SIZE, RAW_DATA_DIR, PROCESSED_DIR, DB_DIR, OUTPUT_DIR
from graph.workflow import build_workflow
from db_manager import (
    load_db,
    save_db,
    save_file_chunks,
    archive_file,
    record_processed_file,
    get_processed_files,
    update_token_stats,
    migrate_legacy_data_dir,
    reset_full,
    reset_db_only,
)
from progress import WorkflowProgress, print_db_status, print_summary

# checkpoint 数据库路径
CHECKPOINT_DB = DB_DIR / "checkpoints.sqlite"

# 记录最近一次 axial-only 运行的 thread_id，方便 --resume-axial 自动读取
LAST_AXIAL_THREAD_FILE = Path(".last_axial_thread")


# ── 报表导出 ──────────────────────────────────────────────────────────────
def export_report(final_state: dict, output_dir: Path) -> Path:
    """将本次运行结果导出为 JSON 报表快照"""
    output_dir.mkdir(parents=True, exist_ok=True)

    chunks = final_state.get("chunks", [])
    concepts = final_state.get("concepts", {})
    subcategories = final_state.get("subcategories", {})
    categories = final_state.get("categories", {})
    chunk_codings = final_state.get("chunk_codings", {})
    token_stats = final_state.get("token_stats", {})

    session_tokens = sum(
        v.get("total_tokens", 0)
        for v in token_stats.values()
        if isinstance(v, dict)
    )

    # 从 chunks 反推文件名（兼容 checkpoint 恢复后 files 字段为空的情况）
    files_from_chunks = sorted({c.get("file") for c in chunks if c.get("file")})
    files_from_state = list(final_state.get("files", {}).keys())
    files_processed = files_from_chunks if files_from_chunks else files_from_state

    output = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "files_processed": files_processed,
            "total_chunks": len(chunks),
            "total_concepts": len(concepts),
            "total_subcategories": len(subcategories),
            "total_categories": len(categories),
            "session_tokens": session_tokens,
            "token_breakdown": token_stats,
        },
        "chunks": [],
        "concepts": concepts,
        "subcategories": subcategories,
        "categories": categories,
    }

    for chunk in chunks:
        chunk_id = chunk["chunk_id"]
        output["chunks"].append({
            **chunk,
            "coding": chunk_codings.get(chunk_id, []),
        })

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"report_{timestamp}.json"
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path


# ── thread_id 生成 ────────────────────────────────────────────────────────
def make_thread_id(file_names: list[str]) -> str:
    """根据待处理文件名集合生成稳定的 thread_id"""
    key = ",".join(sorted(file_names))
    return hashlib.md5(key.encode()).hexdigest()[:16]


# ── 主流程（完整流程）───────────────────────────────────────────────────────
def run(
    raw_dir: Path = RAW_DATA_DIR,
    output_dir: Path = OUTPUT_DIR,
    batch_size: int = BATCH_SIZE,
    dry_run: bool = False,
    discard_checkpoint: bool = False,
) -> None:
    """增量编码主流程（支持断点续跑）"""
    from rich.console import Console
    console = Console()

    # ── 1. 迁移旧 data/ 目录 ────────────────────────────────────────
    migrated = migrate_legacy_data_dir()
    if migrated > 0:
        console.print(
            f"[yellow]已将 data/ 目录中的 {migrated} 个文件迁移到 raw_data/[/yellow]"
        )

    # ── 2. 确保目录存在 ──────────────────────────────────────────────
    raw_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── 3. 加载知识库 ────────────────────────────────────────────────
    db = load_db()
    processed_files = get_processed_files(db)

    # ── 4. 扫描新文件 ────────────────────────────────────────────────
    all_md = sorted(
        list(raw_dir.glob("*.md")) + list(raw_dir.glob("*.txt"))
    )
    new_files = [f for f in all_md if f.name not in processed_files]

    console.print(f"\n[bold]扫描 {raw_dir}/[/bold]")
    console.print(f"  已处理: {len(processed_files)} 个文件")
    console.print(f"  待处理: {len(new_files)} 个新文件")

    if not new_files:
        console.print("\n[green]没有新文件需要处理。[/green]")
        console.print("  使用 [bold]--status[/bold] 查看知识库状态")
        console.print("  使用 [bold]--reset[/bold] 重置数据库重新处理")
        return

    # ── 5. 加载新文件内容 ────────────────────────────────────────────
    files_data = load_all_files(raw_dir, only_files={f.name for f in new_files})
    if not files_data:
        console.print("[red]新文件解析失败，未找到有效发言[/red]")
        sys.exit(1)

    total_utterances = sum(len(v) for v in files_data.values())
    console.print(f"  加载了 {len(files_data)} 个文件，共 {total_utterances} 条发言")

    files_serialized = {
        fname: [u.model_dump() for u in utterances]
        for fname, utterances in files_data.items()
    }

    # ── 6. thread_id 与 checkpoint 管理 ────────────────────────────────
    thread_id = make_thread_id([f.name for f in new_files])
    run_config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 200,
    }

    # 构建工作流（注入 SqliteSaver）
    checkpoint_db_path = None if dry_run else CHECKPOINT_DB
    app = build_workflow(checkpoint_db=checkpoint_db_path)

    # 检查是否有未完成的 checkpoint
    resume_from_checkpoint = False
    if not dry_run and not discard_checkpoint:
        try:
            existing = app.get_state(run_config)
            if existing and existing.values:
                completed = existing.values.get("completed_chunk_ids", [])
                chunks_done = len(completed)
                console.print(
                    f"\n[yellow]检测到未完成的运行（thread_id={thread_id}）[/yellow]"
                )
                console.print(f"  已完成 {chunks_done} 个 chunk，将从中断点继续")
                console.print("  如需从头开始，请使用 [bold]--discard-checkpoint[/bold]")
                resume_from_checkpoint = True
        except Exception:
            pass  # 没有 checkpoint 或读取失败，正常启动

    if discard_checkpoint and not dry_run:
        console.print(f"[yellow]已放弃旧 checkpoint，将从头开始[/yellow]")
        resume_from_checkpoint = False

    # ── 7. 构建初始 state ────────────────────────────────────────────
    if resume_from_checkpoint:
        # 从 checkpoint 恢复：传 None 让 LangGraph 自动加载上次 state
        initial_state = None
    else:
        initial_state = {
            "files": files_serialized,
            "chunks": [],
            "current_batch_start": 0,
            "batch_size": batch_size,
            "completed_chunk_ids": [],
            # 继承已有概念库（从 db 加载）
            "concepts": db.get("concepts", {}),
            "subcategories": db.get("subcategories", {}),
            "chunk_codings": db.get("chunk_codings", {}),
            "rounds_without_new": 0,
            "prev_concept_count": len(db.get("concepts", {})),
            "is_saturated": False,
            "categories": {},
            "axial_chunk_size": 50,
            "axial_run_id": "",
            "axial_total": 0,
            "axial_completed_count": 0,
            "axial_sub_results": [],
            "entry_point": "full",  # 走完整流程
            "token_stats": {},
            "current_step": "init",
            "current_file": "",
            "log": [],
        }

    # ── 8. 运行工作流（带进度面板）───────────────────────────────────
    prog = WorkflowProgress(
        total_files=len(files_data),
        total_chunks=0,
    )
    prog.set_history_tokens(db.get("stats", {}).get("total_tokens", 0))

    final_state = None

    try:
        with prog.live_display():
            prog.start_step("chunking")

            axial_completed_local = 0   # 本地累计 axial Map 完成数（不依赖 reducer）

            for event in app.stream(initial_state, run_config):  # type: ignore[arg-type]
                for node_name, node_state in event.items():
                    step = node_state.get("current_step", node_name)
                    prog.start_step(step)

                    # ── chunk 进度：从累积 final_state 读取（chunking 节点才有 chunks）──
                    chunks_now = (final_state or {}).get("chunks", []) or node_state.get("chunks", [])
                    if chunks_now:
                        prog.total_chunks = len(chunks_now)
                        # current_batch_start 在 merge 节点更新，优先取 node_state
                        batch_start = node_state.get(
                            "current_batch_start",
                            (final_state or {}).get("current_batch_start", 0),
                        )
                        prog.set_chunk_progress(
                            min(batch_start, len(chunks_now)),
                            len(chunks_now),
                        )

                    # ── axial 进度：复用 chunk 进度条，标题切换 ──
                    if node_state.get("axial_completed_count"):
                        axial_completed_local += node_state["axial_completed_count"]
                    axial_total = node_state.get("axial_total") or (final_state or {}).get("axial_total", 0)
                    if axial_total and step in ("axial_dispatch", "axial_map", "axial_reduce"):
                        prog.set_chunk_progress(axial_completed_local, axial_total,
                                                label=f"axial {axial_completed_local}/{axial_total}")

                    ts = node_state.get("token_stats", {})
                    for node_key, node_data in ts.items():
                        if isinstance(node_data, dict):
                            prog.update_tokens(**{node_key: node_data.get("total_tokens", 0)})

                    for log_line in node_state.get("log", []):
                        prog.log(log_line)

                    if final_state is None:
                        final_state = {**(initial_state or {}), **node_state}
                    else:
                        final_state = {**final_state, **node_state}

            prog.start_step("saving")

    except KeyboardInterrupt:
        console.print("\n[yellow]运行被用户中断[/yellow]")
        if not dry_run:
            console.print(f"[yellow]进度已保存到 {CHECKPOINT_DB}[/yellow]")
            console.print("[yellow]再次运行 python main.py 将自动从中断点继续[/yellow]")
        sys.exit(0)

    except Exception as e:
        console.print(f"\n[red]运行出错: {e}[/red]")
        if not dry_run:
            console.print(f"[yellow]进度已保存到 {CHECKPOINT_DB}[/yellow]")
            console.print("[yellow]再次运行 python main.py 将自动从中断点继续[/yellow]")
        raise

    if final_state is None:
        console.print("[red]工作流未产生结果[/red]")
        sys.exit(1)

    # ── 9. 保存结果 ──────────────────────────────────────────────────
    if not dry_run:
        db["concepts"] = final_state.get("concepts", {})
        db["subcategories"] = final_state.get("subcategories", {})
        db["categories"] = final_state.get("categories", {})

        existing_codings = db.get("chunk_codings", {})
        existing_codings.update(final_state.get("chunk_codings", {}))
        db["chunk_codings"] = existing_codings

        token_stats = final_state.get("token_stats", {})
        update_token_stats(db, token_stats)

        new_chunks = final_state.get("chunks", [])
        # 从 chunks 反推文件名（兼容 checkpoint 恢复后 files_data 为空的情况）
        chunk_files = sorted({c.get("file") for c in new_chunks if c.get("file")})
        target_files = chunk_files if chunk_files else list(files_data.keys())
        for fname in target_files:
            file_chunks_count = sum(1 for c in new_chunks if c.get("file") == fname)
            record_processed_file(db, fname, 0, file_chunks_count)
            save_file_chunks(fname, new_chunks, final_state.get("chunk_codings", {}))
            archive_file(fname)

        save_db(db)

        report_path = export_report(final_state, output_dir)
        console.print(f"\n[green]报表已保存:[/green] {report_path}")
        console.print(f"[green]知识库已更新:[/green] db/coding_db.json")
    else:
        report_path = export_report(final_state, output_dir)
        console.print(f"\n[yellow][dry-run] 报表已生成（知识库未更新）:[/yellow] {report_path}")

    # ── 10. 打印摘要 ──────────────────────────────────────────────────
    print_summary(final_state, db)


# ── 独立主轴编码入口（--from-axial）─────────────────────────────────────────
def run_axial_only(
    output_dir: Path = OUTPUT_DIR,
    chunk_size: int = 50,
    dry_run: bool = False,
) -> None:
    """
    跳过 chunking/open_coding，直接读取 db/coding_db.json 的已有概念，
    运行主轴编码的 Map-Reduce 流程。

    设计原则：
    - 使用全新的 thread_id（axial-{timestamp}），与 Open Coding 的 thread 完全隔离
      （避免 checkpoint 污染）
    - 从 db 加载 concepts 作为 initial_state 注入，确保独立性和幂等性
    """
    from rich.console import Console
    console = Console()

    # ── 1. 加载已有概念库 ────────────────────────────────────────────
    db = load_db()
    existing_concepts = db.get("concepts", {})

    if not existing_concepts:
        console.print("[red]coding_db.json 中未找到概念[/red]")
        console.print("  请先运行完整流程（python main.py）完成开放编码")
        sys.exit(1)

    console.print(
        f"[bold]主轴编码（独立模式）[/bold]\n"
        f"  概念总数: {len(existing_concepts)}\n"
        f"  切片大小: {chunk_size}\n"
        f"  预计 Map 分支数: {(len(existing_concepts) + chunk_size - 1) // chunk_size}\n"
    )

    # ── 2. 生成隔离的 thread_id 并持久化 ────────────────────────────
    # 使用时间戳确保每次都是新 thread，与 Open Coding 的 checkpoint 完全隔离
    thread_id = f"axial-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    run_config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 200,
    }

    # 将 thread_id 写入 .last_axial_thread，方便 --resume-axial 自动读取
    LAST_AXIAL_THREAD_FILE.write_text(thread_id, encoding="utf-8")

    # ── 3. 构建工作流（注入 checkpointer，支持 --resume-axial 续跑）──
    # 使用独立的 axial checkpoint 路径，与 Open Coding 的 checkpoint 完全隔离
    axial_checkpoint_db = DB_DIR / "axial_checkpoints.sqlite"
    app = build_workflow(checkpoint_db=axial_checkpoint_db)

    # ── 4. 构建初始 state ────────────────────────────────────────────
    initial_state = {
        "files": {},
        "chunks": [],
        "current_batch_start": 0,
        "batch_size": 0,
        "completed_chunk_ids": [],
        "concepts": existing_concepts,
        "subcategories": db.get("subcategories", {}),
        "chunk_codings": db.get("chunk_codings", {}),
        "rounds_without_new": 0,
        "prev_concept_count": len(existing_concepts),
        "is_saturated": True,
        "categories": {},
        "axial_chunk_size": chunk_size,
        "axial_run_id": "",
        "axial_total": 0,
        "axial_completed_count": 0,
        "axial_sub_results": [],
        "entry_point": "axial",
        "token_stats": {},
        "current_step": "init",
        "current_file": "",
        "log": [
            f"[主轴-入口] 独立模式启动，从 db/coding_db.json 加载 {len(existing_concepts)} 个概念",
            f"[主轴-入口] thread_id={thread_id}（与 Open Coding 线程隔离）",
        ],
    }

    # ── 5. 运行工作流 ────────────────────────────────────────────────
    # 醒目打印 thread_id，方便中断后用 --resume-axial 续跑
    console.print(f"\n[bold cyan]thread_id = {thread_id}[/bold cyan]")
    console.print(f"[dim]（中断后可用 python main.py --resume-axial {thread_id} 续跑）[/dim]\n")
    final_state = None

    try:
        for event in app.stream(initial_state, run_config):  # type: ignore[arg-type]
            for node_name, node_state in event.items():
                for log_line in node_state.get("log", []):
                    console.print(f"  {log_line}")
                final_state = {**(final_state or initial_state), **node_state}

    except KeyboardInterrupt:
        console.print("\n[yellow]主轴编码被用户中断[/yellow]")
        console.print(
            f"[yellow]如需继续当前进度，请运行：[/yellow]\n"
            f"  [bold]python main.py --resume-axial {thread_id}[/bold]"
        )
        sys.exit(0)

    except Exception as e:
        console.print(f"\n[red]运行出错: {e}[/red]")
        console.print(
            f"[yellow]如需重试当前进度，请运行：[/yellow]\n"
            f"  [bold]python main.py --resume-axial {thread_id}[/bold]"
        )
        raise

    if final_state is None:
        console.print("[red]工作流未产生结果[/red]")
        sys.exit(1)

    # ── 6. 保存结果（仅回写 categories 和 subcategories）────────────
    # 注意：独立模式不修改 concepts（开放编码产出保持不变）
    if not dry_run:
        db["categories"] = final_state.get("categories", {})
        # subcategories 合并：保留 Open Coding 阶段已有的，加上 Map-Reduce 新增的
        new_subcats = final_state.get("subcategories", {})
        existing_subcats = db.get("subcategories", {})
        merged_subcats = {**existing_subcats, **new_subcats}
        db["subcategories"] = merged_subcats

        update_token_stats(db, final_state.get("token_stats", {}))
        save_db(db)

        report_path = export_report(final_state, output_dir)
        console.print(f"\n[green]主轴编码完成[/green]")
        console.print(f"  核心类属: {len(final_state.get('categories', {}))} 个")
        console.print(f"  报表: {report_path}")
        console.print(f"  知识库已更新: db/coding_db.json")
    else:
        report_path = export_report(final_state, output_dir)
        console.print(
            f"\n[yellow][dry-run] 报表已生成（知识库未更新）:[/yellow] {report_path}"
        )

    # 打印摘要
    print_summary(final_state, db)


# ── 主轴编码续跑入口（--resume-axial）──────────────────────────────────────
def run_axial_resume(
    thread_id: str | None = None,
    output_dir: Path = OUTPUT_DIR,
    dry_run: bool = False,
) -> None:
    """
    从中断点续跑主轴编码 Map-Reduce。

    原理：
    - 使用与中断时相同的 thread_id 唤醒 LangGraph Checkpointer
    - LangGraph 自动从最后一个 checkpoint 恢复 state，跳过已完成的 Map 分支
    - 如果 thread_id 未传入，自动读取 .last_axial_thread 文件

    注意：
    - 必须使用与 --from-axial 相同的 axial_checkpoints.sqlite
    - 不需要重新传入 initial_state（LangGraph 从 checkpoint 恢复）
    """
    from rich.console import Console
    console = Console()

    # ── 1. 确定 thread_id ────────────────────────────────────────────
    if not thread_id:
        if LAST_AXIAL_THREAD_FILE.exists():
            thread_id = LAST_AXIAL_THREAD_FILE.read_text(encoding="utf-8").strip()
            console.print(f"[dim]自动读取 .last_axial_thread: {thread_id}[/dim]")
        else:
            console.print("[red]未找到 .last_axial_thread 文件，请手动指定 thread_id[/red]")
            console.print("  用法: python main.py --resume-axial <thread_id>")
            sys.exit(1)

    console.print(
        f"[bold]主轴编码（续跑模式）[/bold]\n"
        f"  thread_id: {thread_id}\n"
    )

    # ── 2. 构建工作流（注入 checkpointer，与 --from-axial 使用同一 db）──
    axial_checkpoint_db = DB_DIR / "axial_checkpoints.sqlite"
    if not axial_checkpoint_db.exists():
        console.print(f"[red]未找到 axial checkpoint 文件: {axial_checkpoint_db}[/red]")
        console.print("  请先运行 python main.py --from-axial 创建初始 checkpoint")
        sys.exit(1)

    app = build_workflow(checkpoint_db=axial_checkpoint_db)
    run_config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 200,
    }

    # ── 3. 检查 checkpoint 状态 ──────────────────────────────────────
    try:
        existing = app.get_state(run_config)
        if not existing or not existing.values:
            console.print(f"[red]未找到 thread_id={thread_id} 的 checkpoint[/red]")
            console.print("  请确认 thread_id 正确，或重新运行 --from-axial")
            sys.exit(1)
        axial_done = existing.values.get("axial_completed_count", 0)
        axial_total = existing.values.get("axial_total", 0)
        console.print(f"  已完成 Map 分支: {axial_done}/{axial_total}")
    except Exception as e:
        console.print(f"[red]读取 checkpoint 失败: {e}[/red]")
        sys.exit(1)

    # ── 4. 续跑（传 None 让 LangGraph 从 checkpoint 恢复 state）──────
    console.print(f"\n[bold cyan]thread_id = {thread_id}[/bold cyan]")
    final_state = None
    db = load_db()

    try:
        # initial_state=None → LangGraph 自动从 checkpoint 恢复
        for event in app.stream(None, run_config):  # type: ignore[arg-type]
            for node_name, node_state in event.items():
                for log_line in node_state.get("log", []):
                    console.print(f"  {log_line}")
                final_state = {**(final_state or {}), **node_state}

    except KeyboardInterrupt:
        console.print("\n[yellow]主轴编码被用户中断[/yellow]")
        console.print(
            f"[yellow]如需继续当前进度，请运行：[/yellow]\n"
            f"  [bold]python main.py --resume-axial {thread_id}[/bold]"
        )
        sys.exit(0)

    except Exception as e:
        console.print(f"\n[red]运行出错: {e}[/red]")
        console.print(
            f"[yellow]如需重试，请运行：[/yellow]\n"
            f"  [bold]python main.py --resume-axial {thread_id}[/bold]"
        )
        raise

    if final_state is None:
        console.print("[red]工作流未产生结果[/red]")
        sys.exit(1)

    # ── 5. 保存结果 ──────────────────────────────────────────────────
    if not dry_run:
        db["categories"] = final_state.get("categories", {})
        new_subcats = final_state.get("subcategories", {})
        existing_subcats = db.get("subcategories", {})
        db["subcategories"] = {**existing_subcats, **new_subcats}
        update_token_stats(db, final_state.get("token_stats", {}))
        save_db(db)

        report_path = export_report(final_state, output_dir)
        console.print(f"\n[green]主轴编码续跑完成[/green]")
        console.print(f"  核心类属: {len(final_state.get('categories', {}))} 个")
        console.print(f"  报表: {report_path}")
    else:
        report_path = export_report(final_state, output_dir)
        console.print(f"\n[yellow][dry-run] 报表已生成（知识库未更新）:[/yellow] {report_path}")

    print_summary(final_state, db)


# ── 子命令处理 ──────────────────────────────────────────────────────────────
def cmd_status() -> None:
    db = load_db()
    print_db_status(db)


def cmd_list_checkpoints() -> None:
    """列出所有未完成的 checkpoint thread"""
    from rich.console import Console
    from rich.table import Table
    console = Console()

    if not CHECKPOINT_DB.exists():
        console.print("[dim]没有 checkpoint 记录[/dim]")
        return

    import sqlite3 as _sqlite3
    try:
        conn = _sqlite3.connect(str(CHECKPOINT_DB))
        cur = conn.execute(
            "SELECT thread_id, checkpoint_id, created_at FROM checkpoints ORDER BY created_at DESC"
        )
        rows = cur.fetchall()
        conn.close()
    except Exception as e:
        console.print(f"[red]读取 checkpoint 失败: {e}[/red]")
        return

    if not rows:
        console.print("[dim]没有 checkpoint 记录[/dim]")
        return

    tbl = Table(show_header=True, header_style="bold")
    tbl.add_column("Thread ID", style="cyan")
    tbl.add_column("Checkpoint ID")
    tbl.add_column("创建时间")
    for row in rows:
        tbl.add_row(str(row[0]), str(row[1]), str(row[2]))
    console.print(tbl)


def cmd_reset(db_only: bool = False) -> None:
    from rich.console import Console
    console = Console()

    if db_only:
        console.print("[bold red]警告：将清空 db/ 和 output/ 目录（processed/ 不变）[/bold red]")
    else:
        console.print("[bold red]警告：将清空 db/ 和 output/，并将 processed/ 中的文件移回 raw_data/[/bold red]")
    console.print("  此操作不可撤销。")

    confirm = input("确认执行？输入 y 继续：").strip().lower()
    if confirm != "y":
        console.print("[yellow]已取消[/yellow]")
        return

    if db_only:
        reset_db_only()
        console.print("[green]已清空 db/ 和 output/（含 checkpoints）[/green]")
    else:
        reset_full(restore_to_raw=True)
        console.print("[green]已重置：db/ 和 output/ 已清空，processed/ 文件已移回 raw_data/[/green]")


# ── 入口 ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(
        description="访谈数据编码工作流",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py                       # 增量处理，自动恢复未完成的运行
  python main.py --status              # 查看知识库状态
  python main.py --list-checkpoints    # 查看所有未完成的 checkpoint
  python main.py --discard-checkpoint  # 放弃旧 checkpoint，从头开始
  python main.py --reset               # 软重置（清空db，文件移回raw_data）
  python main.py --reset-db-only       # 仅清空db/output（保留processed）
  python main.py --dry-run             # 测试运行（不写入db，不归档文件）
  python main.py --batch-size 10       # 调整每轮处理的chunk数量
  python main.py --from-axial          # 跳过开放编码，直接跑主轴编码 Map-Reduce
  python main.py --from-axial --axial-chunk-size 30  # 指定切片大小为 30
        """,
    )
    p.add_argument("--raw-data", default=str(RAW_DATA_DIR), help="原始数据目录")
    p.add_argument("--output", default=str(OUTPUT_DIR), help="报表输出目录")
    p.add_argument("--batch-size", type=int, default=None, help="每轮处理的chunk数量")
    p.add_argument("--status", action="store_true", help="查看知识库状态后退出")
    p.add_argument("--list-checkpoints", action="store_true", help="列出所有 checkpoint")
    p.add_argument("--discard-checkpoint", action="store_true", help="放弃旧 checkpoint，从头开始")
    p.add_argument("--reset", action="store_true", help="软重置：清空db，processed→raw_data")
    p.add_argument("--reset-db-only", action="store_true", help="仅清空db/output，不移动文件")
    p.add_argument("--dry-run", action="store_true", help="测试运行，不写入db，不归档文件")
    p.add_argument(
        "--from-axial", action="store_true",
        help="跳过 chunking/open_coding，直接从 db/coding_db.json 读取已有概念跑主轴编码 Map-Reduce",
    )
    p.add_argument(
        "--axial-chunk-size", type=int, default=50,
        help="主轴编码 Map 阶段切片大小（默认 50）",
    )
    p.add_argument(
        "--resume-axial", nargs="?", const="auto", default=None, metavar="THREAD_ID",
        help=(
            "从中断点续跑主轴编码。"
            "可传入 thread_id（如 axial-20260519-205800），"
            "不传则自动读取 .last_axial_thread 文件"
        ),
    )

    args = p.parse_args()

    if args.status:
        cmd_status()
        sys.exit(0)

    if getattr(args, "list_checkpoints", False):
        cmd_list_checkpoints()
        sys.exit(0)

    if args.reset:
        cmd_reset(db_only=False)
        sys.exit(0)

    if getattr(args, "reset_db_only", False):
        cmd_reset(db_only=True)
        sys.exit(0)

    # ── 主轴编码续跑入口 ────────────────────────────────────────────
    if getattr(args, "resume_axial", None) is not None:
        # --resume-axial 不传值时 const="auto"，传值时为具体 thread_id
        tid = None if args.resume_axial == "auto" else args.resume_axial
        run_axial_resume(
            thread_id=tid,
            output_dir=Path(args.output),
            dry_run=args.dry_run,
        )
        sys.exit(0)

    # ── 独立主轴编码入口 ────────────────────────────────────────────
    if getattr(args, "from_axial", False):
        run_axial_only(
            output_dir=Path(args.output),
            chunk_size=args.axial_chunk_size,
            dry_run=args.dry_run,
        )
        sys.exit(0)

    effective_batch_size = BATCH_SIZE
    if args.batch_size:
        effective_batch_size = args.batch_size

    run(
        raw_dir=Path(args.raw_data),
        output_dir=Path(args.output),
        batch_size=effective_batch_size,
        dry_run=args.dry_run,
        discard_checkpoint=getattr(args, "discard_checkpoint", False),
    )
