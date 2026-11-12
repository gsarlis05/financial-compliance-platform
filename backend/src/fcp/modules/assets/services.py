"""Fixed-asset register and depreciation (M6-1, brief §3).

- Assets are registered per legal entity with their cost, accumulated-depreciation and expense
  accounts. Terms can be corrected until depreciation is first prepared for the asset; then they
  are locked (database trigger) and only a disposal can be recorded, once.
- **Preparing a month** creates one **draft** journal entry for the entity (Dr depreciation
  expense, Cr accumulated depreciation, one pair of lines per asset) through the ledger's public
  interface. It follows the normal approval and posting; this module never posts. A month is
  prepared once; if its draft is voided or rejected, the month can be prepared again.
- A disposal stops depreciation from its month. The gain or loss is shown; the user books the
  disposal (it involves cash and the asset's cost, which only the user knows how to settle).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from fcp.core.errors import ConflictError, NotFoundError, ValidationFailedError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.calendar.api import month_end, month_start
from fcp.modules.ledger.api import (
    Account,
    EntryInput,
    JournalEntry,
    LineInput,
    account_list,
    create_entry_draft,
)
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from .models import DepreciationRun, DepreciationRunLine, FixedAsset
from .schedule import CONVENTION, AssetTerms, ScheduleRow, book_value, disposal_result, schedule

READ, MANAGE = "assets.read", "assets.manage"
MAX_AMOUNT = Decimal("1e12")
CENT = Decimal("0.01")
ENDED = (JournalEntry.Status.VOID, JournalEntry.Status.REJECTED)

__all__ = ["CONVENTION"]


def _invalid(name: str, message: str) -> ValidationFailedError:
    return ValidationFailedError(message, field_errors={name: [message]})


def _entity(ctx: WorkspaceContext, entity_id: UUID, permission: str) -> UUID:
    return get_entity(ctx, entity_id, permission).id


def _money(raw: str | Decimal, name: str, *, allow_zero: bool = True) -> Decimal:
    try:
        value = Decimal(str(raw))
    except InvalidOperation:
        raise _invalid(name, "Enter an amount such as 1250.00.") from None
    if (not value.is_finite() or value.quantize(CENT) != value or value < 0
            or value >= MAX_AMOUNT or (value == 0 and not allow_zero)):  # fmt: skip
        raise _invalid(name, "Enter a positive amount with at most 2 decimals.")
    return value


def terms(asset: FixedAsset) -> AssetTerms:
    return AssetTerms(
        acquired_on=asset.acquired_on,
        cost=asset.cost,
        residual=asset.residual_value,
        life_months=asset.useful_life_months,
        method=asset.method,
        annual_rate=asset.annual_rate,
        disposed_on=asset.disposed_on,
    )


# --- register ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class AssetInput:
    code: str
    name: str
    category: str
    asset_account_id: UUID
    accumulated_account_id: UUID
    expense_account_id: UUID
    acquired_on: date
    cost: str
    useful_life_months: int
    residual_value: str = "0"
    method: str = FixedAsset.Method.STRAIGHT_LINE
    annual_rate: str | None = None


def _account(accounts: dict[UUID, Account], account_id: UUID, kind: str, name: str) -> None:
    found = accounts.get(account_id)
    if (found is None or not found.is_postable or found.status != Account.Status.ACTIVE
            or found.type != kind):  # fmt: skip
        what = "an asset account" if kind == "ASSET" else "an expense account"
        raise _invalid(name, f"Choose {what} of this entity that can be posted to.")


def _validated(ctx: WorkspaceContext, entity: UUID, data: AssetInput) -> dict[str, object]:
    code, name = data.code.strip(), data.name.strip()
    if not code or len(code) > 20:
        raise _invalid("code", "Give the asset a code of 1 to 20 characters.")
    if not name or len(name) > 200:
        raise _invalid("name", "Give the asset a name of 1 to 200 characters.")
    if data.category not in FixedAsset.Category.values:
        raise _invalid("category", "Choose a category.")
    if data.method not in FixedAsset.Method.values:
        raise _invalid("method", "Choose straight-line or declining balance.")
    accounts = {a.id: a for a in account_list(ctx, entity)}
    _account(accounts, data.asset_account_id, "ASSET", "asset_account_id")
    _account(accounts, data.accumulated_account_id, "ASSET", "accumulated_account_id")
    _account(accounts, data.expense_account_id, "EXPENSE", "expense_account_id")
    if data.accumulated_account_id == data.asset_account_id:
        raise _invalid("accumulated_account_id", "Use a separate accumulated-depreciation account.")
    cost = _money(data.cost, "cost", allow_zero=False)
    residual = _money(data.residual_value, "residual_value")
    if residual > cost:
        raise _invalid("residual_value", "The residual value cannot be more than the cost.")
    if not 1 <= data.useful_life_months <= 1200:
        raise _invalid("useful_life_months", "Enter a useful life of 1 to 1,200 months.")
    rate: Decimal | None = None
    if data.method == FixedAsset.Method.DECLINING_BALANCE:
        try:
            rate = Decimal(str(data.annual_rate)) / 100
        except InvalidOperation:
            rate = None
        if rate is None or not rate.is_finite() or not Decimal(0) < rate <= 2:
            raise _invalid("annual_rate", "Enter an annual rate between 0 and 200%.")
    return {
        "code": code, "name": name, "category": data.category,
        "asset_account_id": data.asset_account_id,
        "accumulated_account_id": data.accumulated_account_id,
        "expense_account_id": data.expense_account_id, "acquired_on": data.acquired_on,
        "cost": cost, "residual_value": residual, "useful_life_months": data.useful_life_months,
        "method": data.method, "annual_rate": rate,
    }  # fmt: skip


def _audit(ctx: WorkspaceContext, action: str, asset: FixedAsset, **changes: object) -> None:
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action=f"assets.asset.{action}",
        subject_type="fixed_asset",
        subject_id=asset.id,
        entity_id=asset.legal_entity_id,
        changes={"code": asset.code, **{k: str(v) for k, v in changes.items()}},
    )


@transaction.atomic
def create_asset(ctx: WorkspaceContext, entity_id: UUID, data: AssetInput) -> FixedAsset:
    entity = _entity(ctx, entity_id, MANAGE)
    fields = _validated(ctx, entity, data)
    try:
        with transaction.atomic():
            asset = FixedAsset.objects.create(
                tenant=ctx.tenant, legal_entity_id=entity, created_by=ctx.user, **fields
            )
    except IntegrityError:
        raise _invalid("code", "Another asset of this entity has this code.") from None
    _audit(ctx, "created", asset, cost=asset.cost, acquired_on=asset.acquired_on,
           method=asset.method, life=asset.useful_life_months)  # fmt: skip
    return asset


def _asset(entity: UUID, asset_id: UUID) -> FixedAsset:
    asset = FixedAsset.objects.filter(legal_entity_id=entity, id=asset_id).first()
    if asset is None:
        raise NotFoundError("Asset not found.")
    return asset


@transaction.atomic
def correct_asset(
    ctx: WorkspaceContext, entity_id: UUID, asset_id: UUID, data: AssetInput
) -> FixedAsset:
    """Correct an asset's terms, only while no depreciation has been prepared for it."""
    entity = _entity(ctx, entity_id, MANAGE)
    asset = _asset(entity, asset_id)
    if asset.locked_at is not None:
        raise ConflictError(
            "Depreciation was prepared for this asset, so its terms are locked. Record a "
            "disposal and add the asset again with the right terms."
        )
    fields = _validated(ctx, entity, data)
    for key, value in fields.items():
        setattr(asset, key, value)
    try:
        with transaction.atomic():
            asset.save()
    except IntegrityError:
        raise _invalid("code", "Another asset of this entity has this code.") from None
    _audit(ctx, "corrected", asset, cost=asset.cost, acquired_on=asset.acquired_on,
           method=asset.method, life=asset.useful_life_months)  # fmt: skip
    return asset


@transaction.atomic
def dispose(
    ctx: WorkspaceContext, entity_id: UUID, asset_id: UUID, *, on: date, proceeds: str
) -> FixedAsset:
    entity = _entity(ctx, entity_id, MANAGE)
    asset = _asset(entity, asset_id)
    if asset.disposed_on is not None:
        raise ConflictError("The disposal of this asset is already recorded.")
    if on < asset.acquired_on:
        raise _invalid("disposed_on", "The disposal cannot be before the acquisition.")
    prepared = DepreciationRunLine.objects.filter(
        asset=asset, run__cancelled_at__isnull=True, run__month__gte=month_start(on)
    ).exists()
    if prepared:
        raise _invalid("disposed_on", "Depreciation was already prepared for this month or later.")
    asset.disposed_on, asset.disposal_proceeds = on, _money(proceeds, "proceeds")
    asset.save(update_fields=["disposed_on", "disposal_proceeds"])
    _audit(ctx, "disposed", asset, disposed_on=on, proceeds=asset.disposal_proceeds)
    return asset


@dataclass(frozen=True)
class AssetView:
    asset: FixedAsset
    accumulated: Decimal
    book_value: Decimal
    status: str  # ACTIVE | FULLY_DEPRECIATED | DISPOSED
    gain: Decimal | None  # on disposal


def _view(asset: FixedAsset, as_of: date) -> AssetView:
    t = terms(asset)
    value = book_value(t, as_of)
    held = month_start(asset.acquired_on) <= month_start(as_of)
    if asset.disposed_on is not None and asset.disposed_on <= as_of:
        status = "DISPOSED"
    elif held and value == asset.residual_value and schedule(t)[-1].month <= month_start(as_of):
        status = "FULLY_DEPRECIATED"
    else:
        status = "ACTIVE"
    gain = None
    if asset.disposed_on is not None and asset.disposal_proceeds is not None:
        gain = disposal_result(t, asset.disposal_proceeds).gain
    accumulated = asset.cost - value if held else Decimal("0.00")
    return AssetView(asset, accumulated, value, status, gain)


def assets(ctx: WorkspaceContext, entity_id: UUID, *, as_of: date) -> list[AssetView]:
    entity = _entity(ctx, entity_id, READ)
    rows = FixedAsset.objects.filter(legal_entity_id=entity).order_by("code")
    return [_view(a, as_of) for a in rows]


def asset_schedule(
    ctx: WorkspaceContext, entity_id: UUID, asset_id: UUID
) -> tuple[FixedAsset, list[ScheduleRow], dict[date, UUID]]:
    """The schedule, and for each month already prepared the draft entry it went into."""
    entity = _entity(ctx, entity_id, READ)
    asset = _asset(entity, asset_id)
    prepared = {
        line.run.month: line.run.entry_id
        for line in DepreciationRunLine.objects.filter(asset=asset, run__cancelled_at__isnull=True)
        .select_related("run")
    }  # fmt: skip
    return asset, schedule(terms(asset)), prepared


# --- prepared depreciation entries -------------------------------------------------------------


@dataclass(frozen=True)
class RunView:
    run: DepreciationRun
    entry_status: str
    entry_ref: str
    assets: int


def _entries(ids: Iterable[UUID]) -> dict[UUID, JournalEntry]:
    return {
        e.id: e for e in JournalEntry.objects.filter(id__in=list(ids)).select_related("journal")
    }


def _run_view(run: DepreciationRun, entry: JournalEntry | None) -> RunView:
    ref = f"{entry.journal.code}-{entry.entry_no}" if entry and entry.entry_no else ""
    return RunView(run, entry.status if entry else "MISSING", ref, run.lines.count())


@transaction.atomic
def prepare_month(ctx: WorkspaceContext, entity_id: UUID, month: date) -> RunView:
    """Prepare the month's depreciation as one draft journal entry (see the module text)."""
    entity = _entity(ctx, entity_id, MANAGE)
    first = month_start(month)
    current = (
        DepreciationRun.objects.select_for_update()
        .filter(legal_entity_id=entity, month=first, cancelled_at__isnull=True)
        .first()
    )
    if current is not None:
        entry = _entries([current.entry_id]).get(current.entry_id)
        if entry is not None and entry.status not in ENDED:
            ref = _run_view(current, entry).entry_ref
            where = f" as {ref}" if ref else ""
            raise ConflictError(
                f"Depreciation for {first:%m/%Y} is already prepared{where}; its entry is "
                f"{entry.status.lower()}. Void or reject that entry to prepare the month again."
            )
        current.cancelled_at = timezone.now()
        current.save(update_fields=["cancelled_at"])
    amounts: list[tuple[FixedAsset, Decimal]] = []
    for asset in FixedAsset.objects.filter(legal_entity_id=entity).order_by("code"):
        amount = next((r.depreciation for r in schedule(terms(asset)) if r.month == first),
                      Decimal("0.00"))  # fmt: skip
        if amount > 0:
            amounts.append((asset, amount))
    if not amounts:
        raise _invalid("month", f"There is nothing to depreciate in {first:%m/%Y}.")
    lines: list[LineInput] = []
    for asset, amount in amounts:
        memo = f"{asset.code} {asset.name}"[:200]
        lines.append(LineInput(asset.expense_account_id, debit=f"{amount:.2f}", memo=memo))
        lines.append(LineInput(asset.accumulated_account_id, credit=f"{amount:.2f}", memo=memo))
    total = sum((a for _, a in amounts), Decimal("0.00"))
    entry = create_entry_draft(ctx, entity, EntryInput(
        accounting_date=month_end(first),
        description=f"Depreciation {first:%m/%Y} ({len(amounts)} asset"
        f"{'' if len(amounts) == 1 else 's'}, fixed-asset register)",
        lines=lines,
    ))  # fmt: skip
    run = DepreciationRun.objects.create(
        tenant=ctx.tenant, legal_entity_id=entity, month=first, entry_id=entry.id, total=total,
        prepared_by=ctx.user,
    )  # fmt: skip
    DepreciationRunLine.objects.bulk_create(
        DepreciationRunLine(tenant=ctx.tenant, run=run, asset=asset, amount=amount)
        for asset, amount in amounts
    )
    FixedAsset.objects.filter(id__in=[a.id for a, _ in amounts], locked_at__isnull=True).update(
        locked_at=timezone.now()
    )
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action="assets.depreciation.prepared",
        subject_type="depreciation_run",
        subject_id=run.id,
        entity_id=entity,
        changes={"month": first.isoformat(), "total": f"{total:.2f}", "assets": len(amounts),
                 "entry": str(entry.id)},
    )  # fmt: skip
    return _run_view(run, entry)


def runs(ctx: WorkspaceContext, entity_id: UUID) -> list[RunView]:
    """Prepared months, newest first, with the current status of each draft entry."""
    entity = _entity(ctx, entity_id, READ)
    found = list(
        DepreciationRun.objects.filter(legal_entity_id=entity).order_by("-month", "-created_at")
    )
    entries = _entries(r.entry_id for r in found)
    return [_run_view(r, entries.get(r.entry_id)) for r in found]


# --- for projections (M6-3) ----------------------------------------------------------------------


@dataclass(frozen=True)
class MonthlyDepreciation:
    month: date
    amount: Decimal


def depreciation_plan(
    ctx: WorkspaceContext, entity_id: UUID, months: list[date]
) -> list[MonthlyDepreciation]:
    """Depreciation of the registered assets in each month, as the schedules have it."""
    entity = _entity(ctx, entity_id, READ)
    wanted = [month_start(m) for m in months]
    totals = dict.fromkeys(wanted, Decimal("0.00"))
    for asset in FixedAsset.objects.filter(legal_entity_id=entity):
        for row in schedule(terms(asset)):
            if row.month in totals:
                totals[row.month] += row.depreciation
    return [MonthlyDepreciation(m, totals[m]) for m in wanted]
