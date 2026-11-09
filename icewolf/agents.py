"""Local agent profiles and searchable, document-backed reference material."""

from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path
import re
import sqlite3
import zipfile


BUILTIN_ROLES = ("Research", "Coding", "Marketing")
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_EXTRACTED_CHARS = 1_000_000
MAX_DOCUMENTS = 100
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200
STOP_WORDS = frozenset(
    "a an and are as at be by can do for from how i in is it me my of on or please "
    "the to what when where which why with you your".split()
)


@dataclass(frozen=True)
class Agent:
    name: str
    instructions: str


@dataclass(frozen=True)
class Passage:
    source: str
    text: str


def _extract_document(path: Path) -> list[Passage]:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"{path.name}: file exceeds the 10 MB limit.")
    suffix = path.suffix.lower()
    if suffix in (".txt", ".md"):
        sections = [(path.name, path.read_text(encoding="utf-8-sig"))]
    elif suffix == ".pdf":
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
        try:
            reader = PdfReader(str(path))
            if reader.is_encrypted:
                raise ValueError(f"{path.name}: encrypted PDFs are not supported.")
            if len(reader.pages) > 500:
                raise ValueError(f"{path.name}: PDF exceeds the 500-page limit.")
            sections = []
            total = 0
            for index, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ""
                total += len(text)
                if total > MAX_EXTRACTED_CHARS:
                    raise ValueError(f"{path.name}: extracted text exceeds the limit.")
                sections.append((f"{path.name}, page {index}", text))
        except PdfReadError as exc:
            raise ValueError(f"{path.name}: could not read PDF: {exc}") from exc
    elif suffix == ".docx":
        from docx import Document
        from docx.opc.exceptions import PackageNotFoundError
        from lxml.etree import XMLSyntaxError
        try:
            with zipfile.ZipFile(path) as archive:
                if sum(item.file_size for item in archive.infolist()) > 50 * 1024 * 1024:
                    raise ValueError(f"{path.name}: expanded Word document exceeds the limit.")
            document = Document(str(path))
            paragraphs = [paragraph.text for paragraph in document.paragraphs]
            for table in document.tables:
                paragraphs.extend(" | ".join(cell.text for cell in row.cells) for row in table.rows)
            sections = [(path.name, "\n".join(paragraphs))]
        except (zipfile.BadZipFile, PackageNotFoundError, XMLSyntaxError, KeyError) as exc:
            raise ValueError(f"{path.name}: could not read Word document: {exc}") from exc
    else:
        raise ValueError(f"{path.name}: use PDF, DOCX, TXT, or Markdown files.")
    if sum(len(text) for _, text in sections) > MAX_EXTRACTED_CHARS:
        raise ValueError(f"{path.name}: extracted text exceeds the limit.")
    chunks = []
    for source, text in sections:
        text = text.strip()
        for start in range(0, len(text), CHUNK_SIZE - CHUNK_OVERLAP):
            part = text[start:start + CHUNK_SIZE].strip()
            if part:
                chunks.append(Passage(source, part))
    if not chunks:
        raise ValueError(f"{path.name}: no readable text found. Scanned PDFs require OCR first.")
    return chunks


class AgentStore:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path)
        db.execute("PRAGMA foreign_keys = ON")
        try:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS agents (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    instructions TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY, agent_id INTEGER NOT NULL REFERENCES agents(id),
                    name TEXT NOT NULL COLLATE NOCASE, UNIQUE(agent_id, name)
                );
                CREATE TABLE IF NOT EXISTS passages (
                    document_id INTEGER NOT NULL REFERENCES documents(id),
                    source TEXT NOT NULL, text TEXT NOT NULL
                );
            """)
            with db:
                yield db
        finally:
            db.close()

    def list_agents(self) -> list[Agent]:
        if not self.path.exists():
            return []
        with self._connect() as db:
            rows = db.execute("SELECT name, instructions FROM agents ORDER BY name").fetchall()
        return [Agent(*row) for row in rows]

    def create_agent(self, name: str, instructions: str, paths: list[Path]) -> None:
        name, instructions = name.strip(), instructions.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 -]{0,49}", name):
            raise ValueError("Agent name must be 1–50 letters, numbers, spaces or hyphens.")
        if name.casefold() in {role.casefold() for role in BUILTIN_ROLES}:
            raise ValueError("That name is reserved for an existing agent.")
        if not instructions or len(instructions) > 2000:
            raise ValueError("Enter a role description of 1–2000 characters.")
        documents = self._prepare(paths)
        try:
            with self._connect() as db:
                cursor = db.execute("INSERT INTO agents(name, instructions) VALUES (?, ?)",
                                    (name, instructions))
                self._insert_documents(db, cursor.lastrowid, documents)
        except sqlite3.IntegrityError as exc:
            raise ValueError("An agent or document with that name already exists.") from exc

    def add_documents(self, name: str, paths: list[Path]) -> None:
        documents = self._prepare(paths)
        if not documents:
            raise ValueError("Select at least one document.")
        try:
            with self._connect() as db:
                row = db.execute("SELECT id FROM agents WHERE name = ?", (name,)).fetchone()
                if row is None:
                    raise ValueError("Agent not found.")
                count = db.execute("SELECT count(*) FROM documents WHERE agent_id = ?",
                                   (row[0],)).fetchone()[0]
                if count + len(documents) > MAX_DOCUMENTS:
                    raise ValueError(f"An agent can have at most {MAX_DOCUMENTS} documents.")
                self._insert_documents(db, row[0], documents)
        except sqlite3.IntegrityError as exc:
            raise ValueError("A document with that name is already attached to this agent.") from exc

    def list_documents(self, name: str) -> list[str]:
        if not self.path.exists():
            return []
        with self._connect() as db:
            rows = db.execute(
                "SELECT d.name FROM documents d JOIN agents a ON a.id = d.agent_id "
                "WHERE a.name = ? ORDER BY d.name", (name,)
            ).fetchall()
        return [row[0] for row in rows]

    def remove_document(self, name: str, document: str) -> None:
        if not self.path.exists():
            raise ValueError("Agent database not found.")
        with self._connect() as db:
            row = db.execute(
                "SELECT d.id FROM documents d JOIN agents a ON a.id = d.agent_id "
                "WHERE a.name = ? AND d.name = ?", (name, document)
            ).fetchone()
            if row is None:
                raise ValueError("Document not found.")
            db.execute("DELETE FROM passages WHERE document_id = ?", (row[0],))
            db.execute("DELETE FROM documents WHERE id = ?", (row[0],))

    def _prepare(self, paths: list[Path]):
        if len(paths) > MAX_DOCUMENTS:
            raise ValueError(f"An agent can have at most {MAX_DOCUMENTS} documents.")
        return [(path.name, _extract_document(path)) for path in paths]

    @staticmethod
    def _insert_documents(db, agent_id, documents):
        for name, passages in documents:
            document_id = db.execute("INSERT INTO documents(agent_id, name) VALUES (?, ?)",
                                     (agent_id, name)).lastrowid
            db.executemany("INSERT INTO passages(document_id, source, text) VALUES (?, ?, ?)",
                           [(document_id, part.source, part.text) for part in passages])

    def search(self, name: str, query: str, limit: int = 4) -> list[Passage]:
        terms = {word for word in re.findall(r"[a-z0-9]+", query.lower())
                 if len(word) > 1 and word not in STOP_WORDS}
        if not terms:
            return []
        if not self.path.exists():
            raise ValueError("Agent database not found.")
        with self._connect() as db:
            rows = db.execute(
                "SELECT p.source, p.text FROM passages p "
                "JOIN documents d ON d.id = p.document_id "
                "JOIN agents a ON a.id = d.agent_id WHERE a.name = ?", (name,)
            ).fetchall()
        ranked = []
        for source, text in rows:
            words = set(re.findall(r"[a-z0-9]+", text.lower()))
            score = len(terms & words)
            if score:
                ranked.append((score, Passage(source, text)))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [passage for _, passage in ranked[:limit]]
