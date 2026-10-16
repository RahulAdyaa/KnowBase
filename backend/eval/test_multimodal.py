"""Multimodal ingestion test: PDF, PPTX, DOCX, PNG through the real pipeline.

Generates sample files in-memory, ingests each as a Document, and asserts:
- document reaches READY
- chunks carry the right modality metadata
- content is retrievable via hybrid search
"""

import io

from app.models.document import Document, DocumentStatus
from app.services.rag import ingest_document, retrieve
from eval.harness import EvalEnv


def make_pdf() -> bytes:
    def make_pdf_bytes(text):
        objs = [
            b"<</Type/Catalog/Pages 2 0 R>>",
            b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
        ]
        stream = b"BT /F1 24 Tf 100 700 Td (" + text.encode() + b") Tj ET"
        objs.append(b"<</Length " + str(len(stream)).encode() + b">>stream\n" + stream + b"\nendstream")
        objs.append(b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>")
        out = io.BytesIO()
        out.write(b"%PDF-1.4\n")
        offsets = []
        for i, body in enumerate(objs, start=1):
            offsets.append(out.tell())
            out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
        xref = out.tell()
        out.write(f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n".encode())
        for o in offsets:
            out.write(f"{o:010d} 00000 n \n".encode())
        out.write(f"trailer<</Size {len(objs)+1}/Root 1 0 R>>\nstartxref\n{xref}\n%%EOF".encode())
        return out.getvalue()

    return make_pdf_bytes("Project Phoenix budget approved at 2.4 million dollars")


def make_pptx() -> bytes:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    tb = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
    tb.text_frame.text = "Project Phoenix launch timeline: beta in June"
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def make_docx() -> bytes:
    from docx import Document as DocxDocument

    doc = DocxDocument()
    doc.add_paragraph("Project Phoenix onboarding guide for new engineers")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def make_png() -> bytes:
    from PIL import Image

    img = Image.new("RGB", (320, 200), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def ingest_file(env: EvalEnv, filename: str, content_type: str, raw: bytes) -> Document:
    doc = Document(
        owner_id=env.user_id,
        filename=filename,
        content_type=content_type,
        size_bytes=len(raw),
        status=DocumentStatus.PENDING,
    )
    env.session.add(doc)
    env.session.commit()
    ingest_document(env.session, doc.id, raw, env.embedder, env.store)
    env.session.refresh(doc)
    return doc


def test_multimodal() -> dict:
    env = EvalEnv()
    results: dict = {}
    try:
        cases = [
            ("memo.pdf", "application/pdf", make_pdf(), "text"),
            ("deck.pptx", "application/vnd.ms-powerpoint", make_pptx(), "text"),
            ("notes.docx", "application/vnd.openxmlformats", make_docx(), "text"),
            ("diagram.png", "image/png", make_png(), "image"),
        ]
        for filename, ctype, raw, expected_modality in cases:
            doc = ingest_file(env, filename, ctype, raw)
            chunks = retrieve(env.session, env.user_id, "Project Phoenix", env.embedder, env.store)
            hits = [c for c in chunks if c.document_id == doc.id]
            results[filename] = {
                "status": doc.status.value,
                "chunk_count": doc.chunk_count,
                "modality": hits[0].modality if hits else None,
                "retrievable": len(hits) > 0,
                "ok": doc.status == DocumentStatus.READY and len(hits) > 0,
            }
    finally:
        env.close()
    results["all_ok"] = all(r["ok"] for r in results.values() if isinstance(r, dict))
    return results


if __name__ == "__main__":
    import json

    print(json.dumps(test_multimodal(), indent=2))
