"""Bounded file parsers, run in a separate process by the upload service."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile


def excel_chunks(content):
    from openpyxl import load_workbook
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        entries = archive.infolist()
        if (len(entries) > 2000 or sum(e.file_size for e in entries) > 30 * 1024 * 1024
                or any(e.file_size > 10 * 1024 * 1024 or e.flag_bits & 1 or
                       e.file_size / max(e.compress_size, 1) > 1000 for e in entries)):
            raise ValueError("Excel 展开规模超过安全上限")
        if any("vbaproject" in e.filename.lower() for e in entries):
            raise ValueError("不支持含宏的工作簿")
    formulas = load_workbook(io.BytesIO(content), read_only=True, data_only=False, keep_links=False)
    values = load_workbook(io.BytesIO(content), read_only=True, data_only=True, keep_links=False)
    result = []
    cells = 0
    try:
        if len(formulas.sheetnames) > 20:
            raise ValueError("Excel 超过 20 个工作表")
        for sheet in formulas:
            if sheet.max_row > 10000 or sheet.max_column > 200:
                raise ValueError("Excel 行列数超过上限")
            cached = values[sheet.title]
            for row in sheet:
                cells += len(row)
                if cells > 50000:
                    raise ValueError("Excel 超过 50000 个单元格")
                parts = []
                first = last = None
                for cell in row:
                    if cell.value is None:
                        continue
                    value = cell.value.isoformat() if hasattr(cell.value, "isoformat") else str(cell.value)
                    if cell.data_type == "f":
                        cache = cached[cell.coordinate].value
                        value += f" [公式缓存：{cache if cache is not None else '缺失'}；缓存可能过期，未执行重算]"
                    parts.append(f"{cell.coordinate}={value}")
                    first = first or cell.coordinate
                    last = cell.coordinate
                if parts:
                    text = "；".join(parts)
                    if len(text) > 1800:
                        raise ValueError("Excel 单行文本超过 1800 字符")
                    result.append({"index": len(result), "page": None, "start": row[0].row, "end": row[0].row,
                                   "sheet": sheet.title, "range": f"{first}:{last}", "method": "xlsx", "text": text})
    finally:
        formulas.close()
        values.close()
    return result


def pdf_pages(content):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(content))
    if reader.is_encrypted:
        raise ValueError("加密 PDF 暂不支持")
    if len(reader.pages) > 80:
        raise ValueError("PDF 超过 80 页")
    result = []
    for index, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        method = "native"
        if not text.strip():
            text = ocr_page(content, index + 1)
            method = "ocr"
        result.append((index + 1, text, method))
        if sum(len(item[1]) for item in result) > 60000:
            raise ValueError("PDF 解析文本超过 60000 字符")
    return result


def ocr_page(content, page):
    poppler = os.environ.get("MY_AGENT_PDFTOPPM") or shutil.which("pdftoppm")
    tesseract = os.environ.get("MY_AGENT_TESSERACT") or shutil.which("tesseract")
    if not poppler or not tesseract:
        raise ValueError("扫描 PDF 需要本机 Tesseract 与 Poppler；安装后配置 MY_AGENT_TESSERACT 和 MY_AGENT_PDFTOPPM，可用 MY_AGENT_OCR_LANG 设置 chi_sim+eng")
    from PIL import Image
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = tesseract
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "input.pdf"
        prefix = Path(tmp) / "page"
        source.write_bytes(content)
        subprocess.run([poppler, "-f", str(page), "-l", str(page), "-singlefile", "-scale-to", "2000",
                        "-png", str(source), str(prefix)], check=True, timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        with Image.open(prefix.with_suffix(".png")) as image:
            text = pytesseract.image_to_string(image, lang=os.environ.get("MY_AGENT_OCR_LANG", "eng"), timeout=20)
    if not text.strip():
        raise ValueError("OCR 未识别到文字，请提供清晰扫描件")
    return text



def docx_chunks(content):
    """Body paragraphs/table cells in original order; no inferred page numbers."""
    from docx import Document
    from docx.text.paragraph import Paragraph
    from docx.table import Table
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        entries = archive.infolist()
        if (len(entries) > 2000 or sum(e.file_size for e in entries) > 30 * 1024 * 1024
                or any(e.file_size > 10 * 1024 * 1024 or e.flag_bits & 1 or
                       e.file_size / max(e.compress_size, 1) > 1000 for e in entries)):
            raise ValueError("DOCX展开规模超过安全上限")
        if any("vbaproject" in e.filename.lower() for e in entries):
            raise ValueError("不支持含宏的DOCX")
    document = Document(io.BytesIO(content))
    chunks = []
    total = paragraph = table = cells = 0
    def append(text, location):
        nonlocal total
        total += len(text)
        if total > 60000:
            raise ValueError("DOCX解析文本超过60000字符")
        for offset in range(0, len(text), 1800):
            body = text[offset:offset+1800]
            if body.strip():
                chunks.append({"index": len(chunks), "page": None, "start": location["block"],
                               "end": location["block"], "method": "docx", "text": body,
                               "offset_start": offset, "offset_end": offset+len(body), **location})
    for block, item in enumerate(document.iter_inner_content(), 1):
        if block > 10000:
            raise ValueError("DOCX内容块超过10000")
        if isinstance(item, Paragraph):
            paragraph += 1
            append(item.text, {"block": block, "paragraph": paragraph})
        elif isinstance(item, Table):
            table += 1
            if len(item.rows) > 10000 or len(item.columns) > 200:
                raise ValueError("DOCX表格行列超过上限")
            for row_num, row in enumerate(item.rows, 1):
                for col_num, cell in enumerate(row.cells, 1 + row.grid_cols_before):
                    if cell.tables:
                        raise ValueError("DOCX嵌套表格暂不支持，请展开为普通表格后上传")
                    cells += 1
                    if cells > 50000:
                        raise ValueError("DOCX表格单元格超过50000")
                    append(cell.text, {"block": block, "table": table, "row": row_num, "column": col_num})
    if not chunks:
        raise ValueError("DOCX没有可提取的段落或表格文字")
    return chunks

def worker(source, name, output):
    try:
        content = Path(source).read_bytes()
        if name.lower().endswith(".xlsx"):
            chunks = excel_chunks(content)
        elif name.lower().endswith(".docx"):
            chunks = docx_chunks(content)
        else:
            from src.server.documents import text_chunks
            chunks = text_chunks(pdf_pages(content))
        if not chunks or sum(len(c["text"]) for c in chunks) > 60000:
            raise ValueError("文件无内容或解析文本超过 60000 字符")
        Path(output).write_text(json.dumps({"chunks": chunks}, ensure_ascii=False), encoding="utf-8")
    except Exception as error:
        message = str(error)[:500]
        if name.lower().endswith(".docx") and not isinstance(error, ValueError):
            message = "DOCX文件损坏或格式无效"
        Path(output).write_text(json.dumps({"error": message}, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    import sys
    worker(*sys.argv[1:])
