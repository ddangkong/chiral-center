"""Document processing: read PDF/TXT/MD files, extract text, split into chunks."""
import uuid
from pathlib import Path
from pypdf import PdfReader

from models.document import DocumentMeta, DocumentStatus, TextChunk
from utils.chunker import TextChunker


class DocumentProcessor:
    """Handles document upload, text extraction, and chunking."""

    def __init__(self, chunk_size: int = 2000, overlap: int = 200):
        self.chunker = TextChunker(chunk_size=chunk_size, overlap=overlap)
        self._documents: dict[str, DocumentMeta] = {}

    async def process_file(self, filename: str, content: bytes) -> DocumentMeta:
        """Process an uploaded file: extract text and chunk it."""
        doc_id = str(uuid.uuid4())
        ext = Path(filename).suffix.lower().lstrip(".")

        doc = DocumentMeta(
            id=doc_id,
            filename=filename,
            ext=ext,
            size=len(content),
            status=DocumentStatus.PROCESSING,
        )

        try:
            # Extract text based on file type
            if ext == "pdf":
                text, pages = self._extract_pdf(content)
                doc.pages = pages
            elif ext in ("txt", "md"):
                text = content.decode("utf-8", errors="replace")
                doc.pages = text.count("\n\n") + 1  # rough page estimate
            elif ext == "docx":
                text = self._extract_docx(content)
                doc.pages = text.count("\n\n") + 1
            else:
                raise ValueError(f"Unsupported file type: {ext}")

            doc.extracted_text = text

            # Split into chunks
            doc.chunks = self.chunker.split(text)
            doc.status = DocumentStatus.DONE

        except Exception as e:
            doc.status = DocumentStatus.ERROR
            doc.extracted_text = f"Error: {str(e)}"

        self._documents[doc_id] = doc
        return doc

    def _extract_pdf(self, content: bytes) -> tuple[str, int]:
        """Extract text from PDF bytes."""
        import io
        reader = PdfReader(io.BytesIO(content))
        pages = len(reader.pages)
        text_parts = []
        for page in reader.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
        return "\n\n".join(text_parts), pages

    def _extract_docx(self, content: bytes) -> str:
        """Extract text from DOCX bytes (simple implementation)."""
        import io
        import zipfile
        import xml.etree.ElementTree as ET

        with zipfile.ZipFile(io.BytesIO(content)) as z:
            if "word/document.xml" not in z.namelist():
                raise ValueError("Invalid DOCX file")
            xml_content = z.read("word/document.xml")

        tree = ET.fromstring(xml_content)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

        paragraphs = []
        for para in tree.iter(f"{{{ns['w']}}}p"):
            texts = []
            for run in para.iter(f"{{{ns['w']}}}t"):
                if run.text:
                    texts.append(run.text)
            if texts:
                paragraphs.append("".join(texts))

        return "\n\n".join(paragraphs)

    def get_document(self, doc_id: str) -> DocumentMeta | None:
        """Get document by ID."""
        return self._documents.get(doc_id)

    def get_all_documents(self) -> list[DocumentMeta]:
        """Get all processed documents."""
        return list(self._documents.values())

    def get_combined_text(self, doc_ids: list[str] | None = None) -> str:
        """Get combined text from multiple documents."""
        if doc_ids is None:
            docs = self._documents.values()
        else:
            docs = [self._documents[did] for did in doc_ids if did in self._documents]
        return "\n\n---\n\n".join(d.extracted_text for d in docs if d.status == DocumentStatus.DONE)

    def get_all_chunks(self, doc_ids: list[str] | None = None) -> list[TextChunk]:
        """Get all chunks from specified documents."""
        if doc_ids is None:
            docs = self._documents.values()
        else:
            docs = [self._documents[did] for did in doc_ids if did in self._documents]
        chunks = []
        for d in docs:
            if d.status == DocumentStatus.DONE:
                chunks.extend(d.chunks)
        return chunks


    def add_virtual_document(self, text: str, filename: str = "research_data.txt", source: str = "chiral-research") -> DocumentMeta:
        """리서치 결과 등 외부 텍스트를 가상 문서로 추가. 업로드 없이 온톨로지 추출 파이프라인에 투입 가능."""
        doc_id = str(uuid.uuid4())
        doc = DocumentMeta(
            id=doc_id,
            filename=filename,
            ext="txt",
            size=len(text.encode("utf-8")),
            status=DocumentStatus.DONE,
        )
        doc.extracted_text = text
        doc.chunks = self.chunker.split(text)
        doc.pages = 1
        self._documents[doc_id] = doc
        return doc


# Singleton
doc_processor = DocumentProcessor()
