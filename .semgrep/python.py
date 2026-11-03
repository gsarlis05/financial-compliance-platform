# Semgrep rule tests: run `semgrep --test .semgrep/`. Each "ruleid" line must match, "ok" must not.
# This file is never executed or imported.
import contextlib
import logging

log = logging.getLogger(__name__)


def swallowed(op):
    # ruleid: fcp-swallowed-exception
    try:
        op()
    except:
        pass
    # ruleid: fcp-swallowed-exception
    try:
        op()
    except ValueError:
        pass
    # ruleid: fcp-swallowed-exception
    try:
        op()
    except ValueError as exc:
        pass
    # ruleid: fcp-swallowed-exception
    with contextlib.suppress(Exception):
        op()
    # ok: fcp-swallowed-exception
    try:
        op()
    except ValueError:
        log.warning("operation failed; using default", exc_info=True)
    # ok: fcp-swallowed-exception
    with contextlib.suppress(FileNotFoundError):
        op()


def logging_payloads(request):
    # ruleid: fcp-log-request-payload
    log.info("received %s", request.body)
    # ruleid: fcp-log-request-payload
    log.error("bad form", request.POST)
    # ruleid: fcp-log-request-payload
    log.info("request", extra=request.data)
    # ruleid: fcp-log-request-payload
    log.debug("headers %s", request.headers)
    # ok: fcp-log-request-payload
    log.info("request received", extra={"correlation_id": request.correlation_id})


def sql(cursor, entry_id, Entry):
    # ruleid: fcp-sql-string-building
    cursor.execute(f"SELECT * FROM journal_entry WHERE id = '{entry_id}'")
    # ruleid: fcp-sql-string-building
    cursor.execute("SELECT * FROM journal_entry WHERE id = '%s'" % entry_id)
    # ruleid: fcp-sql-string-building
    Entry.objects.raw("SELECT * FROM journal_entry WHERE id = {}".format(entry_id))
    # ok: fcp-sql-string-building
    cursor.execute("SELECT * FROM journal_entry WHERE id = %s", [entry_id])


def money(value):
    # ruleid: fcp-float-call
    amount = float(value)
    # ok: fcp-float-call
    from decimal import Decimal
    amount = Decimal(value)
    return amount
