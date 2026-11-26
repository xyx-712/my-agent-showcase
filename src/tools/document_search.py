"""Keyword search over a bounded local corpus; no caller-supplied paths."""
import re

from src.config import DEMO_FILES_DIR
from src.tools.file_reader import read_demo_file


def search_documents(keyword):
    if not re.fullmatch(r"[\w-]{1,32}", keyword):
        raise ValueError("检索关键词格式无效")
    root = DEMO_FILES_DIR
    marker = f"项目：{keyword}"
    if not root.is_dir():
        return []
    paths = sorted(path for path in root.iterdir() if path.suffix.lower() in {".md", ".txt"})
    if len(paths) > 64:
        raise ValueError("演示资料数量超过上限")
    results = []
    for path in paths:
        document = read_demo_file(path.name)
        if "error" in document:
            continue
        lines = document["content"].lstrip("\ufeff").splitlines()
        starts = [i for i, line in enumerate(lines) if line.startswith("## ")]
        for start, end in zip(starts, starts[1:] + [len(lines)]):
            while end > start + 1 and not lines[end - 1].strip():
                end -= 1
            section = lines[start + 1:end]
            if marker in section:
                results.append({"file": path.name, "heading": lines[start][3:],
                                "start": start + 1, "end": end, "lines": section})
                if len(results) > 32:
                    raise ValueError("匹配段落超过上限")
    return results
