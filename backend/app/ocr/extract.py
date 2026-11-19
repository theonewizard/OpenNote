"""Text of one image or PDF (P6-06). Runs inside `python -m app.ocr`, a child process with
memory and time limits (app.ocr.vault.run_isolated), never in the API or worker process.

A PDF page with a text layer gives that text; a page without one (a scan) is rendered to
a greyscale bitmap and read by Tesseract, like an image attachment. Tesseract reads
PNG, JPEG, TIFF, WebP and BMP itself (Leptonica; the API image builds it without GIF,
for which the UBI 10 repositories have no library), so images go to it unchanged.
"""

import math
import os
import re
import shutil
import subprocess  # nosec B404  # fixed argv, no shell
from collections.abc import Iterator

import filetype  # type: ignore[import-untyped]
import pypdfium2 as pdfium  # type: ignore[import-untyped]

IMAGE_MIMES = frozenset(
    {"image/png", "image/jpeg", "image/tiff", "image/webp", "image/bmp"}
)
PDF_MIME = "application/pdf"
MAX_PDF_PAGES = 50  # pages after this one are left out
DPI = 300
MAX_PIXELS = 25_000_000  # a larger page is rendered at a lower resolution
TESSERACT_TIMEOUT = 120  # seconds per image or page
_WORD = re.compile(r"\w")


class OcrError(Exception):
    """The file could not be read."""


def _env() -> dict[str, str]:
    """A minimal environment for Tesseract: PATH, one thread, and where its language data
    is when the build has no default for it (the API image sets TESSDATA_PREFIX)."""
    env = {"PATH": os.environ.get("PATH", ""), "OMP_THREAD_LIMIT": "1"}
    if "TESSDATA_PREFIX" in os.environ:
        env["TESSDATA_PREFIX"] = os.environ["TESSDATA_PREFIX"]
    return env


def tesseract(image: bytes, languages: str) -> str:
    """Tesseract's text for one image (any format leptonica reads, PGM included)."""
    binary = shutil.which("tesseract")
    if binary is None:
        raise OcrError("tesseract is not installed")
    try:
        result = subprocess.run(  # noqa: S603  # nosec B603  # fixed argv, languages validated
            [binary, "stdin", "stdout", "-l", languages],
            input=image,
            capture_output=True,
            timeout=TESSERACT_TIMEOUT,
            check=False,
            env=_env(),
        )
    except subprocess.TimeoutExpired as exc:
        raise OcrError("tesseract timed out") from exc
    if result.returncode != 0:
        raise OcrError(f"tesseract exited with {result.returncode}")
    return result.stdout.decode("utf-8", "replace")


def _pgm(page: pdfium.PdfPage) -> bytes:
    """The page as a binary greyscale PGM at DPI, or less if it would exceed MAX_PIXELS."""
    width, height = page.get_size()  # points, 1/72 inch
    scale = min(DPI / 72, math.sqrt(MAX_PIXELS / max(width * height, 1)))
    bitmap = page.render(scale=scale, grayscale=True)
    w, h, stride = bitmap.width, bitmap.height, bitmap.stride
    data = bytes(bitmap.buffer)
    rows = data if stride == w else b"".join(data[y * stride : y * stride + w] for y in range(h))
    return f"P5\n{w} {h}\n255\n".encode() + rows


def _pdf_pages(data: bytes, languages: str) -> Iterator[str]:
    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        raise OcrError("not a readable PDF") from exc
    try:
        for index in range(min(len(pdf), MAX_PDF_PAGES)):
            page = pdf[index]
            text = page.get_textpage().get_text_bounded()
            yield text if _WORD.search(text) else tesseract(_pgm(page), languages)
    finally:
        pdf.close()


def extract_text(data: bytes, languages: str) -> str:
    """The text of an image or PDF; OcrError for any other file or one that cannot be read."""
    kind = filetype.guess_mime(data)
    if kind == PDF_MIME:
        pages = list(_pdf_pages(data, languages))
    elif kind in IMAGE_MIMES:
        pages = [tesseract(data, languages)]
    else:
        raise OcrError(f"not an image or PDF ({kind or 'unknown type'})")
    return "\n\n".join(p.strip() for p in pages if p.strip())
