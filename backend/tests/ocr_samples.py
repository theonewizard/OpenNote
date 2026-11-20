"""Small images and PDFs with known text for the OCR tests, made with PDFium (no image
library): a PDF with a text layer, a PNG of it, and a scanned PDF (the PNG's pixels as an
image, no text layer)."""

import ctypes
import io
import struct
import zlib

import pypdfium2 as pdfium  # type: ignore[import-untyped]
import pypdfium2.raw as raw  # type: ignore[import-untyped]

TEXT = "OpenNote receipt 4711"


def _save(pdf: pdfium.PdfDocument) -> bytes:
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue()


def text_pdf(text: str = TEXT) -> bytes:
    pdf = pdfium.PdfDocument.new()
    page = pdf.new_page(612, 300)
    obj = raw.FPDFPageObj_NewTextObj(pdf.raw, b"Helvetica", 36.0)
    utf16 = (text + "\0").encode("utf-16-le")
    raw.FPDFText_SetText(obj, (ctypes.c_ushort * (len(utf16) // 2)).from_buffer_copy(utf16))
    raw.FPDFPageObj_Transform(obj, 1, 0, 0, 1, 40, 140)
    raw.FPDFPage_InsertObject(page.raw, obj)
    raw.FPDFPage_GenerateContent(page.raw)
    return _save(pdf)


def _bitmap(text: str) -> pdfium.PdfBitmap:
    return pdfium.PdfDocument(text_pdf(text))[0].render(scale=300 / 72, grayscale=True)


def png(text: str = TEXT) -> bytes:
    """An 8-bit greyscale PNG of the text at 300 dpi."""
    bitmap = _bitmap(text)
    w, h, stride, data = bitmap.width, bitmap.height, bitmap.stride, bytes(bitmap.buffer)
    rows = b"".join(b"\0" + data[y * stride : y * stride + w] for y in range(h))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    header = struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def scanned_pdf(text: str = TEXT) -> bytes:
    """A PDF page that is only an image of the text, like a scanner's output."""
    bitmap = _bitmap(text)
    pdf = pdfium.PdfDocument.new()
    page = pdf.new_page(612, 300)
    image = raw.FPDFPageObj_NewImageObj(pdf.raw)
    raw.FPDFImageObj_SetBitmap(None, 0, image, bitmap.raw)
    raw.FPDFPageObj_Transform(image, 612, 0, 0, 300, 0, 0)
    raw.FPDFPage_InsertObject(page.raw, image)
    raw.FPDFPage_GenerateContent(page.raw)
    return _save(pdf)
