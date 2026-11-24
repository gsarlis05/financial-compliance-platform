"""Problem responses, correlation IDs and log redaction (AC-M0-4, AC-E1/E2)."""

import io
import json
import logging
import uuid
from collections.abc import Iterator

import pytest
import structlog
from django.test import Client, override_settings

from fcp.core.logging import REDACTED, json_formatter, scrub

SENSITIVE = {
    "name": "Eleni Georgiou",
    "email": "eleni.georgiou@example.com",
    "iban": "CY17002001280000001200527600",
    "tin": "12345678L",
    "amount": "98765.43",
}


@pytest.fixture
def log_output() -> Iterator[io.StringIO]:
    """Capture everything logged through the production JSON formatter."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(json_formatter())
    root = logging.getLogger()
    root.addHandler(handler)
    previous = root.level
    root.setLevel(logging.INFO)
    try:
        yield stream
    finally:
        root.removeHandler(handler)
        root.setLevel(previous)


def log_lines(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


pytestmark = pytest.mark.urls("tests.error_urls")


# --- problem responses --------------------------------------------------------------------


def test_domain_error_becomes_problem_json() -> None:
    response = Client().get("/domain-error")
    assert response.status_code == 422
    assert response["Content-Type"] == "application/problem+json"
    body = response.json()
    assert body["type"] == "urn:fcp:problem:validation_failed"
    assert body["code"] == "validation_failed"
    assert body["title"] == "Validation failed"
    assert body["detail"] == "The journal entry does not balance."
    assert body["errors"] == {"lines": ["Debits and credits differ by 0.01."]}
    assert body["instance"] == "/domain-error"
    assert body["correlation_id"] == response["X-Request-ID"]


def test_money_error_becomes_422_problem() -> None:
    response = Client().get("/money-error")
    assert response.status_code == 422
    assert response.json()["code"] == "money.invalid_amount"


def test_unhandled_exception_returns_generic_500_without_internals(
    log_output: io.StringIO,
) -> None:
    response = Client().get("/boom", {"email": SENSITIVE["email"], "iban": SENSITIVE["iban"]})
    assert response.status_code == 500
    assert response["Content-Type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "internal_error"
    assert "correlation ID" in body["detail"]
    text = response.content.decode()
    for leaked in ("Traceback", "RuntimeError", SENSITIVE["email"], SENSITIVE["iban"]):
        assert leaked not in text
    # The exception is logged (with traceback) for operators, scrubbed of sensitive data.
    errors = [
        line for line in log_lines(log_output) if line["event"] == "request.unhandled_exception"
    ]
    assert len(errors) == 1
    assert errors[0]["error_type"] == "RuntimeError"
    assert "Traceback" in str(errors[0]["exception"])
    assert errors[0]["correlation_id"] == body["correlation_id"]
    raw = log_output.getvalue()
    assert SENSITIVE["email"] not in raw
    assert SENSITIVE["iban"] not in raw


def test_unknown_url_returns_problem_404() -> None:
    response = Client().get("/does-not-exist")
    assert response.status_code == 404
    assert response["Content-Type"] == "application/problem+json"
    assert response.json()["code"] == "not_found"


# --- correlation IDs ------------------------------------------------------------------------


def test_safe_incoming_correlation_id_is_reused() -> None:
    response = Client().get("/domain-error", headers={"X-Request-ID": "abc12345-req"})
    assert response["X-Request-ID"] == "abc12345-req"
    assert response.json()["correlation_id"] == "abc12345-req"


@pytest.mark.parametrize(
    "malicious", ["short", "x" * 65, "abc12345\nfake log line", "abc12345<script>", "abc 12345"]
)
def test_unsafe_incoming_correlation_id_is_replaced(malicious: str) -> None:
    response = Client().get("/domain-error", headers={"X-Request-ID": malicious})
    assert response["X-Request-ID"] != malicious
    uuid.UUID(response["X-Request-ID"])


def test_request_completion_is_logged_without_query_string(log_output: io.StringIO) -> None:
    Client().get("/log-sensitive", {"email": SENSITIVE["email"]})
    completed = [line for line in log_lines(log_output) if line["event"] == "request.completed"]
    assert len(completed) == 1
    assert completed[0]["path"] == "/log-sensitive"
    assert completed[0]["status_code"] == 200
    assert completed[0]["method"] == "GET"
    assert isinstance(completed[0]["duration_ms"], int)


# --- redaction (AC-M0-4) --------------------------------------------------------------------


def test_sensitive_values_never_reach_logs(log_output: io.StringIO) -> None:
    Client().get("/log-sensitive", SENSITIVE)
    raw = log_output.getvalue()
    for key, value in SENSITIVE.items():
        assert value not in raw, f"{key} leaked into logs"
    updated = next(line for line in log_lines(log_output) if line["event"] == "customer.updated")
    for key in ("customer_name", "email", "iban", "tax_id", "amount"):
        assert updated[key] == REDACTED
    # Opaque identifiers on the allow-list are kept.
    assert updated["entity_id"] == "9b7c1a2e-0000-4000-8000-000000000001"
    lookup = next(line for line in log_lines(log_output) if line["event"] == "customer.lookup")
    assert lookup["path"] == "/customers/[EMAIL]"


def test_stdlib_loggers_are_redacted_too(log_output: io.StringIO) -> None:
    logging.getLogger("thirdparty").warning("contact %s", SENSITIVE["email"])
    assert SENSITIVE["email"] not in log_output.getvalue()
    assert "[EMAIL]" in log_output.getvalue()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("mail eleni@example.com now", "mail [EMAIL] now"),
        ("iban CY17002001280000001200527600", "iban [IBAN]"),
        ("iban CY17 0020 0128 0000 0012 0052 7600", "iban [IBAN]"),
        ("vat CY12345678L", "vat [TAX_ID]"),
        ("tin 12345678L", "tin [TAX_ID]"),
        ("card 4111 1111 1111 1111", "card [NUMBER]"),
        ("paid 1,234.56 and 99.5", "paid [AMOUNT] and [AMOUNT]"),
        ("paid 1.234,56", "paid [AMOUNT]"),
        (
            "entity 9b7c1a2e-0000-4000-8000-000000000001",
            "entity 9b7c1a2e-0000-4000-8000-000000000001",
        ),
        ("status 200 in 15 ms", "status 200 in 15 ms"),
        ("marker \x0099\x00 survives", "marker \x0099\x00 survives"),
    ],
)
def test_scrub_patterns(text: str, expected: str) -> None:
    assert scrub(text) == expected


def test_scrub_handles_nested_structures(log_output: io.StringIO) -> None:
    structlog.get_logger("nested").info("x", count={"a": ["eleni@example.com"]})
    line = log_lines(log_output)[-1]
    assert line["count"] == {"a": ["[EMAIL]"]}


@override_settings(DEBUG=True)
def test_debug_mode_still_returns_problem_json_not_debug_page() -> None:
    response = Client().get("/boom")
    assert response.status_code == 500
    assert response["Content-Type"] == "application/problem+json"
