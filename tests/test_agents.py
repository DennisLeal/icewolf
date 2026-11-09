import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from icewolf.agents import AgentStore, Passage
from icewolf.ollama import OllamaClient


class AgentStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = AgentStore(self.root / "private" / "agents.sqlite3")

    def test_create_add_search_and_remove_stay_local(self):
        guide = self.root / "guide.txt"
        guide.write_text("Forecast interval configuration for NICE IEX.", encoding="utf-8")
        self.store.create_agent("NICE IEX Administrator", "Help with workforce management", [guide])
        word = self.root / "operations.docx"
        document = Document()
        document.add_paragraph("Repair the scheduling service before generating schedules.")
        document.save(word)
        self.store.add_documents("NICE IEX Administrator", [word])
        self.assertEqual(self.store.list_agents()[0].name, "NICE IEX Administrator")
        self.assertEqual(self.store.list_documents("NICE IEX Administrator"),
                         ["guide.txt", "operations.docx"])
        self.assertIn("scheduling service", self.store.search(
            "NICE IEX Administrator", "repair scheduling service")[0].text)
        self.assertEqual(self.store.search("NICE IEX Administrator", "unrelated ocean"), [])
        self.store.remove_document("NICE IEX Administrator", "operations.docx")
        self.assertEqual(self.store.search("NICE IEX Administrator", "scheduling service"), [])
        self.assertTrue(word.exists())

    def test_extracts_pdf_with_page_sources(self):
        pdf = self.root / "manual.pdf"
        writer = PdfWriter()
        page = writer.add_blank_page(width=400, height=400)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})
        })
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 20 300 Td (IEX workforce forecasting guide) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
        with pdf.open("wb") as file:
            writer.write(file)
        self.store.create_agent("NICE IEX Administrator", "NICE IEX guidance", [pdf])
        result = self.store.search("NICE IEX Administrator", "workforce forecasting")
        self.assertEqual(result[0].source, "manual.pdf, page 1")
        self.assertIn("workforce forecasting", result[0].text)

    def test_invalid_input_and_duplicate_import_do_not_partially_save(self):
        first = self.root / "first.txt"
        first.write_text("Useful reference text", encoding="utf-8")
        empty = self.root / "empty.txt"
        empty.write_text("", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "no readable text"):
            self.store.create_agent("NICE IEX Administrator", "Help", [first, empty])
        self.assertEqual(self.store.list_agents(), [])
        self.store.create_agent("NICE IEX Administrator", "Help", [first])
        second = self.root / "second.txt"
        second.write_text("Additional reference", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "already attached"):
            self.store.add_documents("NICE IEX Administrator", [second, first])
        self.assertEqual(self.store.list_documents("NICE IEX Administrator"), ["first.txt"])
        with self.assertRaisesRegex(ValueError, "reserved"):
            self.store.create_agent("Research", "Help", [])

    def test_isolates_documents_between_agents(self):
        path = self.root / "private.txt"
        path.write_text("Payroll scheduling guidance", encoding="utf-8")
        self.store.create_agent("First", "Help", [path])
        self.store.create_agent("Second", "Help", [])
        self.assertEqual(self.store.search("Second", "payroll scheduling"), [])

    def test_scanned_pdf_without_text_is_rejected(self):
        pdf = self.root / "scanned.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=400, height=400)
        with pdf.open("wb") as file:
            writer.write(file)
        with self.assertRaisesRegex(ValueError, "OCR"):
            self.store.create_agent("NICE IEX Administrator", "Help", [pdf])
        self.assertEqual(self.store.list_agents(), [])

    def test_unsupported_format_and_invalid_utf8_are_rejected(self):
        unsupported = self.root / "guide.exe"
        unsupported.write_text("test", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "PDF, DOCX"):
            self.store.create_agent("NICE IEX Administrator", "Help", [unsupported])
        invalid = self.root / "guide.txt"
        invalid.write_bytes(b"\xff")
        with self.assertRaises(UnicodeError):
            self.store.create_agent("NICE IEX Administrator", "Help", [invalid])
        self.assertEqual(self.store.list_agents(), [])

    def test_document_agent_passes_bounded_sources_to_local_model(self):
        client = OllamaClient("local")
        with patch.object(client, "_post", return_value={"message": {"content": "Use the guide [1]."}}) as post:
            result = client.document_agent_reply(
                "NICE IEX Administrator", "Troubleshoot", "How do I schedule?",
                [Passage("guide.txt", "Scheduling reference")],
            )
        self.assertEqual(result, "Use the guide [1].")
        payload = post.call_args.args[1]
        self.assertIn("untrusted reference data", payload["messages"][0]["content"])
        self.assertIn("[1] guide.txt", payload["messages"][1]["content"])
        self.assertFalse(payload["stream"])
        self.assertEqual(client.messages, [{"role": "system", "content": client.messages[0]["content"]}])


if __name__ == "__main__":
    unittest.main()
