"""Session-owned attachments, atomically stored with parsed source locations."""
import hashlib
import os
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from pathlib import PurePosixPath
from uuid import uuid4

from fastapi import HTTPException

from src.server.session import app_db
from src.server.conversations import storage_session,scoped

MAX_BYTES = 5 * 1024 * 1024
MAX_TEXT = 60000
MAX_FILES = 12
MAX_SESSION_TEXT = 180000


def init_documents():
    with app_db() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, name TEXT NOT NULL,
            digest TEXT NOT NULL, original BLOB NOT NULL, chunks TEXT NOT NULL,
            UNIQUE(user_id, digest, name))""")
        db.execute("CREATE INDEX IF NOT EXISTS documents_user ON documents(user_id)")
        db.execute('CREATE TABLE IF NOT EXISTS conversation_documents(user_id TEXT NOT NULL,session_id TEXT NOT NULL,document_id TEXT NOT NULL,PRIMARY KEY(user_id,session_id,document_id))')


def parse_document(name, content):
    if (not name or len(name) > 180 or "/" in name or "\\" in name
            or ":" in name or name in {".", ".."} or any(ord(c) < 32 for c in name)):
        raise ValueError("文件名包含非法路径或字符")
    suffix = PurePosixPath(name).suffix.lower()
    if suffix not in {".txt", ".md", ".pdf", ".xlsx", ".docx"}:
        raise ValueError("仅支持 TXT、Markdown、PDF、XLSX 和 DOCX")
    if not content or len(content) > MAX_BYTES:
        raise ValueError("文件为空或超过 5 MiB")
    pages = []
    if suffix in {".pdf", ".xlsx", ".docx"}:
        if suffix == ".pdf" and not content.startswith(b"%PDF-"):
            raise ValueError("PDF 格式无效")
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / "input", Path(tmp) / "output.json"
            source.write_bytes(content)
            try:
                process = subprocess.Popen([sys.executable, "-m", "src.server.file_parsers", str(source), name, str(output)],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    process.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    try:
                        if os.name == "nt":
                            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                           timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    finally:
                        if process.poll() is None:
                            process.kill()
                        process.wait(timeout=5)
                    raise
                if process.returncode:
                    raise ValueError("解析子进程执行失败")
                result = json.loads(output.read_text(encoding="utf-8"))
            except (subprocess.SubprocessError, OSError, ValueError) as error:
                raise ValueError("解析失败或超过 60 秒，请缩小文件") from error
            if "error" in result:
                raise ValueError(result["error"])
            return result["chunks"]
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("文本需使用 UTF-8 编码") from error
    if "\x00" in text:
        raise ValueError("文本包含二进制内容")
    return text_chunks([(None, text, "native")])


def text_chunks(pages):
    if sum(len(text) for _, text, _ in pages) > MAX_TEXT:
        raise ValueError("解析文本超过 60000 字符")
    chunks = []
    for page, text, method in pages:
        lines = text.splitlines()
        start = 0
        while start < len(lines):
            end = start
            size = 0
            while end < len(lines) and end - start < 18 and size + len(lines[end]) <= 1800:
                size += len(lines[end]) + 1
                end += 1
            if end == start:
                raise ValueError("单行文本超过 1800 字符，请分段")
            body = "\n".join(lines[start:end]).strip()
            if body:
                chunks.append({"index": len(chunks), "page": page, "start": start + 1,
                               "end": end, "text": body, "method": method, "ocr_review": method == "ocr"})
            start = end
    if not chunks:
        raise ValueError("未提取到文字，扫描 PDF 需要 OCR，当前暂不支持")
    return chunks


def store_document(user_id, name, content):
    chunks = parse_document(name, content)
    digest = hashlib.sha256(content).hexdigest()
    with app_db() as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT id FROM documents WHERE user_id=? AND digest=? AND name=?",
                              (user_id, digest, name)).fetchone()
        if existing:
            db.execute('INSERT OR IGNORE INTO conversation_documents VALUES (?,?,?)',(user_id,storage_session(user_id),existing[0]))
            return existing[0]
        rows = db.execute("SELECT chunks FROM documents WHERE user_id=?", (user_id,)).fetchall()
        total = sum(len(c["text"]) for row in rows for c in json.loads(row[0]))
        if len(rows) >= MAX_FILES or total + sum(len(c["text"]) for c in chunks) > MAX_SESSION_TEXT:
            raise ValueError("当前账号或访客的独立附件达到数量或文本总量上限，请清理不再使用的文件")
        identity = uuid4().hex
        db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)",
                   (identity, user_id, name, digest, content, json.dumps(chunks, ensure_ascii=False)))
        db.execute('INSERT INTO conversation_documents VALUES (?,?,?)',(user_id,storage_session(user_id),identity))
    return identity


def documents(user_id):
    with app_db() as db:
        if scoped(user_id):
            rows=db.execute('''SELECT d.id,d.name,d.chunks FROM documents d JOIN conversation_documents c ON c.document_id=d.id AND c.user_id=d.user_id
                WHERE d.user_id=? AND c.session_id=? ORDER BY d.rowid''',(user_id,storage_session(user_id))).fetchall()
        else:
            rows = db.execute("SELECT id,name,chunks FROM documents WHERE user_id=? ORDER BY rowid",(user_id,)).fetchall()
    return [{"id": identity, "name": name, "status": "ready", "chunks": json.loads(chunks)}
            for identity, name, chunks in rows]


def get_document(user_id, identity):
    if not re.fullmatch(r"[0-9a-f]{32}", identity):
        raise HTTPException(404, "文件不存在")
    return next((d for d in documents(user_id) if d["id"] == identity), None) or missing()


def missing():
    raise HTTPException(404, "文件不存在")


def source_label(source):
    if source.get("method") == "docx":
        position = (f'表格{source["table"]} 行{source["row"]} 列{source["column"]}' if "table" in source else f'段落{source["paragraph"]}')
        return f'{source["name"]} {position} 字符{source["offset_start"]}–{source["offset_end"]}（左闭右开）'
    if source.get("sheet"):
        return f'{source["name"]} 工作表「{source["sheet"]}」{source["range"]}'
    page = f'第 {source["page"]} 页 ' if source["page"] else ""
    return f'{source["name"]} {page}L{source["start"]}–{source["end"]}'

