"""Budgets: creation, draft lines, the approval lifecycle and revisions (M4-1, AC-BU1).

Lifecycle (doc 10 §7): DRAFT → SUBMITTED → APPROVED → LOCKED, and SUPERSEDED.
- A preparer (``budget.edit``) creates a budget (version 1, a draft), saves its lines and submits.
- An approver (``budget.approve``) approves or returns it to draft with a comment. With
  segregation of duties (on by default, per entity), the person who submitted cannot approve; the
  database refuses it as well.
- Approving a revision supersedes the previous approved (or locked) version in the same
  transaction, so there is exactly one current budget. The first version ever approved stays
  reportable as the original budget.
- A revision copies the current version into a new draft, with a reason.

Content is fixed from submission onwards. Submission stores a hash of the lines, and approval
checks it again, so what was approved is exactly what was submitted.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Max, Prefetch
from django.utils import timezone

from fcp.core.errors import ConflictError, NotFoundError, ValidationFailedError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.calendar.api import add_months, month_start
from fcp.modules.metrics.api import DEFAULT_TAXONOMY, TaxonomyLine, canonical_digest
from fcp.modules.reporting.api import accounts, dimension_values, fiscal_years
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from .models import (
    Budget,
    BudgetAmount,
    BudgetEvent,
    BudgetLine,
    BudgetSettings,
    BudgetVersion,
)

READ, EDIT, APPROVE = "budget.read", "budget.edit", "budget.approve"
SETTINGS = "budget.settings.manage"
MAX_LINES = 5000
MAX_AMOUNT = Decimal("1e15")
CENT = Decimal("0.01")
Status = BudgetVersion.Status
OPEN = (Status.DRAFT, Status.SUBMITTED)
CURRENT = (Status.APPROVED, Status.LOCKED)
DIMENSION_KINDS = {
    Budget.Kind.DEPARTMENTAL: {"DEPARTMENT", "COST_CENTRE"},
    Budget.Kind.PROJECT: {"PROJECT"},
}


class SegregationOfDutiesError(ConflictError):
    code = "budgeting.segregation_of_duties"


class LifecycleError(ConflictError):
    code = "budgeting.lifecycle"


def _invalid(field_name: str, message: str) -> ValidationFailedError:
    return ValidationFailedError(message, field_errors={field_name: [message]})


def _audit(
    ctx: WorkspaceContext,
    entity_id: UUID,
    subject_type: str,
    subject_id: UUID,
    action: str,
    changes: dict[str, Any],
) -> None:
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action=action,
        subject_type=subject_type,
        subject_id=subject_id,
        entity_id=entity_id,
        changes=changes,
    )


def _event(ctx: WorkspaceContext, version: BudgetVersion, action: str, comment: str = "") -> None:
    last = version.events.aggregate(m=Max("seq"))["m"] or 0
    BudgetEvent.objects.create(
        tenant_id=ctx.tenant.id,
        legal_entity_id=version.legal_entity_id,
        version=version,
        seq=last + 1,
        action=action,
        actor_id=ctx.user.id,
        comment=comment[:500],
    )


def fiscal_months(start: date, end: date) -> list[date]:
    """First day of every month the fiscal year touches, in order."""
    months, month = [], month_start(start)
    while month <= end:
        months.append(month)
        month = add_months(month, 1)
    return months


# --- settings -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Settings:
    sod_required: bool


def get_settings(ctx: WorkspaceContext, entity_id: UUID) -> Settings:
    entity = get_entity(ctx, entity_id, READ)
    row = BudgetSettings.objects.filter(legal_entity=entity).first()
    return Settings(sod_required=row.sod_required if row else True)


@transaction.atomic
def set_settings(ctx: WorkspaceContext, entity_id: UUID, *, sod_required: bool) -> Settings:
    entity = get_entity(ctx, entity_id, SETTINGS)
    before = get_settings(ctx, entity_id)
    BudgetSettings.objects.update_or_create(
        legal_entity=entity,
        defaults={
            "tenant_id": ctx.tenant.id,
            "sod_required": sod_required,
            "updated_by_id": ctx.user.id,
        },
    )
    if before.sod_required != sod_required:
        _audit(
            ctx,
            entity.id,
            "budget_settings",
            entity.id,
            "budgeting.settings.changed",
            {"sod_required": [before.sod_required, sod_required]},
        )
    return Settings(sod_required)


# --- budgets --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BudgetInput:
    name: str
    fiscal_year_id: UUID
    kind: str = Budget.Kind.ANNUAL
    dimension_value_id: UUID | None = None


@dataclass(frozen=True)
class BudgetView:
    budget: Budget
    versions: list[BudgetVersion]

    @property
    def original(self) -> BudgetVersion | None:
        approved = [v for v in self.versions if v.approved_at is not None]
        return min(approved, key=lambda v: v.number) if approved else None

    @property
    def current(self) -> BudgetVersion | None:
        return next((v for v in self.versions if v.status in CURRENT), None)

    @property
    def open(self) -> BudgetVersion | None:
        return next((v for v in self.versions if v.status in OPEN), None)


def _view(budget: Budget) -> BudgetView:
    return BudgetView(budget, sorted(budget.versions.all(), key=lambda v: v.number))


@transaction.atomic
def create_budget(ctx: WorkspaceContext, entity_id: UUID, data: BudgetInput) -> BudgetView:
    entity = get_entity(ctx, entity_id, EDIT)
    name = data.name.strip()
    if not name or len(name) > 120:
        raise _invalid("name", "Give the budget a name of up to 120 characters.")
    year = next((y for y in fiscal_years(ctx, entity.id) if y.id == data.fiscal_year_id), None)
    if year is None:
        raise _invalid("fiscal_year_id", "Fiscal year not found in this legal entity.")
    if data.kind not in Budget.Kind.values:
        raise _invalid("kind", "Choose annual, departmental or project.")
    if data.kind == Budget.Kind.ANNUAL:
        if data.dimension_value_id is not None:
            raise _invalid("dimension_value_id", "An annual budget covers the whole entity.")
    else:
        value = next(
            (v for v in dimension_values(ctx, entity.id) if v.id == data.dimension_value_id), None
        )
        if value is None or value.dimension_kind not in DIMENSION_KINDS[Budget.Kind(data.kind)]:
            kinds = " or ".join(
                sorted(k.lower().replace("_", " ") for k in DIMENSION_KINDS[Budget.Kind(data.kind)])
            )
            raise _invalid("dimension_value_id", f"Choose a {kinds} for this budget.")
    try:
        with transaction.atomic():
            budget = Budget.objects.create(
                tenant_id=ctx.tenant.id,
                legal_entity=entity,
                fiscal_year_id=year.id,
                fiscal_year_start=year.start_date,
                fiscal_year_end=year.end_date,
                name=name,
                kind=data.kind,
                dimension_value_id=data.dimension_value_id,
                created_by_id=ctx.user.id,
            )
    except IntegrityError as exc:
        raise ConflictError("A budget with this name already exists for this fiscal year.") from exc
    version = BudgetVersion.objects.create(
        tenant_id=ctx.tenant.id,
        legal_entity=entity,
        budget=budget,
        number=1,
        created_by_id=ctx.user.id,
    )
    _event(ctx, version, BudgetEvent.Action.CREATED)
    _audit(
        ctx,
        entity.id,
        "budget",
        budget.id,
        "budgeting.budget.created",
        {
            "name": name,
            "fiscal_year": year.name,
            "kind": data.kind,
            "dimension_value_id": str(data.dimension_value_id or ""),
        },
    )
    return BudgetView(budget, [version])


def list_budgets(
    ctx: WorkspaceContext, entity_id: UUID, fiscal_year_id: UUID | None = None
) -> list[BudgetView]:
    entity = get_entity(ctx, entity_id, READ)
    budgets = Budget.objects.filter(legal_entity=entity).prefetch_related("versions")
    if fiscal_year_id is not None:
        budgets = budgets.filter(fiscal_year_id=fiscal_year_id)
    return [_view(b) for b in budgets.order_by("-fiscal_year_start", "name")]


def get_budget(ctx: WorkspaceContext, entity_id: UUID, budget_id: UUID) -> BudgetView:
    entity = get_entity(ctx, entity_id, READ)
    budget = (
        Budget.objects.filter(legal_entity=entity, id=budget_id)
        .prefetch_related("versions")
        .first()
    )
    if budget is None:
        raise NotFoundError("Budget not found.")
    return _view(budget)


# --- versions and lines ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LineInput:
    taxonomy_code: str | None = None
    account_id: UUID | None = None
    dimension_value_id: UUID | None = None
    amounts: dict[date, Decimal] = field(default_factory=dict)
    method: str = BudgetLine.Method.MANUAL
    method_params: dict[str, Any] = field(default_factory=dict)
    note: str = ""


@dataclass(frozen=True)
class VersionView:
    version: BudgetVersion
    budget: Budget
    months: list[date]
    lines: list[BudgetLine]
    amounts: dict[UUID, dict[date, Decimal]]

    def line_amounts(self, line: BudgetLine) -> list[Decimal]:
        found = self.amounts.get(line.id, {})
        return [found.get(m, Decimal(0)) for m in self.months]


def _version(entity_id: UUID, version_id: UUID, *, lock: bool = False) -> BudgetVersion:
    rows = BudgetVersion.objects.select_related("budget").filter(
        legal_entity_id=entity_id, id=version_id
    )
    if lock:
        rows = rows.select_for_update(of=("self",))
    version: BudgetVersion | None = rows.first()
    if version is None:
        raise NotFoundError("Budget version not found.")
    return version


def get_version(ctx: WorkspaceContext, entity_id: UUID, version_id: UUID) -> VersionView:
    entity = get_entity(ctx, entity_id, READ)
    version = _version(entity.id, version_id)
    return _load(version)


def _load(version: BudgetVersion) -> VersionView:
    lines = list(
        version.lines.select_related("taxonomy_line")
        .prefetch_related(Prefetch("amounts", queryset=BudgetAmount.objects.order_by("month")))
        .order_by("seq")
    )
    amounts = {ln.id: {a.month: a.amount for a in ln.amounts.all()} for ln in lines}
    budget = version.budget
    return VersionView(
        version,
        budget,
        fiscal_months(budget.fiscal_year_start, budget.fiscal_year_end),
        lines,
        amounts,
    )


def _require(version: BudgetVersion, *allowed: str) -> None:
    if version.status not in allowed:
        names = " or ".join(s.lower() for s in allowed)
        raise LifecycleError(
            f"Version {version.number} is {version.status.lower()}; it must be {names} for this."
        )


def _amount(value: Decimal, where: str) -> Decimal:
    if not value.is_finite() or value != value.quantize(CENT) or abs(value) >= MAX_AMOUNT:
        raise _invalid(where, "Amounts have at most 2 decimals and fewer than 16 digits.")
    return value.quantize(CENT)


def _validated(  # noqa: PLR0912 (one check per rule)
    ctx: WorkspaceContext, budget: Budget, months: list[date], lines: list[LineInput]
) -> list[tuple[LineInput, TaxonomyLine | None, UUID | None]]:
    """Check every line; return it with its taxonomy line and effective dimension value."""
    if len(lines) > MAX_LINES:
        raise _invalid("lines", f"A version has at most {MAX_LINES} lines.")
    taxonomy = {ln.code: ln for ln in TaxonomyLine.objects.filter(version_id=DEFAULT_TAXONOMY)}
    postable = {
        a.id
        for a in accounts(ctx, budget.legal_entity_id)
        if a.is_postable and a.status == "ACTIVE"
    }
    values = {v.id: v for v in dimension_values(ctx, budget.legal_entity_id)}
    allowed_months = set(months)
    seen: set[tuple[str, UUID | None]] = set()
    out = []
    for i, line in enumerate(lines):
        where = f"lines[{i}]"
        if (line.taxonomy_code is None) == (line.account_id is None):
            raise _invalid(where, "Each line is either a taxonomy line or an account.")
        tax_line = None
        if line.taxonomy_code is not None:
            tax_line = taxonomy.get(line.taxonomy_code)
            if tax_line is None:
                raise _invalid(where, f"Unknown taxonomy line {line.taxonomy_code[:40]!r}.")
        elif line.account_id not in postable:
            raise _invalid(where, "Choose an active postable account of this legal entity.")
        dimension = line.dimension_value_id
        if budget.dimension_value_id is not None:
            if dimension not in (None, budget.dimension_value_id):
                raise _invalid(
                    where, "Lines of this budget belong to its own department or project."
                )
            dimension = budget.dimension_value_id
        elif dimension is not None and (
            dimension not in values or values[dimension].status != "ACTIVE"
        ):
            raise _invalid(where, "Dimension value not found or inactive.")
        key = (tax_line.code if tax_line else str(line.account_id), dimension)
        if key in seen:
            raise _invalid(where, "This line appears twice; combine the amounts.")
        seen.add(key)
        if line.method not in BudgetLine.Method.values:
            raise _invalid(where, "Unknown phasing method.")
        if len(line.note) > 300:
            raise _invalid(where, "Notes have at most 300 characters.")
        for month, value in line.amounts.items():
            if month not in allowed_months:
                raise _invalid(where, f"{month.isoformat()} is not a month of this fiscal year.")
            _amount(value, where)
        out.append((line, tax_line, dimension))
    return out


def _content(view: VersionView) -> list[dict[str, Any]]:
    return [
        {
            "subject": ln.taxonomy_line.code if ln.taxonomy_line else str(ln.account_id),
            "dimension": ln.dimension_value_id,
            "method": ln.method,
            "params": ln.method_params,
            "note": ln.note,
            "amounts": view.line_amounts(ln),
        }
        for ln in view.lines
    ]


def content_hash(view: VersionView) -> str:
    return canonical_digest({"months": view.months, "lines": _content(view)})


@transaction.atomic
def save_lines(
    ctx: WorkspaceContext, entity_id: UUID, version_id: UUID, lines: list[LineInput]
) -> VersionView:
    """Replace all lines of a draft version (months not given are 0)."""
    entity = get_entity(ctx, entity_id, EDIT)
    version = _version(entity.id, version_id, lock=True)
    _require(version, Status.DRAFT)
    budget = version.budget
    months = fiscal_months(budget.fiscal_year_start, budget.fiscal_year_end)
    checked = _validated(ctx, budget, months, lines)
    BudgetAmount.objects.filter(line__version=version).delete()
    version.lines.all().delete()
    common = {"tenant_id": ctx.tenant.id, "legal_entity_id": entity.id}
    created = BudgetLine.objects.bulk_create(
        [
            BudgetLine(
                **common,
                version=version,
                seq=i + 1,
                taxonomy_line=tax_line,
                account_id=line.account_id,
                dimension_value_id=dimension,
                method=line.method,
                method_params=line.method_params,
                note=line.note.strip(),
            )
            for i, (line, tax_line, dimension) in enumerate(checked)
        ]
    )
    BudgetAmount.objects.bulk_create(
        [
            BudgetAmount(**common, line=row, month=m, amount=line.amounts.get(m, Decimal(0)))
            for row, (line, _, _) in zip(created, checked, strict=True)
            for m in months
        ]
    )
    _event(ctx, version, BudgetEvent.Action.LINES_SAVED, f"{len(created)} lines")
    _audit(
        ctx,
        entity.id,
        "budget_version",
        version.id,
        "budgeting.lines.saved",
        {"budget_id": str(budget.id), "version": version.number, "lines": len(created)},
    )
    return _load(version)


@transaction.atomic
def submit(ctx: WorkspaceContext, entity_id: UUID, version_id: UUID) -> BudgetVersion:
    entity = get_entity(ctx, entity_id, EDIT)
    version = _version(entity.id, version_id, lock=True)
    _require(version, Status.DRAFT)
    view = _load(version)
    if not view.lines:
        raise LifecycleError("Add at least one line before submitting.")
    version.status = Status.SUBMITTED
    version.content_hash = content_hash(view)
    version.submitted_by_id = ctx.user.id
    version.submitted_at = timezone.now()
    version.save(update_fields=["status", "content_hash", "submitted_by", "submitted_at"])
    _event(ctx, version, BudgetEvent.Action.SUBMITTED)
    _audit(
        ctx,
        entity.id,
        "budget_version",
        version.id,
        "budgeting.version.submitted",
        {"version": version.number, "content_hash": version.content_hash},
    )
    return version


@transaction.atomic
def return_to_draft(
    ctx: WorkspaceContext, entity_id: UUID, version_id: UUID, comment: str
) -> BudgetVersion:
    entity = get_entity(ctx, entity_id, APPROVE)
    comment = comment.strip()
    if not comment:
        raise _invalid("comment", "Say what needs to change.")
    version = _version(entity.id, version_id, lock=True)
    _require(version, Status.SUBMITTED)
    version.status = Status.DRAFT
    version.content_hash = ""
    version.submitted_by = None
    version.submitted_at = None
    version.save(update_fields=["status", "content_hash", "submitted_by", "submitted_at"])
    _event(ctx, version, BudgetEvent.Action.RETURNED, comment)
    _audit(
        ctx,
        entity.id,
        "budget_version",
        version.id,
        "budgeting.version.returned",
        {"version": version.number, "comment": comment[:500]},
    )
    return version


@transaction.atomic
def approve(
    ctx: WorkspaceContext, entity_id: UUID, version_id: UUID, comment: str = ""
) -> BudgetVersion:
    entity = get_entity(ctx, entity_id, APPROVE)
    version = _version(entity.id, version_id, lock=True)
    _require(version, Status.SUBMITTED)
    sod = get_settings(ctx, entity.id).sod_required
    if sod and version.submitted_by_id == ctx.user.id:
        raise SegregationOfDutiesError(
            "You submitted this version, so someone else must approve it (segregation of duties)."
        )
    if content_hash(_load(version)) != version.content_hash:  # pragma: no cover (DB-guarded)
        raise LifecycleError("The lines changed after submission; submit again.")
    now = timezone.now()
    previous = (
        BudgetVersion.objects.select_for_update()
        .filter(budget_id=version.budget_id, status__in=CURRENT)
        .first()
    )
    if previous is not None:
        previous.status = Status.SUPERSEDED
        previous.superseded_at = now
        previous.save(update_fields=["status", "superseded_at"])
        _event(ctx, previous, BudgetEvent.Action.SUPERSEDED, f"by version {version.number}")
    version.status = Status.APPROVED
    version.approved_by_id = ctx.user.id
    version.approved_at = now
    version.sod_applied = sod
    version.save(update_fields=["status", "approved_by", "approved_at", "sod_applied"])
    _event(ctx, version, BudgetEvent.Action.APPROVED, comment.strip())
    _audit(
        ctx,
        entity.id,
        "budget_version",
        version.id,
        "budgeting.version.approved",
        {
            "version": version.number,
            "content_hash": version.content_hash,
            "sod_applied": sod,
            "superseded": str(previous.id) if previous else "",
        },
    )
    return version


@transaction.atomic
def lock(ctx: WorkspaceContext, entity_id: UUID, version_id: UUID) -> BudgetVersion:
    entity = get_entity(ctx, entity_id, APPROVE)
    version = _version(entity.id, version_id, lock=True)
    _require(version, Status.APPROVED)
    version.status = Status.LOCKED
    version.locked_by_id = ctx.user.id
    version.locked_at = timezone.now()
    version.save(update_fields=["status", "locked_by", "locked_at"])
    _event(ctx, version, BudgetEvent.Action.LOCKED)
    _audit(
        ctx,
        entity.id,
        "budget_version",
        version.id,
        "budgeting.version.locked",
        {"version": version.number},
    )
    return version


@transaction.atomic
def revise(ctx: WorkspaceContext, entity_id: UUID, version_id: UUID, reason: str) -> VersionView:
    """Start a revision of the current version: a new draft with the same lines."""
    entity = get_entity(ctx, entity_id, EDIT)
    reason = reason.strip()
    if not reason or len(reason) > 500:
        raise _invalid("reason", "Give the reason for the revision (up to 500 characters).")
    source = _version(entity.id, version_id, lock=True)
    _require(source, *CURRENT)
    Budget.objects.select_for_update().filter(id=source.budget_id).first()
    if BudgetVersion.objects.filter(budget_id=source.budget_id, status__in=OPEN).exists():
        raise LifecycleError("This budget already has a version in progress.")
    number = (
        BudgetVersion.objects.filter(budget_id=source.budget_id).aggregate(m=Max("number"))["m"]
        or 0
    ) + 1
    version = BudgetVersion.objects.create(
        tenant_id=ctx.tenant.id,
        legal_entity=entity,
        budget_id=source.budget_id,
        number=number,
        supersedes=source,
        reason=reason,
        created_by_id=ctx.user.id,
    )
    old = _load(source)
    common = {"tenant_id": ctx.tenant.id, "legal_entity_id": entity.id}
    copies = BudgetLine.objects.bulk_create(
        [
            BudgetLine(
                **common,
                version=version,
                seq=ln.seq,
                taxonomy_line_id=ln.taxonomy_line_id,
                account_id=ln.account_id,
                dimension_value_id=ln.dimension_value_id,
                method=ln.method,
                method_params=ln.method_params,
                note=ln.note,
            )
            for ln in old.lines
        ]
    )
    BudgetAmount.objects.bulk_create(
        [
            BudgetAmount(**common, line=copy, month=m, amount=a)
            for copy, ln in zip(copies, old.lines, strict=True)
            for m, a in zip(old.months, old.line_amounts(ln), strict=True)
        ]
    )
    _event(ctx, version, BudgetEvent.Action.REVISION_STARTED, reason)
    _audit(
        ctx,
        entity.id,
        "budget_version",
        version.id,
        "budgeting.revision.started",
        {
            "budget_id": str(source.budget_id),
            "version": number,
            "from_version": source.number,
            "reason": reason,
        },
    )
    return _load(version)


@transaction.atomic
def set_reason(
    ctx: WorkspaceContext, entity_id: UUID, version_id: UUID, reason: str
) -> BudgetVersion:
    entity = get_entity(ctx, entity_id, EDIT)
    version = _version(entity.id, version_id, lock=True)
    _require(version, Status.DRAFT)
    reason = reason.strip()
    if version.number > 1 and not reason:
        raise _invalid("reason", "A revision needs a reason.")
    if len(reason) > 500:
        raise _invalid("reason", "Up to 500 characters.")
    version.reason = reason
    version.save(update_fields=["reason"])
    return version


def events(ctx: WorkspaceContext, entity_id: UUID, budget_id: UUID) -> list[BudgetEvent]:
    """The approval trail of every version of a budget, oldest first."""
    view = get_budget(ctx, entity_id, budget_id)
    rows = (
        BudgetEvent.objects.filter(version__budget=view.budget)
        .select_related("version", "actor")
        .order_by("version__number", "seq")
    )
    return list(rows)


# --- totals ---------------------------------------------------------------------------------------


def quarters(months: list[date], amounts: list[Decimal]) -> list[Decimal]:
    """Fiscal quarter totals: months 1-3, 4-6, ...  of the fiscal year (a short year's last
    quarter may be partial). Always sums of months, never entered."""
    sums: dict[int, Decimal] = defaultdict(Decimal)
    for i, value in enumerate(amounts[: len(months)]):
        sums[i // 3] += value
    return [sums[q] for q in range((len(months) + 2) // 3)]
