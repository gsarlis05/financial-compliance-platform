"""Management report packs (M8-1, AC-MR1 to AC-MR3, AC-MR6) on the goals fixture: books for 2025
and Q1 2026, and an approved 2026 budget of sales 1,000, cost of sales 600, rent 100 and
depreciation 50 a month. March 2026 has no sales: a variance of -1,000 for the month and -2,000
for the year to date, both above the default thresholds (1,000 and 10%), so both need an
explanation before a March pack can be final."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from django.db import DatabaseError, connection, transaction

from fcp.core.db.rls import set_context
from fcp.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from fcp.core.ids import uuid7
from fcp.modules.audit_log.models import AuditEvent
from fcp.modules.mgmt_reporting.models import ReportPack
from fcp.modules.mgmt_reporting.snapshot import _block, missing_explanations

from ..goals.test_goals import budget, g
from ..kpi.test_kpis import _post, k
from ..ledger.conftest import books, join
from ..projections.test_assumptions import hist
from ..projections.test_projections import approved

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books", "g", "hist", "k"]
MARCH = {"period_kind": "MONTH", "month": "2026-03-01"}


def generate(g: dict[str, Any], body: dict[str, str] = MARCH) -> dict[str, Any]:
    made = g["client"].post_json(f"{g['base']}/report-packs", body)
    assert made.status_code == 201, made.content
    out: dict[str, Any] = made.json()
    return out


def reviewer(g: dict[str, Any], make_user: Make, api_client: Make) -> Any:
    return join(g["client"], g["ws"]["slug"], make_user("reviewer@example.test"), api_client,
                "finance_manager")  # fmt: skip


def act(client: Any, g: dict[str, Any], pack_id: str, what: str, **body: str) -> Any:
    return client.post_json(f"{g['base']}/report-packs/{pack_id}/{what}", body)


def report(pack: dict[str, Any], view: str, comparison: str = "ACTUAL_VS_BUDGET") -> dict[str, Any]:
    reports = pack["snapshot"]["blocks"]["budget"]["data"]["reports"]
    return next(r for r in reports if (r["view"], r["comparison"]) == (view, comparison))


def line(rep: dict[str, Any], code: str) -> dict[str, Any]:
    return next(r for r in rep["rows"] if r["taxonomy_code"] == code)


def explain_all(g: dict[str, Any], pack: dict[str, Any]) -> int:
    """Explain every variance the snapshot says needs one (through the budget review API)."""
    version = pack["snapshot"]["blocks"]["budget"]["data"]["version_id"]
    done = 0
    for rep in pack["snapshot"]["blocks"]["budget"]["data"]["reports"]:
        if rep["comparison"] != "ACTUAL_VS_BUDGET":
            continue
        for r in rep["rows"]:
            if r["requires_explanation"] and not r["explanation"]:
                made = g["client"].post_json(
                    f"{g['base']}/budget-versions/{version}/explanations",
                    {"line_id": r["line_id"], "month": "2026-03-01", "view": rep["view"],
                     "comparison": "ACTUAL_VS_BUDGET", "comment": "Orders moved to April"},
                )  # fmt: skip
                assert made.status_code == 201, made.content
                done += 1
    return done


def test_a_pack_freezes_its_figures(g: dict[str, Any]) -> None:
    """AC-MR1: every figure and reference is frozen; a later posting changes nothing."""
    budget(g)
    pack = generate(g)
    assert (pack["status"], pack["version"], pack["title"]) == (
        "DRAFT", 1, "Management pack, March 2026")  # fmt: skip
    assert (pack["period_start"], pack["period_end"]) == ("2026-03-01", "2026-03-31")
    assert pack["blocks"] == {"statements": "ok", "budget": "ok", "kpis": "empty",
                              "cash": "empty", "projection": "empty", "goals": "ok"}  # fmt: skip
    blocks = pack["snapshot"]["blocks"]
    assert blocks["kpis"]["reason"] == "No KPI set for this period yet."
    assert blocks["projection"]["reason"] == (
        "No published projection covers the months after this period.")  # fmt: skip
    # The variance report, by hand: sales 0 against 1,000 in March, 1,000 against 3,000 to date.
    month, ytd = line(report(pack, "MONTH"), "REV.SALES"), line(report(pack, "YTD"), "REV.SALES")
    assert (month["subject"], month["comparison"], month["variance"]) == (
        "0.00", "1000.00", "-1000.00")  # fmt: skip
    assert (ytd["subject"], ytd["comparison"], ytd["variance"]) == ("1000.00", "3000.00",
                                                                    "-2000.00")  # fmt: skip
    assert month["requires_explanation"]
    assert ytd["requires_explanation"]
    assert report(pack, "YTD", "ACTUAL_VS_PRIOR_YEAR")["rows"]
    refs = pack["snapshot"]["references"]
    assert refs["watermark"] == pack["watermark"] > 0
    assert refs["budget_version_id"] == blocks["budget"]["data"]["version_id"]
    statement_kinds = [s["kind"] for s in blocks["statements"]["data"]["statements"]]
    assert statement_kinds == ["PL", "BS", "CF"]

    # A posting after generation (even one dated in March) leaves the pack as it was.
    _post(g, "2026-03-28", ("1300", "75", "0", None), ("4000", "0", "75", None))
    again = g["client"].get(f"{g['base']}/report-packs/{pack['id']}").json()
    assert (again["snapshot"], again["snapshot_hash"]) == (pack["snapshot"], pack["snapshot_hash"])
    # Regenerating the draft takes the figures again: March sales are now 75.
    fresh = act(g["client"], g, pack["id"], "regenerate").json()
    assert fresh["snapshot_hash"] != pack["snapshot_hash"]
    assert line(report(fresh, "MONTH"), "REV.SALES")["subject"] == "75.00"
    listed = g["client"].get(f"{g['base']}/report-packs").json()
    assert [p["id"] for p in listed] == [pack["id"]]


def test_review_and_finalise(g: dict[str, Any], make_user: Make, api_client: Make) -> None:
    """AC-MR3: the reviewer is never the preparer; missing explanations and changed figures
    block finalising, with what to do; later months do not."""
    budget(g)
    boss = reviewer(g, make_user, api_client)
    pack = generate(g)
    assert act(g["client"], g, pack["id"], "submit").status_code == 200
    # In review, the pack is frozen for its preparer too.
    assert act(g["client"], g, pack["id"], "regenerate").status_code == 409
    own = act(g["client"], g, pack["id"], "finalise")
    assert own.status_code == 403, own.content  # the owner prepared it
    refused = act(boss, g, pack["id"], "finalise")
    assert refused.status_code == 409, refused.content
    assert refused.json()["code"] == "mgmt_reporting.not_finalisable"
    assert "REV.SALES (MONTH)" in refused.json()["detail"]
    shown = boss.get(f"{g['base']}/report-packs/{pack['id']}").json()
    assert "need an explanation" in shown["blockers"][0]

    returned = act(boss, g, pack["id"], "return", note="Explain the sales shortfall")
    assert returned.json()["status"] == "DRAFT"
    assert returned.json()["review_note"] == "Explain the sales shortfall"
    assert explain_all(g, pack) >= 2  # at least the month and the year to date
    pack = act(g["client"], g, pack["id"], "regenerate").json()
    assert act(g["client"], g, pack["id"], "submit").status_code == 200
    # An entry dated in March, posted while in review, changes the period's figures.
    _post(g, "2026-03-29", ("6100", "20", "0", None), ("1300", "0", "20", None))
    changed = act(boss, g, pack["id"], "finalise")
    assert changed.status_code == 409
    assert "figures have changed" in changed.json()["detail"]
    act(boss, g, pack["id"], "return", note="Regenerate")
    explain_all(g, act(g["client"], g, pack["id"], "regenerate").json())
    pack = act(g["client"], g, pack["id"], "regenerate").json()
    act(g["client"], g, pack["id"], "submit")
    # An entry for April does not touch March: the pack can be final.
    _post(g, "2026-04-02", ("6100", "20", "0", None), ("1300", "0", "20", None))
    final = act(boss, g, pack["id"], "finalise", note="Approved for the board")
    assert final.status_code == 200, final.content
    body = final.json()
    assert (body["status"], body["review_note"]) == ("FINAL", "Approved for the board")
    assert body["reviewed_by_id"] != body["created_by_id"]
    assert act(g["client"], g, pack["id"], "regenerate").status_code == 409

    set_context(tenant_id=UUID(g["ws"]["id"]))
    actions = list(AuditEvent.objects.filter(subject_id=pack["id"]).order_by("seq")
                   .values_list("action", flat=True))  # fmt: skip
    assert actions[0] == "mgmt_reporting.pack_generated"
    assert actions[-1] == "mgmt_reporting.pack_finalised"
    assert "mgmt_reporting.pack_returned" in actions


def test_new_versions_and_the_database(g: dict[str, Any], make_user: Make,
                                       api_client: Make) -> None:  # fmt: skip
    """AC-MR2: a final pack never changes or disappears; a correction is a new version that
    supersedes it once final."""
    budget(g)
    boss = reviewer(g, make_user, api_client)
    pack = generate(g)
    explain_all(g, pack)
    pack = act(g["client"], g, pack["id"], "regenerate").json()
    act(g["client"], g, pack["id"], "submit")
    assert act(boss, g, pack["id"], "finalise").status_code == 200

    v2 = act(g["client"], g, pack["id"], "new-version")
    assert v2.status_code == 201, v2.content
    second = v2.json()
    assert (second["version"], second["supersedes_id"], second["status"]) == (2, pack["id"],
                                                                              "DRAFT")  # fmt: skip
    again = act(g["client"], g, pack["id"], "new-version")
    assert again.status_code == 409  # one correction at a time, from the latest final version
    act(g["client"], g, second["id"], "submit")
    assert act(boss, g, second["id"], "finalise").status_code == 200
    first = g["client"].get(f"{g['base']}/report-packs/{pack['id']}").json()
    assert first["status"] == "SUPERSEDED"

    set_context(tenant_id=UUID(g["ws"]["id"]))
    final = ReportPack.objects.get(id=second["id"])
    with pytest.raises(DatabaseError, match="never changes"), transaction.atomic():
        ReportPack.objects.filter(id=final.id).update(snapshot={"changed": True})
    with pytest.raises(DatabaseError, match="never change"), transaction.atomic():
        ReportPack.objects.filter(id=final.id).update(period_end="2026-04-30")
    with pytest.raises(DatabaseError, match="kept"), transaction.atomic(), \
            connection.cursor() as cur:  # fmt: skip
        cur.execute("DELETE FROM mgmt_reporting_pack WHERE id = %s", [final.id])
    with pytest.raises(DatabaseError, match="starts as a draft"), transaction.atomic():
        ReportPack.objects.create(
            tenant_id=final.tenant_id, legal_entity_id=final.legal_entity_id,
            family_id=final.family_id, version=9, title="X", period_kind="MONTH",
            period_start=final.period_start, period_end=final.period_end, status="FINAL",
            snapshot_hash="x", watermark=1, generated_at=final.generated_at,
            generated_by_id=final.created_by_id, created_by_id=final.created_by_id,
            reviewed_by_id=final.reviewed_by_id, finalised_at=final.finalised_at,
        )  # fmt: skip
    with pytest.raises(DatabaseError, match="follows the final version"), transaction.atomic():
        ReportPack.objects.create(
            tenant_id=final.tenant_id, legal_entity_id=final.legal_entity_id,
            family_id=final.family_id, version=2, supersedes_id=pack["id"], title="X",
            period_kind="MONTH", period_start=final.period_start, period_end=final.period_end,
            snapshot_hash="x", watermark=1, generated_at=final.generated_at,
            generated_by_id=final.created_by_id, created_by_id=final.created_by_id,
        )  # fmt: skip
    # The preparer can never review their own pack, even straight in the database.
    draft = generate(g, {"period_kind": "QUARTER", "month": "2026-02-15"})
    assert (draft["period_start"], draft["period_end"]) == ("2026-01-01", "2026-03-31")
    act(g["client"], g, draft["id"], "submit")
    set_context(tenant_id=UUID(g["ws"]["id"]))
    with pytest.raises(DatabaseError, match="cannot be its preparer"), transaction.atomic():
        ReportPack.objects.filter(id=draft["id"]).update(
            status="FINAL", reviewed_by_id=final.created_by_id, finalised_at=final.finalised_at
        )
    with pytest.raises(DatabaseError, match="in review cannot be edited"), transaction.atomic():
        ReportPack.objects.filter(id=draft["id"]).update(title="Changed in review")


def test_permissions_and_scope(g: dict[str, Any], make_user: Make, api_client: Make) -> None:
    """Read-only users see packs but cannot make them; preparers cannot finalise; a block the
    preparer may not see says so instead of holding the figures (AC-MR6, T30)."""
    budget(g)
    pack = generate(g, {"period_kind": "YEAR", "month": "2026-03-01", "title": "FY 2026"})
    assert (pack["title"], pack["period_start"], pack["period_end"]) == (
        "FY 2026", "2026-01-01", "2026-12-31")  # fmt: skip
    viewer = join(g["client"], g["ws"]["slug"], make_user("viewer@example.test"), api_client,
                  "read_only")  # fmt: skip
    assert viewer.get(f"{g['base']}/report-packs").status_code == 200
    assert viewer.post_json(f"{g['base']}/report-packs", MARCH).status_code == 403
    clerk = join(g["client"], g["ws"]["slug"], make_user("clerk@example.test"), api_client,
                 "accountant")  # fmt: skip
    act(g["client"], g, pack["id"], "submit")
    assert act(clerk, g, pack["id"], "finalise").status_code == 403
    assert act(clerk, g, pack["id"], "return", note="x").status_code == 403
    holder = join(g["client"], g["ws"]["slug"], make_user("holder@example.test"), api_client,
                  "budget_holder")  # fmt: skip
    assert holder.get(f"{g['base']}/report-packs/{pack['id']}").status_code == 403

    def denied() -> dict[str, Any]:
        raise PermissionDeniedError("no")

    def missing() -> dict[str, Any]:
        raise NotFoundError("")

    assert _block(denied, "x") == {"status": "denied", "data": {},
                                   "reason": "You do not have permission to see this."}  # fmt: skip
    assert _block(missing, "Nothing yet.")["reason"] == "Nothing yet."

    def refused() -> dict[str, Any]:
        raise ConflictError("Create a fiscal year first.")

    assert _block(refused, "x")["reason"] == "Create a fiscal year first."
    assert missing_explanations({"blocks": {"budget": {"status": "denied"}}}) == []
    assert g["client"].get(f"{g['base']}/report-packs/{uuid7()}").status_code == 404
    draft = generate(g)
    renamed = g["client"].put_json(f"{g['base']}/report-packs/{draft['id']}/title",
                                   {"title": "March for the board"})  # fmt: skip
    assert renamed.json()["title"] == "March for the board"


def test_kpis_cash_and_projection_blocks(hist: dict[str, Any]) -> None:
    """With a KPI set, a 13-week forecast and a published projection, their blocks hold the
    figures and the pack names the runs; the projection says its engine is pending review."""
    c, base = hist["client"], hist["base"]
    run = c.post_json(f"{base}/projections", {"assumption_set_id": approved(hist)}).json()
    assert c.post_json(f"{base}/calc-runs/{run['id']}/publish", {}).status_code == 200
    kpis = c.post_json(f"{base}/kpi-sets", {"date_from": "2026-12-01", "date_to": "2026-12-31"})
    assert kpis.status_code == 201, kpis.content
    cash = c.post_json(f"{base}/cash-forecasts", {"as_of": "2026-12-31"})
    assert cash.status_code == 201, cash.content
    pack = generate(hist, {"period_kind": "MONTH", "month": "2026-12-01"})
    assert pack["blocks"] == {"statements": "ok", "budget": "empty", "kpis": "ok", "cash": "ok",
                              "projection": "ok", "goals": "ok"}  # fmt: skip
    blocks = pack["snapshot"]["blocks"]
    assert blocks["budget"]["reason"] == "No approved annual budget covers this period."
    projected = blocks["projection"]["data"]
    assert (projected["run_id"], projected["engine_status"], projected["nature"]) == (
        run["id"], "PENDING_PROFESSIONAL_REVIEW", "FORECAST")  # fmt: skip
    assert projected["months"][0] == "2027-01-01"
    assert len(projected["rows"]["BS.CASH"]) == len(projected["months"]) == 12
    latest = c.get(f"{base}/projections/{run['id']}").json()
    assert projected["rows"]["BS.CASH"][0] == latest["rows"]["BS.CASH"][1]  # January 2027
    assert blocks["kpis"]["data"]["run_id"] == kpis.json()["run_id"]
    assert {v["key"] for v in blocks["kpis"]["data"]["values"]} >= {"GROSS_MARGIN", "DSO"}
    assert blocks["cash"]["data"]["run_id"] == cash.json()["run_id"]
    assert len(blocks["cash"]["data"]["weeks"]) == 13
    assert pack["snapshot"]["references"]["calc_runs"] == {
        "kpis": kpis.json()["run_id"],
        "cash": cash.json()["run_id"],
        "projection": run["id"],
    }
