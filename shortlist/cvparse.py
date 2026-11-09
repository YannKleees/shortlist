import io
from pathlib import Path


def extract_text(filename, data):
    ext = Path(filename).suffix.lower()
    if ext in (".txt", ".md"):
        return data.decode("utf-8", errors="replace").strip()
    if ext == ".pdf":
        from pypdf import PdfReader
        return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages).strip()
    if ext == ".docx":
        import docx
        return "\n".join(p.text for p in docx.Document(io.BytesIO(data)).paragraphs if p.text).strip()
    raise ValueError("Upload your CV as PDF, DOCX, TXT or MD.")
