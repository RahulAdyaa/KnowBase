"""Multimodal document extraction.

Each file becomes a list of RawSegments with modality metadata
(text/image/audio/video), which the ingestion pipeline chunks and embeds.
Text extraction is dependency-light (pypdf, python-pptx, python-docx, PIL).
Audio/video transcription uses faster-whisper when installed; image
understanding uses an optional local vision GGUF via the caption seam.
"""

from dataclasses import dataclass, field

from app.core.logging import get_logger

log = get_logger(__name__)

TEXT_EXTS = {".txt", ".md", ".markdown", ".csv", ".json", ".html", ".htm", ".xml", ".log"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"}
AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


@dataclass
class RawSegment:
    text: str
    modality: str = "text"  # text | image | audio | video
    page_number: int | None = None
    timestamp_ms: int | None = None
    label: str = ""


def _ext(filename: str) -> str:
    return "." + filename.lower().rsplit(".", 1)[-1] if "." in filename else ""


def extract_segments(filename: str, content_type: str, raw: bytes) -> list[RawSegment]:
    """Route a file to its extractor. Raises ValueError with a helpful message
    when an optional backend (transcription/vision) is not installed."""
    ext = _ext(filename)
    if ext == ".pdf":
        return _extract_pdf(raw)
    if ext in (".pptx", ".ppt"):
        return _extract_pptx(filename, raw)
    if ext == ".docx":
        return _extract_docx(raw)
    if ext in TEXT_EXTS or content_type.startswith("text/"):
        return _extract_text(raw)
    if ext in IMAGE_EXTS or content_type.startswith("image/"):
        return _extract_image(filename, raw)
    if ext in AUDIO_EXTS or content_type.startswith("audio/"):
        return _extract_audio(filename, raw)
    if ext in VIDEO_EXTS or content_type.startswith("video/"):
        return _extract_video(filename, raw)
    # Fallback: best-effort UTF-8 decode (previous behaviour).
    try:
        return [RawSegment(text=raw.decode("utf-8"))]
    except UnicodeDecodeError:
        return [RawSegment(text=raw.decode("utf-8", errors="replace"))]


def _extract_text(raw: bytes) -> list[RawSegment]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    return [RawSegment(text=text)]


def _extract_pdf(raw: bytes) -> list[RawSegment]:
    from pypdf import PdfReader
    import io

    reader = PdfReader(io.BytesIO(raw))
    segments: list[RawSegment] = []
    for i, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            segments.append(RawSegment(text=text, page_number=i))
    if not segments:
        raise ValueError("PDF has no extractable text (scanned PDFs need OCR - not bundled)")
    return segments


def _extract_pptx(filename: str, raw: bytes) -> list[RawSegment]:
    import io

    from pptx import Presentation

    if filename.lower().endswith(".ppt"):
        raise ValueError("Legacy .ppt is not supported - convert to .pptx first")
    prs = Presentation(io.BytesIO(raw))
    segments: list[RawSegment] = []
    for i, slide in enumerate(prs.slides, start=1):
        texts = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                t = shape.text_frame.text.strip()
                if t:
                    texts.append(t)
            if shape.has_table:
                for row in shape.table.rows:
                    texts.append(" | ".join(c.text.strip() for c in row.cells))
        if texts:
            segments.append(
                RawSegment(text="\n".join(texts), page_number=i, label=f"slide {i}")
            )
    if not segments:
        raise ValueError("PPTX has no extractable text")
    return segments


def _extract_docx(raw: bytes) -> list[RawSegment]:
    import io

    from docx import Document as DocxDocument

    doc = DocxDocument(io.BytesIO(raw))
    text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    if not text.strip():
        raise ValueError("DOCX has no extractable text")
    return [RawSegment(text=text)]


def caption_image(raw: bytes) -> str | None:
    """Optional vision caption via local GGUF (moondream2). Returns None when
    the vision model is not downloaded - images then fall back to metadata."""
    import os

    model_path = os.environ.get(
        "LOCAL_VISION_MODEL_PATH", "models/moondream2-q4_k_m.gguf"
    )
    if not os.path.exists(model_path):
        return None
    try:
        from llama_cpp import Llama
        from llama_cpp.llama_chat_format import MoondreamChatHandler

        import io
        from PIL import Image

        handler = MoondreamChatHandler.from_pretrained(
            repo_id="vikhyatk/moondream2",
            filename="moondream2-mmproj-f16.gguf",
        )
        llm = Llama(model_path, chat_handler=handler, n_ctx=2048, verbose=False)
        img = Image.open(io.BytesIO(raw))
        # Downscale huge images for the vision encoder.
        img.thumbnail((1024, 1024))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG")
        import base64

        b64 = base64.b64encode(buf.getvalue()).decode()
        resp = llm.create_chat_completion(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this image in detail."},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                        },
                    ],
                }
            ],
            max_tokens=256,
        )
        return resp["choices"][0]["message"]["content"]
    except Exception as exc:  # pragma: no cover - optional path
        log.warning("vision_caption_failed", extra={"err": str(exc)[:200]})
        return None


def _extract_image(filename: str, raw: bytes) -> list[RawSegment]:
    import io

    from PIL import Image

    img = Image.open(io.BytesIO(raw))
    w, h = img.size
    caption = caption_image(raw)
    if caption:
        text = f"[Image: {filename}, {w}x{h}]\n{caption}"
    else:
        text = (
            f"[Image: {filename}, {w}x{h} {img.mode}. "
            f"Visual understanding needs the optional vision model "
            f"(LOCAL_VISION_MODEL_PATH); searching matches filename/metadata.]"
        )
    return [RawSegment(text=text, modality="image", label=filename)]


def _ffmpeg_to_wav(raw: bytes, filename: str) -> str:
    """Convert any audio/video to 16kHz mono wav via ffmpeg. Returns tmp path."""
    import shutil
    import subprocess
    import tempfile

    if not shutil.which("ffmpeg"):
        raise ValueError("ffmpeg is required for audio/video but was not found")
    tmp_in = tempfile.NamedTemporaryFile(
        suffix="." + filename.rsplit(".", 1)[-1], delete=False
    )
    tmp_in.write(raw)
    tmp_in.close()
    tmp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    proc = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", tmp_in.name, "-ar", "16000", "-ac", "1", tmp_wav],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise ValueError(f"ffmpeg failed: {proc.stderr.decode()[:200]}")
    return tmp_wav


def transcribe_audio(wav_path: str) -> list[tuple[int, str]]:
    """Speech-to-text via faster-whisper. Returns [(start_ms, text)]."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise ValueError(
            "Audio transcription needs 'faster-whisper' (pip install faster-whisper). "
            "It downloads a small model (~75MB) on first use."
        )
    import os

    from app.core.envfix import hf_download_env

    with hf_download_env():
        model = WhisperModel("tiny", device="cpu", compute_type="int8")
        segments_out: list[tuple[int, str]] = []
        segments, _ = model.transcribe(wav_path, beam_size=5)
        for seg in segments:
            text = seg.text.strip()
            if text:
                segments_out.append((int(seg.start * 1000), text))
    os.unlink(wav_path)
    return segments_out


def _extract_audio(filename: str, raw: bytes) -> list[RawSegment]:
    wav = _ffmpeg_to_wav(raw, filename)
    transcribed = transcribe_audio(wav)
    if not transcribed:
        raise ValueError("No speech detected in audio")
    return [
        RawSegment(text=text, modality="audio", timestamp_ms=ms, label=filename)
        for ms, text in transcribed
    ]


def _extract_video(filename: str, raw: bytes) -> list[RawSegment]:
    wav = _ffmpeg_to_wav(raw, filename)
    transcribed = transcribe_audio(wav)
    segments = [
        RawSegment(text=text, modality="video", timestamp_ms=ms, label=filename)
        for ms, text in transcribed
    ]
    segments.append(
        RawSegment(
            text=f"[Video: {filename}. {len(transcribed)} transcribed speech segments.]",
            modality="video",
            label=filename,
        )
    )
    return segments


def supported_types() -> list[str]:
    return sorted(TEXT_EXTS | IMAGE_EXTS | AUDIO_EXTS | VIDEO_EXTS | {".pdf", ".pptx", ".docx"})
