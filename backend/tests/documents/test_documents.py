"""Document vault (M2-4, AC-M2-4): upload pipeline, antivirus, type checks, isolation, links.

These tests use the real services: SeaweedFS (S3 API) and ClamAV (``make services`` locally; CI
starts both).
"""

import base64
import contextlib
import io
import json
import logging
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, transaction
from django.test import override_settings
from hypothesis import given, settings
from hypothesis import strategies as st
from openpyxl import Workbook

from fcp.core.db.rls import set_context
from fcp.modules.audit_log.models import AuditEvent
from fcp.modules.documents import sniff, storage
from fcp.modules.documents.models import Document

from ..ledger.conftest import books, join
from ..ledger.test_dimensions import commit_point
from ..ledger.test_entries import act

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books"]

PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


@pytest.fixture(autouse=True)
def bucket(document_bucket: None) -> None:
    del document_bucket


def upload(b: dict[str, Any], name: str, data: bytes, client: Any = None, **form: str) -> Any:
    client = client or b["client"]
    return client.post(
        f"{b['base']}/documents",
        {"file": SimpleUploadedFile(name, data), **form},
        headers=client._csrf(),
    )


def posted(b: dict[str, Any], *lines: dict[str, Any]) -> dict[str, Any]:
    body = {"accounting_date": "2026-03-15", "description": "Entry", "lines": list(lines)}
    draft = b["client"].post_json(f"{b['base']}/journal-entries", body)
    assert draft.status_code == 201, draft.content
    result = act(b, draft.json()["id"], "post")
    assert result.status_code == 200, result.content
    commit_point()
    out: dict[str, Any] = result.json()
    return out


@pytest.fixture
def docs(books: dict[str, Any]) -> dict[str, Any]:
    books["client"].put_json(f"{books['base']}/ledger-settings", {"approval_policy": "NONE"})
    acc = books["accounts"]
    books["entry"] = posted(
        books,
        {"account_id": acc["6100"]["id"], "debit": "100.00"},
        {"account_id": acc["1300"]["id"], "credit": "100.00"},
    )
    customer = (
        books["client"]
        .post_json(
            f"{books['base']}/counterparties",
            {"code": "C1", "name": "Customer", "kind": "CUSTOMER"},
        )
        .json()
    )
    invoice = posted(
        books,
        {
            "account_id": acc["1200"]["id"],
            "debit": "50.00",
            "counterparty_id": customer["id"],
            "reference": "INV-1",
        },
        {"account_id": acc["4000"]["id"], "credit": "50.00"},
    )
    books["invoice"] = invoice
    set_context(tenant_id=books["ws"]["id"])
    from fcp.modules.ledger.models import JournalLine  # noqa: PLC0415

    books["open_item"] = str(
        JournalLine.objects.get(entry_id=invoice["id"], account_id=acc["1200"]["id"]).id
    )
    books["expense_line"] = str(
        JournalLine.objects.get(entry_id=books["entry"]["id"], account_id=acc["6100"]["id"]).id
    )
    return books


def test_upload_attach_list_and_download(docs: dict[str, Any]) -> None:
    made = upload(docs, "invoice-INV-1.pdf", PDF, entry_id=docs["entry"]["id"])
    assert made.status_code == 201, made.content
    document = made.json()
    assert (document["content_type"], document["size"]) == ("application/pdf", len(PDF))
    assert [ln["entry_id"] for ln in document["links"]] == [docs["entry"]["id"]]
    again = upload(docs, "copy.pdf", PDF)
    assert (again.status_code, again.json()["id"]) == (200, document["id"])  # same content

    listed = docs["client"].get(f"{docs['base']}/documents", {"entry_id": docs["entry"]["id"]})
    assert [d["id"] for d in listed.json()] == [document["id"]]
    content = docs["client"].get(f"{docs['base']}/documents/{document['id']}/content")
    assert content.status_code == 200
    assert content.content == PDF
    assert content["X-Content-Type-Options"] == "nosniff"
    assert content["Content-Disposition"].startswith('attachment; filename="invoice-INV-1.pdf"')

    set_context(tenant_id=docs["ws"]["id"])
    stored = Document.objects.get(id=document["id"])
    assert stored.storage_key.startswith(f"tenants/{docs['ws']['id']}/documents/")
    events = AuditEvent.objects.filter(action__startswith="documents.")
    assert {e.action for e in events} == {
        "documents.uploaded",
        "documents.linked",
        "documents.downloaded",
    }
    assert all("%PDF" not in json.dumps(e.changes) for e in events)  # no content in the audit


def test_eicar_is_rejected_and_nothing_is_stored(
    docs: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    rejected = upload(docs, "notes.txt", EICAR)
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "documents.malware_detected"
    assert "Eicar-Test-Signature" in rejected.json()["detail"]
    set_context(tenant_id=docs["ws"]["id"])
    assert not Document.objects.exists()
    event = AuditEvent.objects.get(action="documents.rejected_malware")
    assert event.changes["signature"] == "Eicar-Test-Signature"
    assert "EICAR-STANDARD" not in json.dumps(event.changes)
    assert "EICAR-STANDARD" not in caplog.text  # no content in the logs


@pytest.mark.parametrize(
    ("name", "data", "message"),
    [
        ("receipt.pdf", PNG, "named .pdf but its content is png"),
        ("photo.png", PDF, "named .png but its content is pdf"),
        ("sheet.xlsx", b"PK\x03\x04" + b"\x00" * 40, "named .xlsx"),
        ("data.csv", b"\x00\x01binary", "not a recognised document"),
        ("setup.exe", b"MZ\x90\x00", "Only these file types are accepted"),
        ("no-extension", PDF, "Only these file types are accepted"),
    ],
)
def test_type_must_match_the_extension(
    docs: dict[str, Any], name: str, data: bytes, message: str
) -> None:
    rejected = upload(docs, name, data)
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "documents.type_mismatch"
    assert message in rejected.json()["detail"]


def test_real_spreadsheets_and_text_are_recognised() -> None:
    book = Workbook()
    buffer = io.BytesIO()
    book.save(buffer)
    assert sniff.check("budget.xlsx", buffer.getvalue()).endswith("spreadsheetml.sheet")
    assert sniff.check("a.csv", b"date;amount\n2026-01-01;1,00\n") == "text/csv"
    assert sniff.check("a.xml", b"<?xml version='1.0'?><a/>") == "application/xml"
    assert sniff.check("A.JPG", b"\xff\xd8\xff\xe0rest") == "image/jpeg"


def test_documents_of_other_workspaces_cannot_be_read(
    docs: dict[str, Any], make_user: Make, api_client: Make, make_workspace: Make
) -> None:
    document = upload(docs, "a.pdf", PDF).json()
    stranger = api_client(make_user("stranger@example.test"))
    url = f"{docs['base']}/documents/{document['id']}"
    assert stranger.get(url).status_code == 404
    assert stranger.get(f"{url}/content").status_code == 404
    # The storage layer refuses keys outside the caller's tenant prefix as well.
    set_context(tenant_id=docs["ws"]["id"])
    key = Document.objects.get(id=document["id"]).storage_key
    with pytest.raises(ValueError, match="outside the tenant prefix"):
        storage.get(uuid4(), key)


def test_documents_are_immutable(docs: dict[str, Any]) -> None:
    document = upload(docs, "a.pdf", PDF).json()
    set_context(tenant_id=docs["ws"]["id"])
    with pytest.raises(DatabaseError, match="immutable"), transaction.atomic():
        Document.objects.filter(id=document["id"]).update(filename="other.pdf")
    with pytest.raises(DatabaseError, match="immutable"), transaction.atomic():
        Document.objects.filter(id=document["id"]).delete()


def test_links_to_open_items_and_unlinking(docs: dict[str, Any]) -> None:
    document = upload(docs, "invoice.pdf", PDF).json()
    url = f"{docs['base']}/documents/{document['id']}/links"
    linked = docs["client"].post_json(url, {"line_id": docs["open_item"]})
    assert linked.status_code == 201, linked.content
    assert docs["client"].post_json(url, {"line_id": docs["expense_line"]}).status_code == 422
    assert docs["client"].post_json(url, {"entry_id": str(uuid4())}).status_code == 404
    assert docs["client"].post_json(url, {}).status_code == 422
    by_item = docs["client"].get(f"{docs['base']}/documents", {"line_id": docs["open_item"]})
    assert len(by_item.json()) == 1
    removed = docs["client"].delete_json(f"{docs['base']}/document-links/{linked.json()['id']}")
    assert removed.status_code == 204
    assert docs["client"].get(f"{docs['base']}/documents/{document['id']}").status_code == 200


def test_permissions_size_and_scanner_outage(
    docs: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    viewer = join(
        docs["client"], docs["ws"]["slug"], make_user("ro@example.test"), api_client, "read_only"
    )
    assert upload(docs, "a.pdf", PDF, client=viewer).status_code == 403
    assert viewer.get(f"{docs['base']}/documents").status_code == 200
    with override_settings(DOCUMENTS_MAX_BYTES=10):
        too_big = upload(docs, "a.pdf", PDF)
    assert too_big.json()["code"] == "documents.too_large"
    with override_settings(CLAMD_PORT=1):  # nothing listens there: fail closed
        down = upload(docs, "b.pdf", PDF + b"x")
    assert down.status_code == 503
    assert down.json()["code"] == "documents.scan_unavailable"
    set_context(tenant_id=docs["ws"]["id"])
    assert not Document.objects.exists()


def test_deployed_storage_uses_sse_kms_with_the_tenant_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class Fake:
        def put_object(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(storage, "_client", Fake)
    tenant = uuid4()
    with override_settings(DOCUMENTS_KMS_KEY_ID="arn:aws:kms:eu-central-1:1:key/k"):
        storage.put(tenant, storage.document_key(tenant, uuid4()), b"x", "application/pdf")
    assert calls[0]["ServerSideEncryption"] == "aws:kms"
    context = json.loads(base64.b64decode(calls[0]["SSEKMSEncryptionContext"]))
    assert context == {"tenant_id": str(tenant)}
    with pytest.raises(ValueError, match="outside the tenant prefix"):
        storage.put(tenant, f"tenants/{uuid4()}/documents/x", b"x", "text/plain")


@pytest.mark.parametrize(
    ("raw", "safe"),
    [
        ("../../etc/passwd.txt", "passwd.txt"),
        ("C:\\Users\\a\\inv\x00oice.pdf", "invoice.pdf"),
        ('re"port<1>.pdf', "report1.pdf"),
        ("...", "document"),
        ("τιμολόγιο.pdf", "τιμολόγιο.pdf"),
    ],
)
def test_filenames_are_made_safe(raw: str, safe: str) -> None:
    assert sniff.safe_filename(raw) == safe


@settings(max_examples=300, deadline=None)
@given(st.binary(max_size=3000), st.sampled_from(list(sniff.ALLOWED)))
def test_sniffing_never_crashes(data: bytes, extension: str) -> None:
    with contextlib.suppress(sniff.DocumentTypeError):
        sniff.check(f"file.{extension}", data)
