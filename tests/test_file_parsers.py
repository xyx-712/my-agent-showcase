import io
import os
import zipfile
from unittest import TestCase, main
from unittest.mock import patch
from openpyxl import Workbook
from pypdf import PdfWriter
from src.server.documents import parse_document, source_label
from src.server.file_parsers import pdf_pages


class ParserTests(TestCase):
    def test_excel_coordinates_and_formula(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "计划"
        sheet.append(["任务", "剩余"])
        sheet.append(["开发", 5])
        sheet["C2"] = "=B2+1"
        buffer = io.BytesIO()
        workbook.save(buffer)
        chunks = parse_document("plan.xlsx", buffer.getvalue())
        self.assertEqual(chunks[1]["range"], "A2:C2")
        self.assertIn("公式缓存：缺失", chunks[1]["text"])
        self.assertIn("未执行重算", chunks[1]["text"])
        self.assertIn("计划", source_label({**chunks[1], "name": "plan.xlsx"}))
        with self.assertRaises(ValueError):
            parse_document("bad.xlsx", b"not a zip")

    def test_zip_limits_and_macros(self):
        for filename, body in (("xl/vbaProject.bin", b"macro"), ("huge.xml", b"0" * 1000000)):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(filename, body)
            with self.assertRaises(ValueError):
                parse_document("unsafe.xlsx", buffer.getvalue())

    def test_scan_fallback_and_missing_dependency(self):
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        buffer = io.BytesIO()
        writer.write(buffer)
        with patch("src.server.file_parsers.ocr_page", return_value="OCR 识别 123"):
            pages = pdf_pages(buffer.getvalue())
        self.assertEqual(pages[0][2], "ocr")
        with patch.dict(os.environ, {"MY_AGENT_TESSERACT": "", "MY_AGENT_PDFTOPPM": ""}), patch("shutil.which", return_value=None):
            with self.assertRaisesRegex(ValueError, "Tesseract"):
                pdf_pages(buffer.getvalue())


if __name__ == "__main__":
    main()
