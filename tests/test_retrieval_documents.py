import io
import json
import zipfile
from copy import deepcopy
import unittest
import subprocess
from unittest.mock import patch, MagicMock
from docx import Document as WordDocument
from openpyxl import Workbook
from langchain_core.documents import Document
from src.retrieval.loaders import load_document, SourceLoader
from src.retrieval.splitter import split_documents
from src.server.documents import parse_document, source_label, MAX_BYTES
from tests.abstract_evaluation import pdf


def docx_bytes():
    doc = WordDocument()
    doc.add_paragraph("原文第一段：虚构研究。")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "表格甲"
    table.cell(0, 1).text = "表格乙"
    doc.add_paragraph("原文第二段：结论。")
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


class RetrievalDocumentTests(unittest.TestCase):
    def test_text_markdown_and_pdf(self):
        for name in ("fiction.txt", "fiction.md"):
            docs = load_document(name, "第一行\n第二行".encode())
            self.assertIsInstance(docs[0], Document)
            self.assertEqual(docs[0].page_content, "第一行\n第二行")
            self.assertEqual((docs[0].metadata["start"], docs[0].metadata["end"]), (1, 2))
            self.assertEqual(docs[0].metadata["name"], name)
        docs = load_document("fiction.pdf", pdf(["Abstract", "Fictional evidence."]))
        self.assertEqual(docs[0].metadata["page"], 1)
        self.assertIn("Fictional evidence.", docs[0].page_content)

    def test_docx_order_and_citations(self):
        docs = load_document("fiction.docx", docx_bytes())
        self.assertEqual([d.page_content for d in docs], ["原文第一段：虚构研究。", "表格甲", "表格乙", "原文第二段：结论。"])
        self.assertEqual([d.metadata["block"] for d in docs], [1, 2, 2, 3])
        self.assertEqual(docs[-1].metadata["paragraph"], 2)
        self.assertEqual(docs[2].metadata["column"], 2)
        self.assertTrue(all(d.metadata["page"] is None for d in docs))
        self.assertIn("表格1 行1 列2", source_label(docs[2].metadata))
        self.assertIn("段落2", source_label(docs[-1].metadata))

    def test_excel_unchanged(self):
        book = Workbook()
        book.active.append(["任务", 5])
        buffer = io.BytesIO()
        book.save(buffer)
        docs = load_document("fiction.xlsx", buffer.getvalue())
        self.assertEqual(docs[0].metadata["range"], "A1:B1")
        self.assertIn("B1=5", docs[0].page_content)

    def test_split_spans_and_stability_without_mutation(self):
        for name, body in (("fiction.txt", ("  重复原文。\n" * 50).encode()), ("fiction.docx", docx_bytes())):
            parents = load_document(name, body)
            before = deepcopy(parents)
            children = split_documents(parents, chunk_size=15, chunk_overlap=4)
            self.assertEqual(parents, before)
            again = split_documents(parents, chunk_size=15, chunk_overlap=4)
            self.assertEqual([c.id for c in children], [c.id for c in again])
            self.assertEqual(len(set(c.id for c in children)), len(children))
            by_id = {p.id: p for p in parents}
            for child in children:
                meta = child.metadata
                parent = by_id[meta["parent_id"]]
                self.assertEqual(child.page_content, parent.page_content[meta["parent_char_start"]:meta["parent_char_end"]])
                self.assertLessEqual(len(child.page_content), 15)
            self.assertNotEqual(children[0].id, split_documents(parents, chunk_size=16, chunk_overlap=4)[0].id)
            changed = SourceLoader(name, parse_document(name, body), "another-file-id").load()
            self.assertNotEqual(changed[0].id, parents[0].id)
        for size, overlap in ((0, 0), (5, 5), (5, -1), (True, 0)):
            with self.assertRaises(ValueError): split_documents([], size, overlap)

    def test_long_docx_parent_offsets(self):
        word = WordDocument()
        text = "长段落" * 700
        word.add_paragraph(text)
        buffer = io.BytesIO()
        word.save(buffer)
        parents = load_document("long.docx", buffer.getvalue())
        self.assertGreater(len(parents), 1)
        for child in split_documents(parents, 100, 20):
            meta = child.metadata
            self.assertEqual(child.page_content, text[meta["source_char_start"]:meta["source_char_end"]])

    def test_corrupt_empty_traversal_and_limits(self):
        for name, content in (("bad.docx", b"broken"), ("../bad.docx", docx_bytes()), ("bad.txt", b"\x00"), ("bad.docx", b""), ("huge.txt", b"x"*(MAX_BYTES+1))):
            with self.assertRaises(ValueError): parse_document(name, content)
        empty = WordDocument()
        buffer = io.BytesIO()
        empty.save(buffer)
        with self.assertRaises(ValueError): parse_document("empty.docx", buffer.getvalue())
        for entry, body in (("word/vbaProject.bin", b"macro"), ("word/document.xml", b"x"*1000000)):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(entry, body)
            with self.assertRaises(ValueError): parse_document("unsafe.docx", buffer.getvalue())
        big = WordDocument()
        big.add_paragraph("字"*60001)
        buffer = io.BytesIO()
        big.save(buffer)
        with self.assertRaises(ValueError): parse_document("large.docx", buffer.getvalue())
        nested = WordDocument()
        nested.add_table(rows=1, cols=1).cell(0, 0).add_table(rows=1, cols=1)
        buffer = io.BytesIO()
        nested.save(buffer)
        with self.assertRaisesRegex(ValueError, "嵌套表格"):
            parse_document("nested.docx", buffer.getvalue())
        process = MagicMock()
        process.wait.side_effect = [subprocess.TimeoutExpired("parser", 60), 0]
        process.poll.return_value = None
        with patch("subprocess.Popen", return_value=process), patch("subprocess.run"):
            with self.assertRaisesRegex(ValueError, "60 秒"):
                parse_document("timeout.docx", docx_bytes())
        process.kill.assert_called_once()


if __name__ == "__main__":
    unittest.main()
