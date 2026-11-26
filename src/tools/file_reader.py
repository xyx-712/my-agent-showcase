from pathlib import Path

from src.config import DEMO_FILES_DIR, IS_DEMO


MAX_DEMO_FILE_BYTES = 64 * 1024

def read_demo_file(path):
    error = {"error": "只能读取演示目录内符合大小限制的 UTF-8 文本文件"}
    try:
        relative = Path(path.replace("\\", "/"))
        if relative.anchor or ":" in path or ".." in relative.parts:
            return error
        root = DEMO_FILES_DIR.resolve(strict=True)
        if root != DEMO_FILES_DIR or not root.is_dir():
            return error
        target = (root / relative).resolve(strict=True)
        if not target.is_relative_to(root) or not target.is_file():
            return error
        if target.stat().st_nlink != 1:
            return error
        with target.open("rb") as file:
            content = file.read(MAX_DEMO_FILE_BYTES + 1)
        if len(content) > MAX_DEMO_FILE_BYTES:
            return error
        return {"path": relative.as_posix(), "content": content.decode("utf-8")}
    except (OSError, ValueError, RuntimeError):
        return error


def file_reader(path: str):
    if IS_DEMO:
        return read_demo_file(path)
    try:
        file = Path(path)
        if not file.exists():
            return {"error": "文件不存在"}
        if not file.is_file():
            return {"error": "不是文件"}
        return {"path": str(file), "content": file.read_text(encoding="utf-8")}
    except Exception as error:
        return {"error": str(error)}
