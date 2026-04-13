from models.document import TextChunk

class TextChunker:
    def __init__(self, chunk_size: int = 2000, overlap: int = 200):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def split(self, text: str) -> list[TextChunk]:
        """Split text into overlapping chunks."""
        chunks = []
        start = 0
        idx = 0
        while start < len(text):
            end = start + self.chunk_size
            # Try to break at sentence boundary
            if end < len(text):
                # Look for last period, question mark, or newline
                for sep in ['\n\n', '.\n', '. ', '? ', '! ']:
                    last_sep = text[start:end].rfind(sep)
                    if last_sep > self.chunk_size * 0.5:
                        end = start + last_sep + len(sep)
                        break

            chunk_text = text[start:end].strip()
            if chunk_text:
                chunks.append(TextChunk(
                    text=chunk_text,
                    index=idx,
                    metadata={"start": start, "end": end}
                ))
                idx += 1
            start = end - self.overlap if end < len(text) else len(text)
        return chunks
