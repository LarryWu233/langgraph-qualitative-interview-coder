"""MD/TXT 文件解析器 - 规则预解析"""
import re
from pathlib import Path
from models import Utterance


def parse_interview_file(filepath: str | Path) -> list[Utterance]:
    """
    解析单个访谈文件（.md 或 .txt），提取所有发言。

    支持的格式：
        [任意名字 HH:MM:SS]： 发言内容
        [任意名字 MM:SS]: 发言内容

    例如：
        [发言人1 00:00]： 提问
        [提问人 40:14]： 提问
        [受访者001 40:23]： 回答
    """
    filepath = Path(filepath)
    text = filepath.read_text(encoding="utf-8")

    # 匹配 [任意名字 HH:MM:SS] 或 [任意名字 MM:SS] 格式
    # 名字可以是任意非空白、非方括号字符（含中文、英文、数字）
    pattern = r'\[([^\s\[\]]+)\s+(\d{1,2}:\d{2}(?::\d{2})?)\](?:：|:)\s*'
    parts = re.split(pattern, text)

    utterances: list[Utterance] = []
    # parts: [前导文本, 发言人名字, 时间戳, 发言内容, 发言人名字, 时间戳, 发言内容, ...]
    i = 1
    while i + 2 < len(parts):
        speaker = parts[i].strip()
        timestamp = parts[i + 1].strip()
        content = parts[i + 2].strip()

        if content:
            utterances.append(Utterance(
                speaker=speaker,
                timestamp=timestamp,
                text=content,
            ))
        i += 3

    return utterances


# 向后兼容别名
parse_md_file = parse_interview_file


def load_all_files(
    data_dir: str | Path,
    only_files: set[str] | None = None,
) -> dict[str, list[Utterance]]:
    """
    加载目录下的访谈文件（.md 和 .txt）。

    only_files: 若指定，则只加载文件名在该集合中的文件；
                若为 None，则加载全部 .md 和 .txt 文件。
    """
    data_dir = Path(data_dir)
    result = {}

    # 同时扫描 .md 和 .txt，按文件名排序
    all_files = sorted(
        list(data_dir.glob("*.md")) + list(data_dir.glob("*.txt"))
    )

    for f in all_files:
        if only_files is not None and f.name not in only_files:
            continue
        utterances = parse_interview_file(f)
        if utterances:
            result[f.name] = utterances

    return result
