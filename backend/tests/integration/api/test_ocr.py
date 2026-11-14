"""OCR of image and PDF attachments (P6-06) against the real database and Tesseract: an
upload asks the worker to read its vault, a run reads each new attachment once, and
search finds the notes that link to an attachment by the attachment's text."""

import uuid

import pytest
from dramatiq import Message
from dramatiq.brokers.stub import StubBroker
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ocr import jobs, vault
from app.ocr.models import OcrText
from app.ocr.vault import ocr_vault
from tests import ocr_samples
from tests.integration.api.test_attachments import upload
from tests.integration.api.test_search import put

pytestmark = pytest.mark.anyio


@pytest.fixture
def stub(monkeypatch: pytest.MonkeyPatch) -> StubBroker:
    broker = StubBroker()
    broker.declare_queue("default")
    monkeypatch.setattr(vault, "_broker", lambda settings: broker)
    return broker


def sent(broker: StubBroker) -> list[Message]:
    queue = broker.queues["default"]
    return [Message.decode(queue.get_nowait()) for _ in range(queue.qsize())]


def rows(api, vault_id: uuid.UUID) -> dict[str, tuple[str, bool]]:
    with Session(api.engine) as s:
        found = s.scalars(select(OcrText).where(OcrText.vault_id == vault_id)).all()
        return {r.content_hash: (r.text, r.failed) for r in found}


async def search(api, headers, vault_id: uuid.UUID, q: str) -> list[str]:
    response = await api.client.get(
        "/api/v1/search", params={"q": q, "vault_id": str(vault_id)}, headers=headers
    )
    assert response.status_code == 200, response.text
    return [hit["note"]["path"] for hit in response.json()["items"]]


async def test_an_image_upload_enqueues_the_ocr_job(api, stub):
    alice = api.user("alice")
    work = api.vault(alice)
    headers = await api.bearer(alice)
    response = await upload(api, headers, work, "Scans/receipt.png", ocr_samples.png())
    assert response.status_code == 201, response.text
    [message] = sent(stub)
    assert (message.actor_name, message.args) == (jobs.ocr_vault_job.actor_name, (str(work),))


async def test_a_note_save_does_not_enqueue_it(api, stub):
    alice = api.user("alice")
    work = api.vault(alice)
    body = {"vault_id": str(work), "path": "Inbox/Idea.md", "content": "hello\n"}
    response = await api.client.post("/api/v1/notes", json=body, headers=await api.bearer(alice))
    assert response.status_code == 201, response.text
    assert sent(stub) == []


async def test_a_broken_broker_does_not_fail_the_upload(api, monkeypatch, caplog):
    def broken(settings):
        raise ConnectionError("valkey down")

    monkeypatch.setattr(vault, "_broker", broken)
    alice = api.user("alice")
    work = api.vault(alice)
    response = await upload(api, await api.bearer(alice), work, "a.png", ocr_samples.png())
    assert response.status_code == 201, response.text
    assert "ocr: run not requested" in caplog.text


async def test_search_finds_a_note_by_the_text_of_its_scans(api):
    alice = api.user("alice")
    work = api.vault(alice)
    headers = await api.bearer(alice)
    put(api, work, "Scans/receipt.png", ocr_samples.png())
    put(api, work, "Scans/invoice.pdf", ocr_samples.scanned_pdf("Invoice from Bornholm"))
    put(api, work, "Scans/letter.pdf", ocr_samples.text_pdf("Letter about Gotland"))
    put(api, work, "Scans/broken.pdf", b"%PDF-1.4 broken")
    put(api, work, "Expenses.md", "Paid.\n\n![[receipt.png]]\n")
    put(api, work, "Trip.md", "See [[invoice.pdf]] and [[letter.pdf]].\n")
    put(api, work, "Unrelated.md", "Nothing attached.\n")

    assert await search(api, headers, work, "receipt") == []
    assert ocr_vault(api.engine, work, "eng") == 4
    assert await search(api, headers, work, "receipt") == ["Expenses.md"]
    assert await search(api, headers, work, "bornholm") == ["Trip.md"]
    assert await search(api, headers, work, "gotland") == ["Trip.md"]
    assert await search(api, headers, work, '"letter about gotland"') == ["Trip.md"]
    assert await search(api, headers, work, "gotland -bornholm") == []
    assert sum(failed for _, failed in rows(api, work).values()) == 1

    # Nothing new: nothing is read again.
    assert ocr_vault(api.engine, work, "eng") == 0


async def test_text_of_deleted_attachments_is_removed_and_not_found(api):
    alice = api.user("alice")
    work = api.vault(alice)
    headers = await api.bearer(alice)
    image = put(api, work, "Scans/receipt.png", ocr_samples.png())
    put(api, work, "Expenses.md", "![[receipt.png]]\n")
    assert ocr_vault(api.engine, work, "eng") == 1

    response = await api.client.delete(
        f"/api/v1/attachments/{image}", headers=headers | {"If-Match": '"1"'}
    )
    assert response.status_code in (200, 204), response.text
    assert await search(api, headers, work, "receipt") == []
    ocr_vault(api.engine, work, "eng")
    assert rows(api, work) == {}


async def test_ocr_text_stays_inside_its_vault(api):
    alice, bob = api.user("alice"), api.user("bob")
    work, other = api.vault(alice, "Work"), api.vault(bob, "Other")
    data = ocr_samples.png()
    put(api, work, "receipt.png", data)
    put(api, other, "receipt.png", data)
    put(api, other, "Bob.md", "![[receipt.png]]\n")
    assert ocr_vault(api.engine, work, "eng") == 1
    assert await search(api, await api.bearer(bob), other, "receipt") == []


async def test_a_vault_in_use_is_left_for_later(api):
    alice = api.user("alice")
    work = api.vault(alice)
    with api.engine.connect() as held:
        key = int.from_bytes(work.bytes[:4], signed=True)
        held.exec_driver_sql("select pg_advisory_lock(%s, %s)", (vault.LOCK_CLASS, key))
        assert ocr_vault(api.engine, work, "eng") is None
        held.exec_driver_sql("select pg_advisory_unlock(%s, %s)", (vault.LOCK_CLASS, key))
    assert ocr_vault(api.engine, work, "eng") == 0


def test_without_tesseract_nothing_is_read(api, monkeypatch, caplog):
    monkeypatch.setattr(vault.shutil, "which", lambda name: None)
    alice = api.user("alice")
    work = api.vault(alice)
    put(api, work, "receipt.png", ocr_samples.png())
    assert ocr_vault(api.engine, work, "eng") == 0
    assert rows(api, work) == {}
    assert "tesseract is not installed" in caplog.text
