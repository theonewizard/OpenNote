"""Text from images and PDFs with the real Tesseract (installed in CI and in the image)."""

import subprocess
import sys
from pathlib import Path

import pytest

from app.ocr import extract
from app.ocr.extract import OcrError, extract_text
from app.ocr.vault import is_candidate, run_isolated
from tests import ocr_samples

BACKEND_DIR = Path(__file__).resolve().parents[3]


def _words(text: str) -> str:
    return " ".join(text.lower().split())


def test_an_image_is_read_by_tesseract():
    assert "opennote receipt" in _words(extract_text(ocr_samples.png(), "eng"))


def test_a_pdf_text_layer_is_used_without_tesseract(monkeypatch):
    def no_tesseract(image: bytes, languages: str) -> str:
        raise AssertionError("tesseract was called")

    monkeypatch.setattr(extract, "tesseract", no_tesseract)
    assert extract_text(ocr_samples.text_pdf(), "eng") == ocr_samples.TEXT


def test_a_scanned_pdf_page_is_rendered_and_read():
    assert "opennote receipt" in _words(extract_text(ocr_samples.scanned_pdf(), "eng"))


def test_pages_after_the_limit_are_left_out(monkeypatch):
    monkeypatch.setattr(extract, "MAX_PDF_PAGES", 0)
    assert extract_text(ocr_samples.text_pdf(), "eng") == ""


@pytest.mark.parametrize(
    "data", [b"plain text", b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, b"%PDF-1.4 broken"]
)
def test_other_or_broken_files_are_refused(data):
    with pytest.raises(OcrError):
        extract_text(data, "eng")


def test_the_child_process_reads_stdin_and_writes_the_text():
    result = subprocess.run(
        [sys.executable, "-m", "app.ocr", "eng"],
        input=ocr_samples.text_pdf(),
        capture_output=True,
        cwd=BACKEND_DIR,
        check=True,
    )
    assert result.stdout.decode() == ocr_samples.TEXT


def test_run_isolated_returns_none_for_an_unreadable_file():
    assert run_isolated(b"not an image", "eng") is None
    assert "receipt" in (run_isolated(ocr_samples.png(), "eng") or "").lower()


def test_run_isolated_gives_up_on_a_slow_file(monkeypatch):
    from app.ocr import vault

    monkeypatch.setattr(vault, "FILE_TIMEOUT", 0.001)
    assert run_isolated(ocr_samples.png(), "eng") is None


@pytest.mark.parametrize(
    ("path", "expected"),
    [("Scans/a.PNG", True), ("x.jpeg", True), ("r.pdf", True), ("n.md", False), (None, False)],
)
def test_candidates_are_images_and_pdfs(path, expected):
    assert is_candidate(path) is expected
