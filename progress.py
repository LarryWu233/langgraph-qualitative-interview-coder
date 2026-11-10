"""
Rich 进度面板
提供实时进度显示：当前步骤、当前文件、token 统计
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text

console = Console()


class WorkflowProgress:
    """
    工作流进度管理器。

    用法：
        prog = WorkflowProgress(total_files=3, total_chunks=18)
        with prog.live_display():
            prog.start_step("chunking", "interview_001.md")
            prog.advance_file()
            prog.update_tokens(chunking=1234)
            ...
    """

    STEP_LABELS = {
        "init":         "初始化",
        "chunking":     "问答分组",
        "open_coding":  "开放编码",
        "merge":        "概念合并",
        "axial_coding": "主轴编码",
        "saving":       "保存结果",
        "done":         "完成",
    }

    def __init__(self, total_files: int = 0, total_chunks: int = 0):
        self.total_files = total_files
        self.total_chunks = total_chunks

        # 当前状态
        self._current_step: str = "init"
        self._current_file: str = ""
        self._current_chunk: int = 0
        self._files_done: int = 0

        # token 统计（本次运行）
        self._tokens: dict[str, int] = {
            "chunking": 0,
            "open_coding": 0,
            "merge": 0,
            "axial_coding": 0,
        }
        # 历史累计 token（从 db 读入）
        self._hist_tokens: int = 0

        # rich 组件
        self._file_progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(bar_width=30),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
        )
        self._chunk_progress = Progress(
            SpinnerColumn(),
            TextColumn("[dim]{task.description}"),
            BarColumn(bar_width=25),
            MofNCompleteColumn(),
        )
        self._file_task: TaskID | None = None
        self._chunk_task: TaskID | None = None
        self._live: Live | None = None

    # ── 公开接口 ──────────────────────────────────────

    def set_history_tokens(self, total: int) -> None:
        """设置历史累计 token（从 db 读入）"""
        self._hist_tokens = total

    def start_step(self, step: str, filename: str = "") -> None:
        """切换到新步骤"""
        self._current_step = step
        self._current_file = filename
        self._refresh()

    def set_file(self, filename: str) -> None:
        """更新当前处理的文件名"""
        self._current_file = filename
        self._refresh()

    def advance_file(self) -> None:
        """完成一个文件"""
        self._files_done += 1
        if self._file_task is not None:
            self._file_progress.update(self._file_task, completed=self._files_done)
        self._refresh()

    def set_chunk_progress(self, current: int, total: int, label: str | None = None) -> None:
        """更新 chunk / axial 处理进度（label 可覆盖默认标题）"""
        self._current_chunk = current
        if self._chunk_task is not None:
            desc = label if label else f"chunk {current}/{total}"
            self._chunk_progress.update(
                self._chunk_task,
                completed=current,
                total=total,
                description=desc,
            )
        self._refresh()

    def update_tokens(self, **node_tokens: int) -> None:
        """
        更新 token 统计。
        例：update_tokens(open_coding=512, merge=128)
        """
        for node, count in node_tokens.items():
            if node in self._tokens:
                self._tokens[node] += count
        self._refresh()

    def log(self, message: str, style: str = "dim") -> None:
        """在 live 面板外打印一行日志（不影响进度条）"""
        if self._live:
            self._live.console.print(f"  {message}", style=style)
        else:
            console.print(f"  {message}", style=style)

    # ── Context manager ───────────────────────────────

    @contextmanager
    def live_display(self) -> Generator[None, None, None]:
        """启动 rich Live 面板"""
        self._file_task = self._file_progress.add_task(
            "处理文件",
            total=max(self.total_files, 1),
        )
        self._chunk_task = self._chunk_progress.add_task(
            "chunk 0/0",
            total=max(self.total_chunks, 1),
        )

        with Live(
            self._build_panel(),
            console=console,
            refresh_per_second=4,
            transient=False,
        ) as live:
            self._live = live
            try:
                yield
            finally:
                self._live = None

    # ── 内部渲染 ──────────────────────────────────────

    def _build_panel(self) -> Panel:
        grid = Table.grid(padding=(0, 1))
        grid.add_column(style="bold", min_width=14)
        grid.add_column()

        step_label = self.STEP_LABELS.get(self._current_step, self._current_step)
        grid.add_row("当前步骤:", Text(step_label, style="bold yellow"))

        if self._current_file:
            grid.add_row("当前文件:", Text(self._current_file, style="cyan"))

        # token 统计
        session_total = sum(self._tokens.values())
        grand_total = self._hist_tokens + session_total
        token_text = (
            f"本次 {session_total:,}  |  "
            f"累计 {grand_total:,}  "
            f"[dim](chunking:{self._tokens['chunking']:,} "
            f"open:{self._tokens['open_coding']:,} "
            f"merge:{self._tokens['merge']:,} "
            f"axial:{self._tokens['axial_coding']:,})[/dim]"
        )
        grid.add_row("Token 消耗:", Text.from_markup(token_text))

        # 进度条
        grid.add_row("文件进度:", self._file_progress)
        grid.add_row("Chunk 进度:", self._chunk_progress)

        return Panel(grid, title="[bold]访谈编码工作流[/bold]", border_style="blue")

    def _refresh(self) -> None:
        if self._live:
            self._live.update(self._build_panel())


# ── 便捷函数：打印状态摘要 ────────────────────────────
def print_db_status(db: dict) -> None:
    """打印当前知识库状态（用于 --status 命令）"""
    from rich.table import Table as RTable

    stats = db.get("stats", {})
    processed = db.get("processed_files", [])

    console.rule("[bold blue]知识库状态")

    # 基本统计
    info = RTable.grid(padding=(0, 2))
    info.add_column(style="bold", min_width=16)
    info.add_column()
    info.add_row("已处理文件:", str(len(processed)))
    info.add_row("概念数:", str(len(db.get("concepts", {}))))
    info.add_row("子类属数:", str(len(db.get("subcategories", {}))))
    info.add_row("核心类属数:", str(len(db.get("categories", {}))))
    info.add_row("累计 Token:", f"{stats.get('total_tokens', 0):,}")
    info.add_row("累计 API 调用:", str(stats.get("total_calls", 0)))
    info.add_row("最后更新:", db.get("last_updated", "—"))
    console.print(info)

    # 已处理文件列表
    if processed:
        console.rule("[dim]已处理文件")
        tbl = RTable(show_header=True, header_style="bold")
        tbl.add_column("文件名", style="cyan")
        tbl.add_column("处理时间")
        tbl.add_column("Chunks", justify="right")
        tbl.add_column("Tokens", justify="right")
        for entry in processed:
            tbl.add_row(
                entry.get("file", ""),
                entry.get("processed_at", "")[:19].replace("T", " "),
                str(entry.get("chunks", 0)),
                f"{entry.get('tokens_used', 0):,}",
            )
        console.print(tbl)

    console.rule()


def print_summary(final_state: dict, db: dict) -> None:
    """打印本次运行摘要"""
    from rich.table import Table as RTable

    console.rule("[bold green]编码完成")

    info = RTable.grid(padding=(0, 2))
    info.add_column(style="bold", min_width=14)
    info.add_column()
    info.add_row("问答片段数:", str(len(final_state.get("chunks", []))))
    info.add_row("概念数:", str(len(final_state.get("concepts", {}))))
    info.add_row("子类属数:", str(len(final_state.get("subcategories", {}))))
    info.add_row("核心类属数:", str(len(final_state.get("categories", {}))))

    token_stats = final_state.get("token_stats", {})
    session_total = sum(
        v.get("total_tokens", 0)
        for v in token_stats.values()
        if isinstance(v, dict)
    )
    info.add_row("本次 Token:", f"{session_total:,}")
    info.add_row("累计 Token:", f"{db.get('stats', {}).get('total_tokens', 0):,}")
    console.print(info)

    categories = final_state.get("categories", {})
    if categories:
        console.rule("[dim]核心类属体系")
        for cat_name, cat_data in categories.items():
            console.print(f"  [bold yellow]{cat_name}[/bold yellow]  {cat_data.get('definition', '')}")
            for subcat in cat_data.get("subcategories", []):
                subcat_data = final_state.get("subcategories", {}).get(subcat, {})
                concept_count = len(subcat_data.get("concepts", []))
                console.print(f"    └─ [cyan]{subcat}[/cyan] ({concept_count} 个概念)")

    console.rule()
