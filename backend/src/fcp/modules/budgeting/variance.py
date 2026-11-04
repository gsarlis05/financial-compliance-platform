"""Variance analysis, explanations and period reviews (M4-3, AC-BU4, AC-BU5).

- Actuals come from **posted** ledger entries only, through ``reporting`` and pinned to one ledger
  watermark per response; year-end closing entries are left out. Entries not yet posted are not
  counted, and how many there are is returned as a warning.
- Lines with a dimension value compare with the actuals of lines tagged with that value; lines
  without compare with the whole entity.
- Amounts are in each line's natural direction (income as income, costs as cost). Variance =
  subject - comparison. Whether it is favourable follows the line's direction: more revenue is
  favourable, more cost is not. The percentage is variance ÷ |comparison|, and "not meaningful"
  when the comparison is zero.
- Comparisons: actual vs budget, actual vs prior year, and current vs original budget. Views:
  month, quarter to date, year to date, and the full-year outlook (actuals to date blended with
  the budget for the remaining months, labelled BLENDED with its cut-over month).
- A variance needs an explanation when |variance| and |percentage| both reach the entity's
  thresholds (default 1,000 and 10%; a non-meaningful percentage counts as reached). A month's
  review can be completed only when every such actual-vs-budget variance for the month and the
  year to date is explained.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Max

from fcp.core.errors import ConflictError, ValidationFailedError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.calendar.api import add_months, month_end
from fcp.modules.metrics.api import current_mapping
from fcp.modules.reporting.api import (
    accounts,
    actuals_monthly,
    current_watermark,
    dimension_actuals,
    unposted_count,
)
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from . import services
from .models import Budget, BudgetLine, BudgetSettings, BudgetVersion, PeriodReview
from .models import VarianceExplanation as Explanation

ZERO = Decimal(0)
HUNDRED = Decimal(100)
View = Explanation.View
CURRENT = (BudgetVersion.Status.APPROVED, BudgetVersion.Status.LOCKED)


class Comparison(StrEnum):
    ACTUAL_VS_BUDGET = "ACTUAL_VS_BUDGET"
    ACTUAL_VS_PRIOR_YEAR = "ACTUAL_VS_PRIOR_YEAR"
    CURRENT_VS_ORIGINAL = "CURRENT_VS_ORIGINAL"


class ReviewIncompleteError(ConflictError):
    code = "budgeting.review_incomplete"


@dataclass(frozen=True)
class Thresholds:
    amount: Decimal
    percent: Decimal


@dataclass(frozen=True)
class Row:
    line_id: UUID | None
    taxonomy_code: str | None
    account_id: UUID | None
    dimension_value_id: UUID | None
    direction: str
    subject: Decimal
    subject_nature: str
    comparison: Decimal
    comparison_nature: str
    variance: Decimal
    percent: Decimal | None
    favourable: bool | None
    requires_explanation: bool
    explanation: Explanation | None


@dataclass(frozen=True)
class Variance:
    version: BudgetVersion
    budget: Budget
    month: date
    view: str
    comparison: str
    window: list[date]
    cutover: date | None
    watermark: int
    unposted: int | None
    thresholds: Thresholds
    rows: list[Row]
    review: PeriodReview | None


def thresholds(entity_id: UUID) -> Thresholds:
    row = BudgetSettings.objects.filter(legal_entity_id=entity_id).first()
    if row is None:
        return Thresholds(Decimal(1000), Decimal(10))
    return Thresholds(row.explain_above_amount, row.explain_above_percent)


def window(months: list[date], month: date, view: str) -> list[date]:
    i = months.index(month)
    if view == View.MONTH:
        return [month]
    if view == View.QTD:
        return months[(i // 3) * 3 : i + 1]
    if view == View.YTD:
        return months[: i + 1]
    return list(months)


def _key(line: BudgetLine) -> tuple[str, UUID | None]:
    code = line.taxonomy_line.code if line.taxonomy_line else str(line.account_id)
    return code, line.dimension_value_id


class _Actuals:
    """Posted actuals per budget line and month, in each line's natural direction."""

    def __init__(
        self,
        ctx: WorkspaceContext,
        budget: Budget,
        lines: list[BudgetLine],
        months: list[date],
        *,
        scoped: bool,
        watermark: int,
    ) -> None:
        entity_id = budget.legal_entity_id
        refs = accounts(ctx, entity_id)
        self.credit = {a.id for a in refs if a.normal_side == "CREDIT"}
        self.types = {a.id: a.type for a in refs}
        self.mapping = current_mapping(entity_id)
        self.by_code: dict[str, list[UUID]] = defaultdict(list)
        for account_id, tax_line in self.mapping.items():
            self.by_code[tax_line.code].append(account_id)
        first, last = min(months), month_end(max(months))
        self.entity: dict[tuple[UUID, date], Decimal] = defaultdict(Decimal)
        self.tagged: dict[tuple[UUID, UUID, date], Decimal] = defaultdict(Decimal)
        if not scoped and any(ln.dimension_value_id is None for ln in lines):
            facts = actuals_monthly(
                ctx, entity_id, date_from=first, date_to=last, watermark=watermark
            ).facts
            for f in facts:
                self.entity[(f.account_id, f.period)] += self._natural(f.account_id, f.net_debit)
        values = sorted({ln.dimension_value_id for ln in lines if ln.dimension_value_id}, key=str)
        if values:
            rows = dimension_actuals(
                ctx,
                entity_id,
                date_from=first,
                date_to=last,
                value_ids=values,
                watermark=watermark,
                permission="budget.department" if scoped else "reports.read",
            )
            for r in rows:
                net = r.debit_total - r.credit_total
                self.tagged[(r.value_id, r.account_id, r.month)] += self._natural(r.account_id, net)

    def _natural(self, account_id: UUID, net_debit: Decimal) -> Decimal:
        return -net_debit if account_id in self.credit else net_debit

    def accounts_of(self, line: BudgetLine) -> list[UUID]:
        if line.account_id:
            return [line.account_id]
        return self.by_code.get(line.taxonomy_line.code, []) if line.taxonomy_line else []

    def value(self, line: BudgetLine, month: date) -> Decimal:
        accts = self.accounts_of(line)
        if line.dimension_value_id:
            value = line.dimension_value_id
            return sum((self.tagged.get((value, a, month), ZERO) for a in accts), ZERO)
        return sum((self.entity.get((a, month), ZERO) for a in accts), ZERO)

    def direction(self, line: BudgetLine) -> str:
        if line.taxonomy_line:
            return line.taxonomy_line.direction
        kind = self.types.get(line.account_id) if line.account_id else None
        if kind == "INCOME":
            return "HIGHER_BETTER"
        if kind == "EXPENSE":
            return "LOWER_BETTER"
        mapped = self.mapping.get(line.account_id) if line.account_id else None
        return mapped.direction if mapped else "HIGHER_BETTER"


@dataclass(frozen=True)
class Figures:
    subject: Decimal
    subject_nature: str
    comparison: Decimal
    comparison_nature: str


def _row(
    line: BudgetLine | None,
    template: BudgetLine,
    direction: str,
    figures: Figures,
    limits: Thresholds,
    explanation: Explanation | None,
) -> Row:
    subject, comparison = figures.subject, figures.comparison
    variance = subject - comparison
    percent = None if comparison == 0 else variance / abs(comparison) * HUNDRED
    favourable = None if variance == 0 else (variance > 0) == (direction == "HIGHER_BETTER")
    required = (
        line is not None
        and variance != 0
        and abs(variance) >= limits.amount
        and (percent is None or abs(percent) >= limits.percent)
    )
    return Row(
        line_id=line.id if line else None,
        taxonomy_code=template.taxonomy_line.code if template.taxonomy_line else None,
        account_id=template.account_id,
        dimension_value_id=template.dimension_value_id,
        direction=direction,
        subject=subject,
        subject_nature=figures.subject_nature,
        comparison=comparison,
        comparison_nature=figures.comparison_nature,
        variance=variance,
        percent=percent,
        favourable=favourable,
        requires_explanation=required,
        explanation=explanation,
    )


def _explanations(
    version: BudgetVersion, month: date, view: str, comparison: str
) -> dict[UUID, Explanation]:
    latest: dict[UUID, Explanation] = {}
    rows = Explanation.objects.filter(
        version=version, month=month, view=view, comparison=comparison
    ).select_related("author")
    for e in rows.order_by("seq"):
        latest[e.line_id] = e
    return latest


def compute(
    ctx: WorkspaceContext,
    entity_id: UUID,
    version_id: UUID,
    *,
    month: date,
    view: str = View.MONTH,
    comparison: str = Comparison.ACTUAL_VS_BUDGET,
) -> Variance:
    """The variance of every visible budget line for one period view."""
    if view not in View.values:
        raise ValidationFailedError(
            "Choose month, quarter to date, year to date or full year.",
            field_errors={"view": ["unknown view"]},
        )
    if comparison not in Comparison.__members__:
        raise ValidationFailedError(
            "Choose a comparison.", field_errors={"comparison": ["unknown comparison"]}
        )
    access = services._access(ctx, entity_id, services.READ)
    full = services._load(services._version(access.entity_id, version_id))
    dims = access.require(full.budget.id)
    view_ = full.only(dims)
    budget, version, months = view_.budget, view_.version, view_.months
    if month not in months:
        raise ValidationFailedError(
            "Choose a month of this budget's fiscal year.",
            field_errors={"month": ["outside the fiscal year"]},
        )
    scoped = dims is not None
    permission = "budget.department" if scoped else "reports.read"
    watermark = current_watermark(ctx, budget.legal_entity_id, permission)
    span = window(months, month, view)
    to_date = [m for m in span if m <= month]
    later = [m for m in span if m > month]
    needed = list(to_date)
    if comparison == Comparison.ACTUAL_VS_PRIOR_YEAR:
        needed += [add_months(m, -12) for m in span]
    lines = view_.lines
    actual = _Actuals(ctx, budget, lines, needed or [month], scoped=scoped, watermark=watermark)
    limits = thresholds(budget.legal_entity_id)
    explained = _explanations(version, month, view, comparison)
    blended = view == View.FULL_YEAR and bool(later)
    rows: list[Row] = []

    def budgeted(v: services.VersionView, line: BudgetLine, period: list[date]) -> Decimal:
        amounts = v.amounts.get(line.id, {})
        return sum((amounts.get(m, ZERO) for m in period), ZERO)

    def actual_to_date(line: BudgetLine) -> Decimal:
        return sum((actual.value(line, m) for m in to_date), ZERO)

    if comparison == Comparison.CURRENT_VS_ORIGINAL:
        first = services._view(budget).original
        original = services._load(first).only(dims) if first else view_
        by_key = {_key(ln): ln for ln in original.lines}
        for line in lines:
            old = by_key.pop(_key(line), None)
            rows.append(
                _row(
                    line,
                    line,
                    actual.direction(line),
                    Figures(
                        budgeted(view_, line, span),
                        "BUDGET",
                        budgeted(original, old, span) if old else ZERO,
                        "BUDGET",
                    ),
                    limits,
                    explained.get(line.id),
                )
            )
        for old in by_key.values():
            rows.append(
                _row(
                    None,
                    old,
                    actual.direction(old),
                    Figures(ZERO, "BUDGET", budgeted(original, old, span), "BUDGET"),
                    limits,
                    None,
                )
            )
    else:
        for line in lines:
            subject = actual_to_date(line) + (budgeted(view_, line, later) if blended else ZERO)
            if comparison == Comparison.ACTUAL_VS_BUDGET:
                compared, nature = budgeted(view_, line, span if blended else to_date), "BUDGET"
            else:
                period = [add_months(m, -12) for m in (span if blended else to_date)]
                compared, nature = sum((actual.value(line, m) for m in period), ZERO), "ACTUAL"
            rows.append(
                _row(
                    line,
                    line,
                    actual.direction(line),
                    Figures(subject, "BLENDED" if blended else "ACTUAL", compared, nature),
                    limits,
                    explained.get(line.id),
                )
            )
    unposted = None
    if not scoped and to_date:
        unposted = unposted_count(
            ctx, budget.legal_entity_id, date_from=to_date[0], date_to=month_end(to_date[-1])
        )
    review = PeriodReview.objects.filter(version=version, month=month).first()
    return Variance(
        version,
        budget,
        month,
        view,
        comparison,
        span,
        month if blended else None,
        watermark,
        unposted,
        limits,
        rows,
        review,
    )


@transaction.atomic
def explain(  # noqa: PLR0913 (keyword-only details of the explanation)
    ctx: WorkspaceContext,
    entity_id: UUID,
    version_id: UUID,
    line_id: UUID,
    *,
    month: date,
    view: str,
    comparison: str,
    comment: str,
) -> Explanation:
    """Record (or change) the explanation of a line's variance; earlier ones are kept."""
    access = services._access(ctx, entity_id, services.EDIT)
    version = services._version(access.entity_id, version_id, lock=True)
    dims = access.require(version.budget_id)
    if version.status not in CURRENT:
        raise services.LifecycleError("Explain variances against the approved budget.")
    line = BudgetLine.objects.filter(version=version, id=line_id).first()
    if line is None or (dims is not None and line.dimension_value_id not in dims):
        raise ValidationFailedError("Budget line not found.", field_errors={"line_id": ["?"]})
    comment = comment.strip()
    if not comment or len(comment) > 1000:
        raise ValidationFailedError(
            "Write the explanation (up to 1,000 characters).",
            field_errors={"comment": ["required"]},
        )
    if view not in View.values or comparison not in Comparison.__members__:
        raise ValidationFailedError(
            "Unknown view or comparison.", field_errors={"view": ["unknown"]}
        )
    if month not in services.fiscal_months(
        version.budget.fiscal_year_start, version.budget.fiscal_year_end
    ):
        raise ValidationFailedError(
            "Choose a month of this budget's fiscal year.",
            field_errors={"month": ["outside the fiscal year"]},
        )
    found = Explanation.objects.filter(line=line, month=month, view=view, comparison=comparison)
    seq = (found.aggregate(m=Max("seq"))["m"] or 0) + 1
    made = Explanation.objects.create(
        tenant_id=ctx.tenant.id,
        legal_entity_id=access.entity_id,
        version=version,
        line=line,
        month=month,
        view=view,
        comparison=comparison,
        comment=comment,
        seq=seq,
        author_id=ctx.user.id,
    )
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action="budgeting.variance.explained",
        subject_type="budget_line",
        subject_id=line.id,
        entity_id=access.entity_id,
        changes={"month": month.isoformat(), "view": view, "comparison": comparison, "seq": seq},
    )
    return made


def history(
    ctx: WorkspaceContext, entity_id: UUID, version_id: UUID, line_id: UUID
) -> list[Explanation]:
    """Every explanation of one line, oldest first (who wrote what, and when)."""
    access = services._access(ctx, entity_id, services.READ)
    version = services._version(access.entity_id, version_id)
    dims = access.require(version.budget_id)
    rows = Explanation.objects.filter(version=version, line_id=line_id).select_related("author")
    if dims is not None:
        rows = rows.filter(line__dimension_value_id__in=dims)
    return list(rows.order_by("month", "view", "comparison", "seq"))


@transaction.atomic
def complete_review(
    ctx: WorkspaceContext, entity_id: UUID, version_id: UUID, month: date
) -> PeriodReview:
    """Mark a month's budget review complete; refused while a required explanation is missing
    for the month or the year to date (actual vs budget)."""
    entity = get_entity(ctx, entity_id, services.APPROVE)
    version = services._version(entity.id, version_id, lock=True)
    if version.status not in CURRENT:
        raise services.LifecycleError("Review against the approved budget.")
    missing, watermark = [], 0
    months = services.fiscal_months(
        version.budget.fiscal_year_start, version.budget.fiscal_year_end
    )
    if month not in months:
        raise ValidationFailedError(
            "Choose a month of this budget's fiscal year.",
            field_errors={"month": ["outside the fiscal year"]},
        )
    # In the first month, the year to date is the month itself: explain it once.
    views = [View.MONTH] if month == months[0] else [View.MONTH, View.YTD]
    for view in views:
        result = compute(ctx, entity_id, version_id, month=month, view=view)
        watermark = result.watermark
        missing += [
            f"{r.taxonomy_code or r.account_id} ({view.lower()})"
            for r in result.rows
            if r.requires_explanation and r.explanation is None
        ]
    if missing:
        raise ReviewIncompleteError(
            f"{len(missing)} variance(s) above the threshold still need an explanation.",
            field_errors={"lines": missing[:50]},
        )
    try:
        with transaction.atomic():
            review = PeriodReview.objects.create(
                tenant_id=ctx.tenant.id,
                legal_entity_id=entity.id,
                version=version,
                month=month,
                actuals_watermark=watermark,
                completed_by_id=ctx.user.id,
            )
    except IntegrityError as exc:
        raise ConflictError("This month's review is already complete.") from exc
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action="budgeting.review.completed",
        subject_type="budget_version",
        subject_id=version.id,
        entity_id=entity.id,
        changes={"month": month.isoformat(), "watermark": watermark},
    )
    return review
