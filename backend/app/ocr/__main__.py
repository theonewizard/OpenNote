"""`python -m app.ocr <languages>`: the file's bytes on stdin, its text (UTF-8) on stdout.
Exit status 1 when the file cannot be read; the reason goes to stderr."""

import sys

from app.ocr.extract import OcrError, extract_text


def main() -> None:
    try:
        text = extract_text(sys.stdin.buffer.read(), sys.argv[1])
    except OcrError as exc:
        sys.exit(f"ocr: {exc}")
    sys.stdout.buffer.write(text.encode())


if __name__ == "__main__":
    main()
