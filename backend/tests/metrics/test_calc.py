"""Calculation runs: pinned actuals, lineage, hashes, reproducibility, immutability (M3-2,
AC-CF1, AC-CF3, AC-CF4, doc 12 "Reproducibility" and "Immutability")."""

from collections.abc import Callable
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from django.db import DatabaseError, connection, transaction

from fcp.core.db.rls import set_context
from fcp.core.errors import ValidationFailedError
from fcp.modules.metrics import calc
from fcp.modules.metrics.api import (
    Nature,
    Output,
    RunInputs,
    Source,
    Value,
    execute,
    mark_stale,
    register_engine,
)
from fcp.modules.metrics.models import CalcLineage, CalcResult, CalcRun
from fcp.modules.reporting.api import (
    WatermarkError,
    actuals_monthly,
    cash_daily,
    current_watermark,
    opening_net,
)
from fcp.modules.tenancy import services as tenancy
from fcp.modules.tenancy.api import WorkspaceContext

from ..ledger.conftest import books, join
from ..reporting.test_actuals import post, rb

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books", "rb"]


class CashEngine:
    """A small engine: cash per account at the as-of date, and its total. ``refs['mode']`` makes
    it misbehave on purpose."""

    kind = "TEST_CASH"
    version = "1"

    def load(self, ctx: WorkspaceContext, inputs: RunInputs) -> dict[str, Any]:
        ids = [UUID(a) for a in inputs.refs["accounts"]]
        if inputs.refs.get("mode") == "user_error":
            raise ValidationFailedError("Pick a bank account.")
        _, opening = opening_net(
            ctx,
            inputs.legal_entity_id,
            before=inputs.as_of + timedelta(days=1),
            watermark=inputs.actuals_watermark,
        )
        week = cash_daily(
            ctx,
            inputs.legal_entity_id,
            account_ids=ids,
            date_from=inputs.as_of - timedelta(days=6),
            date_to=inputs.as_of,
            watermark=inputs.actuals_watermark,
        )
        return {"ids": ids, "opening": opening, "week": week.facts}

    def compute(self, inputs: RunInputs, data: dict[str, Any]) -> Output:
        mode = inputs.refs.get("mode")
        if mode == "crash":
            raise RuntimeError("engine bug")
        values: list[Value] = []
        total = Decimal(0)
        for account_id in data["ids"]:
            balance = data["opening"].get(account_id, Decimal(0))
            total += balance
            values.append(
                Value(
                    f"cash.{account_id}",
                    inputs.as_of,
                    Nature.ACTUAL,
                    1.5 if mode == "float" else balance,  # type: ignore[arg-type]
                    "EUR",
                    lineage=(Source("ACTUAL", f"account:{account_id}", balance),),
                )
            )
        moved = sum((f.net_debit for f in data["week"]), Decimal(0))
        values.append(
            Value(
                "cash.total",
                inputs.as_of,
                Nature.ACTUAL,
                total,
                "EUR",
                lineage=tuple(Source("RESULT", f"cash.{a}") for a in data["ids"]),
            )
        )
        values.append(
            Value(
                "cash.week_movement",
                inputs.as_of - timedelta(days=6),
                Nature.ACTUAL,
                moved,
                "EUR",
                period_end=inputs.as_of,
                granularity="WEEK",
            )
        )
        values.append(
            Value(
                "cash.next_week",
                inputs.as_of + timedelta(days=1),
                Nature.EXPECTED,
                total,
                "EUR",
                period_end=inputs.as_of + timedelta(days=7),
                granularity="WEEK",
                lineage=(Source("ASSUMPTION", "flat", note="no flows yet"),),
            )
        )
        values.append(
            Value(
                "cash.ratio",
                inputs.as_of,
                Nature.ACTUAL,
                None if not moved else total / moved,
                "ratio",
                nm_reason="" if moved else "denominator zero",
            )
        )
        return Output(tuple(values), {"total_is_sum": mode != "invalid"})


ENGINE = register_engine(CashEngine())


@pytest.fixture
def cb(rb: dict[str, Any]) -> dict[str, Any]:
    rb["ctx"] = tenancy.enter_workspace(rb["owner"], rb["ws"]["slug"])
    rb["entity_id"] = UUID(rb["entity"]["id"])
    rb["bank"] = rb["accounts"]["1300"]["id"]
    rb["runs"] = f"{rb['base']}/calc-runs"
    return rb


def run(cb: dict[str, Any], as_of: str = "2026-03-31", **refs: Any) -> CalcRun:
    with transaction.atomic():
        ctx = tenancy.enter_workspace(cb["owner"], cb["ws"]["slug"])
        return execute(
            ctx,
            cb["entity_id"],
            "TEST_CASH",
            as_of=date.fromisoformat(as_of),
            refs={"accounts": [cb["bank"]], **refs},
        )


# --- reporting reads pinned to a watermark -------------------------------------------------------


def test_pinned_reads_return_the_actuals_as_they_were(cb: dict[str, Any]) -> None:
    ctx, entity, bank = cb["ctx"], cb["entity_id"], UUID(cb["bank"])
    post(cb, "2026-01-10", "1300", "4000", "100.00")
    post(cb, "2026-02-03", "6100", "1300", "30.00")

    def snapshot(watermark: int | None = None) -> tuple[object, ...]:
        with transaction.atomic():
            set_context(tenant_id=cb["ws"]["id"])
            return (
                actuals_monthly(
                    ctx,
                    entity,
                    date_from=date(2026, 1, 1),
                    date_to=date(2026, 12, 31),
                    watermark=watermark,
                ).facts,
                cash_daily(
                    ctx,
                    entity,
                    account_ids=[bank],
                    date_from=date(2026, 1, 1),
                    date_to=date(2026, 12, 31),
                    watermark=watermark,
                ).facts,
                opening_net(ctx, entity, before=date(2026, 3, 1), watermark=watermark)[1],
            )

    w = current_watermark(ctx, entity)
    before = snapshot()
    # Later postings: on an existing day and account, on new days, and on a new account.
    post(cb, "2026-01-10", "1300", "4000", "5.00")
    post(cb, "2026-02-20", "1300", "4000", "7.00")
    post(cb, "2026-01-15", "6200", "1300", "2.00")
    assert snapshot() != before
    assert snapshot(w) == before
    latest = current_watermark(ctx, entity)
    assert snapshot(latest) == snapshot()
    with pytest.raises(WatermarkError):
        snapshot(latest + 1)
    with pytest.raises(WatermarkError):
        snapshot(-1)
    assert snapshot(0) == ([], [], {})


# --- runs ----------------------------------------------------------------------------------------


def test_a_run_records_inputs_values_natures_and_lineage(cb: dict[str, Any]) -> None:
    post(cb, "2026-03-28", "1300", "4000", "250.00")
    r = run(cb)
    assert r.status == "VALID"
    assert r.actuals_watermark == current_watermark(cb["ctx"], cb["entity_id"])
    assert r.input_refs == {"accounts": [cb["bank"]]}
    assert len(r.input_hash) == len(r.output_hash) == 64
    assert r.invariant_results == {"total_is_sum": True}
    detail = cb["client"].get(f"{cb['runs']}/{r.id}").json()
    assert detail["status"] == "VALID"
    by_key = {v["series_key"]: v for v in detail["results"]}
    assert by_key["cash.total"]["value"] == "250"
    assert by_key["cash.total"]["nature"] == "ACTUAL"
    assert by_key["cash.next_week"]["nature"] == "EXPECTED"
    assert by_key["cash.ratio"]["value"] == "1"
    assert all(v["nature"] for v in detail["results"])  # AC-CF1
    explained = (
        cb["client"]
        .get(f"{cb['runs']}/{r.id}/results/{by_key[f'cash.{cb["bank"]}']['id']}/explain")
        .json()
    )
    assert explained["lineage"] == [
        {"input_kind": "ACTUAL", "input_ref": f"account:{cb['bank']}", "amount": "250", "note": ""}
    ]
    total = cb["client"].get(f"{cb['runs']}/{r.id}/results/{by_key['cash.total']['id']}/explain")
    assert [x["input_kind"] for x in total.json()["lineage"]] == ["RESULT"]
    listed = cb["client"].get(cb["runs"], {"kind": "TEST_CASH"}).json()
    assert [x["id"] for x in listed] == [str(r.id)]
    assert cb["client"].get(f"{cb['runs']}/{uuid4()}").status_code == 404
    missing = cb["client"].get(f"{cb['runs']}/{r.id}/results/{uuid4()}/explain")
    assert missing.status_code == 404


def test_not_meaningful_values_have_a_reason(cb: dict[str, Any]) -> None:
    r = run(cb)  # no postings: the week's movement is zero
    detail = cb["client"].get(f"{cb['runs']}/{r.id}").json()
    ratio = next(v for v in detail["results"] if v["series_key"] == "cash.ratio")
    assert ratio["value"] is None
    assert ratio["nm_reason"] == "denominator zero"


def test_reruns_reproduce_after_new_postings(cb: dict[str, Any]) -> None:
    """AC-CF3: the watermark is pinned, so unrelated later postings change nothing."""
    post(cb, "2026-03-10", "1300", "4000", "80.00")
    first = run(cb)
    post(cb, "2026-03-11", "1300", "4000", "1.00")  # dated before the as-of date
    reproduced = cb["client"].post_json(f"{cb['runs']}/{first.id}/reproduce", {}).json()
    assert reproduced == {
        "run_id": str(first.id),
        "reproduced": True,
        "stored_intact": True,
        "output_hash": first.output_hash,
        "recomputed_hash": first.output_hash,
        "reason": "",
    }
    second = run(cb)
    assert second.output_hash != first.output_hash
    assert second.input_hash != first.input_hash
    again = run(cb, as_of="2026-03-31")
    assert again.output_hash == second.output_hash  # same inputs, same output
    assert again.input_hash == second.input_hash


def test_reproduce_reports_an_engine_change(
    cb: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    r = run(cb)
    monkeypatch.setattr(ENGINE, "version", "2")
    result = cb["client"].post_json(f"{cb['runs']}/{r.id}/reproduce", {}).json()
    assert result["reproduced"] is False
    assert result["reason"] == "the engine changed from 1 to 2"


def test_reproduce_detects_a_changed_output(
    cb: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    r = run(cb)
    original = ENGINE.compute

    def drifted(inputs: RunInputs, data: dict[str, Any]) -> Output:
        out = original(inputs, data)
        return replace(out, values=out.values[:-1])

    monkeypatch.setattr(ENGINE, "compute", drifted)
    result = cb["client"].post_json(f"{cb['runs']}/{r.id}/reproduce", {}).json()
    assert result["reproduced"] is False
    assert result["reason"] == "the output differs"
    assert result["stored_intact"] is True


def test_stored_values_hash_to_the_output_hash(cb: dict[str, Any]) -> None:
    post(cb, "2026-03-28", "1300", "4000", "33.33")
    r = run(cb)
    with transaction.atomic():
        set_context(tenant_id=cb["ws"]["id"])
        assert calc.stored_output(r).digest() == r.output_hash


def test_failed_invalid_and_refused_runs(cb: dict[str, Any]) -> None:
    crashed = run(cb, mode="crash")
    assert crashed.status == "FAILED"
    assert crashed.error == "RuntimeError: engine bug"
    assert crashed.output_hash == ""
    with transaction.atomic():
        set_context(tenant_id=cb["ws"]["id"])
        assert not CalcResult.objects.filter(run=crashed).exists()
    floated = run(cb, mode="float")
    assert floated.status == "FAILED"
    assert "EngineOutputError" in floated.error
    invalid = run(cb, mode="invalid")
    assert invalid.status == "INVALID"
    assert invalid.invariant_results == {"total_is_sum": False}
    with pytest.raises(ValidationFailedError, match="Pick a bank account"):
        run(cb, mode="user_error")  # a user error is not a run
    with pytest.raises(ValidationFailedError, match="invalid"):
        run(cb, threshold=1.5)  # floats never enter the inputs
    with transaction.atomic():
        set_context(tenant_id=cb["ws"]["id"])
        assert CalcRun.objects.count() == 3
    assert cb["client"].post_json(f"{cb['runs']}/{crashed.id}/reproduce", {}).status_code == 409
    refused = cb["client"].post_json(f"{cb['runs']}/{invalid.id}/publish", {})
    assert refused.status_code == 409


def test_engine_output_is_checked() -> None:
    day = date(2026, 1, 1)
    good = Value("k", day, Nature.ACTUAL, Decimal("1"), "EUR")
    bad = [
        replace(good, nature="ACTUAL"),  # type: ignore[arg-type]
        replace(good, series_key=""),
        replace(good, unit=""),
        replace(good, granularity="HOUR"),
        replace(good, period_end=day - timedelta(days=1)),
        replace(good, value=None),
        replace(good, nm_reason="also a reason"),
        replace(good, value=Decimal("1E-29")),
        replace(good, value=Decimal("1E+22")),
        replace(good, value=Decimal("Infinity")),
        replace(good, lineage=(Source("GUESS", "x"),)),
        replace(good, lineage=(Source("ACTUAL", "x", 1),)),  # type: ignore[arg-type]
    ]
    calc._check(Output((good, replace(good, value=Decimal("1E-28")))))
    for value in bad:
        with pytest.raises(calc.EngineOutputError):
            calc._check(Output((value,)))
    with pytest.raises(calc.EngineOutputError):
        calc._check(Output((good,), {"x": "yes"}))  # type: ignore[dict-item]
    with pytest.raises(calc.EngineOutputError):
        calc._check("nothing")  # type: ignore[arg-type]


def test_engines_are_registered_once() -> None:
    assert register_engine(ENGINE) is ENGINE
    with pytest.raises(ValueError, match="already registered"):
        register_engine(CashEngine())
    with pytest.raises(Exception, match="No calculation engine"):
        calc.engine_for("NOPE")


# --- lifecycle and immutability -------------------------------------------------------------------


def test_publish_and_stale(cb: dict[str, Any]) -> None:
    r = run(cb)
    published = cb["client"].post_json(f"{cb['runs']}/{r.id}/publish", {})
    assert published.status_code == 200
    assert published.json()["is_published"] is True
    assert cb["client"].post_json(f"{cb['runs']}/{r.id}/publish", {}).status_code == 200
    other = run(cb)
    with transaction.atomic():
        set_context(tenant_id=cb["ws"]["id"])
        assert mark_stale(cb["entity_id"], ["OTHER"]) == 0
        assert mark_stale(cb["entity_id"]) == 2
        assert mark_stale(cb["entity_id"]) == 0
    stale = cb["client"].post_json(f"{cb['runs']}/{other.id}/publish", {})
    assert stale.status_code == 409
    assert "Run it again" in stale.json()["detail"]


def _sql(cb: dict[str, Any], statement: str, params: list[Any]) -> None:
    with transaction.atomic():
        set_context(tenant_id=cb["ws"]["id"])
        with connection.cursor() as cursor:
            cursor.execute(statement, params)
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_runs_and_results_are_immutable(cb: dict[str, Any]) -> None:
    """As the runtime role, directly in SQL (doc 12 "Immutability")."""
    r = run(cb)
    with transaction.atomic():
        set_context(tenant_id=cb["ws"]["id"])
        result = CalcResult.objects.filter(run=r).first()
        assert result is not None
        lineage = CalcLineage.objects.filter(result__run=r).first()
        assert lineage is not None
    refused = [
        (
            "UPDATE metrics_calc_run SET output_hash = repeat('0', 64) WHERE id = %s",
            [r.id],
            "finished calculation run is immutable",
        ),
        (
            "UPDATE metrics_calc_run SET status = 'RUNNING' WHERE id = %s",
            [r.id],
            "finished calculation run is immutable",
        ),
        (
            "UPDATE metrics_calc_run SET is_published = true, status = 'INVALID' WHERE id = %s",
            [r.id],
            "finished calculation run is immutable",
        ),
        ("DELETE FROM metrics_calc_run WHERE id = %s", [r.id], "cannot be deleted"),
        ("UPDATE metrics_calc_result SET value = 1 WHERE id = %s", [result.id], "immutable"),
        ("DELETE FROM metrics_calc_result WHERE id = %s", [result.id], "immutable"),
        (
            "UPDATE metrics_calc_lineage SET input_ref = 'x' WHERE id = %s",
            [lineage.id],
            "immutable",
        ),
        (
            "INSERT INTO metrics_calc_result (id, tenant_id, created_at, run_id, seq, series_key,"
            " dimensions, period_start, period_end, granularity, nature, value, unit, nm_reason)"
            " VALUES (gen_random_uuid(), %s, now(), %s, 99, 'k', '[]', '2026-01-01', '2026-01-01',"
            " 'POINT', 'ACTUAL', 1, 'EUR', '')",
            [cb["ws"]["id"], r.id],
            "only while",
        ),
    ]
    for statement, params, error in refused:
        with pytest.raises(DatabaseError, match=error):
            _sql(cb, statement, params)
    _sql(cb, "UPDATE metrics_calc_run SET stale = true WHERE id = %s", [r.id])
    with pytest.raises(DatabaseError, match="immutable"):
        _sql(cb, "UPDATE metrics_calc_run SET stale = false WHERE id = %s", [r.id])


def test_results_need_a_nature_and_runs_must_finish(cb: dict[str, Any]) -> None:
    r = run(cb)
    insert_run = (
        "INSERT INTO metrics_calc_run (id, tenant_id, created_at, legal_entity_id, kind,"
        " engine_version, actuals_watermark, as_of_date, input_refs, input_hash, output_hash,"
        " status, invariant_results, error, stale, is_published, trigger)"
        " VALUES (%s, %s, now(), %s, 'K', '1', 0, '2026-01-01', '{}', repeat('a', 64), '',"
        " %s, '{}', '', false, false, 'USER')"
    )
    with pytest.raises(DatabaseError, match="starts RUNNING"):
        _sql(cb, insert_run, [uuid4(), cb["ws"]["id"], cb["entity_id"], "VALID"])
    with pytest.raises(DatabaseError, match="finished in the transaction"):
        _sql(cb, insert_run, [uuid4(), cb["ws"]["id"], cb["entity_id"], "RUNNING"])
    insert_result = (
        "INSERT INTO metrics_calc_result (id, tenant_id, created_at, run_id, seq, series_key,"
        " dimensions, period_start, period_end, granularity, nature, value, unit, nm_reason)"
        " VALUES (gen_random_uuid(), %s, now(), %s, 0, 'k', '[]', '2026-01-01', '2026-01-01',"
        " 'POINT', %s, 1, 'EUR', '')"
    )
    for nature, error in (("GUESS", "metrics_result_nature_known"), (None, "null value")):
        running = uuid4()
        with transaction.atomic():
            set_context(tenant_id=cb["ws"]["id"])
            with connection.cursor() as cursor:
                cursor.execute(insert_run, [running, cb["ws"]["id"], cb["entity_id"], "RUNNING"])
                with pytest.raises(DatabaseError, match=error):
                    cursor.execute(insert_result, [cb["ws"]["id"], running, nature])
                transaction.set_rollback(True)
    del r


# --- permissions and isolation --------------------------------------------------------------------


def test_permissions(cb: dict[str, Any], make_user: Make, api_client: Make) -> None:
    r = run(cb)
    viewer = join(
        cb["client"], cb["ws"]["slug"], make_user("ro@example.test"), api_client, "read_only"
    )
    assert viewer.get(f"{cb['runs']}/{r.id}").status_code == 200
    assert viewer.post_json(f"{cb['runs']}/{r.id}/reproduce", {}).status_code == 403
    assert viewer.post_json(f"{cb['runs']}/{r.id}/publish", {}).status_code == 403
    preparer = join(
        cb["client"], cb["ws"]["slug"], make_user("acc@example.test"), api_client, "accountant"
    )
    assert preparer.post_json(f"{cb['runs']}/{r.id}/reproduce", {}).status_code == 200
    assert preparer.post_json(f"{cb['runs']}/{r.id}/publish", {}).status_code == 403


def test_other_workspaces_never_see_runs(
    cb: dict[str, Any], make_user: Make, api_client: Make, make_workspace: Make
) -> None:
    r = run(cb)
    stranger = make_user("stranger@example.test")
    ws = make_workspace(stranger, name="Other Ltd")
    client = api_client(stranger)
    entity = client.get(f"/api/w/{ws['slug']}/entities").json()[0]
    assert (
        client.get(f"/api/w/{ws['slug']}/entities/{entity['id']}/calc-runs/{r.id}").status_code
        == 404
    )
    assert (
        client.get(f"/api/w/{ws['slug']}/entities/{cb['entity']['id']}/calc-runs").status_code
        == 404
    )
    with transaction.atomic():
        set_context(tenant_id=ws["id"])
        assert not CalcRun.objects.exists()
        assert not CalcResult.objects.exists()


def test_reproduce_reports_tampered_inputs_or_values(
    cb: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The triggers stop the runtime role from changing a run; these checks catch the rest
    (e.g. a change made with owner rights)."""
    r = run(cb)
    url = f"{cb['runs']}/{r.id}/reproduce"
    with monkeypatch.context() as m:
        m.setattr(calc, "stored_output", lambda run: Output(()))
        changed = cb["client"].post_json(url, {}).json()
    assert changed["reproduced"] is False
    assert changed["stored_intact"] is False
    assert changed["reason"] == "the stored values no longer match the output hash"
    with monkeypatch.context() as m:
        m.setattr(RunInputs, "digest", lambda self: "0" * 64)
        inputs = cb["client"].post_json(url, {}).json()
    assert inputs["reason"] == "the stored inputs no longer match their hash"


def test_run_references_are_limited(cb: dict[str, Any]) -> None:
    with pytest.raises(ValidationFailedError, match="too large"):
        run(cb, notes="x" * (calc.MAX_REFS_CHARS + 1))
