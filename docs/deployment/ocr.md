# OCR of scanned attachments

OpenNote reads the text in image and PDF attachments so that search finds the notes that
link to them (P6-06). It runs in the worker, fully on your own server.

## How it works

- Uploading or changing an attachment whose name ends in `.png`, `.jpg`, `.jpeg`, `.tif`,
  `.tiff`, `.webp`, `.bmp` or `.pdf` through the API enqueues `ocr_vault_job` for its
  vault. GIF images are not read: the UBI 10 repositories have no GIF library to build
  Leptonica with.
- A run reads every live attachment of that kind whose content has not been read before.
  A PDF page with a text layer gives that text; a page without one (a scan) is rendered
  at 300 dpi and read by Tesseract, like an image. At most 50 pages per PDF are read and
  at most 1,000,000 characters are kept per attachment.
- Each file is read in a child process limited to 2 GiB of memory and 10 minutes, so a
  broken or hostile file cannot take the worker down. A file that cannot be read is
  recorded as failed and is not tried again until its content changes.
- The text is stored in the `ocr_texts` table, per vault and content hash: a renamed or
  copied attachment is not read again. Text of attachments deleted from the vault is
  removed on the vault's next run.
- Search words and phrases match it: a note that embeds or links to the attachment is a
  hit. Attachments themselves are not search results.

## Languages

The image ships Tesseract with English only. Set `OPENNOTE_OCR_LANGUAGES` on the worker,
for example `eng+dan+swe`, and add the language data to the image:

```dockerfile
FROM opennote-api:<version>
USER 0
RUN microdnf install -y --nodocs tesseract-langpack-dan tesseract-langpack-swe \
    && microdnf clean all
USER 1001:0
```

While a configured language has no data in the image, the worker logs an error and reads
nothing; files are read once the image has it.

## Attachments uploaded before OCR

A run reads every unread attachment in the vault, so the next image or PDF upload catches
up on older ones. To read a vault now, run in the worker container:

```bash
python -m app.ocr.vault <vault-id>
```

## Where Tesseract comes from

Tesseract is not in the free UBI repositories (RHEL 10 has it in AppStream, so EPEL 10 does
not ship it either). The `opennote-api` image (which also runs the worker) builds Leptonica
and Tesseract from their upstream source releases in a builder stage, checks each archive and
the `tessdata_fast` English model against a pinned SHA-256, and installs them under
`/opt/tesseract` (ADR-0010, amendment of 2026-11-19). The image formats Tesseract reads are
the image libraries it was built with (`tesseract --version` lists them); the image sets
`TESSDATA_PREFIX`, which the worker passes on to Tesseract. Without the
`tesseract` binary (for example in a development checkout without it) the job logs a
warning and reads nothing.
