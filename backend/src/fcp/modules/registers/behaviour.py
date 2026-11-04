"""How late each customer pays (M3-6, doc 10 §3.2, AC-CW2).

The 13-week forecast dates an open receivable at its due date plus the customer's days late:
- **observed:** the amount-weighted average of (fully settled date - due date) over the
  customer's invoices fully settled in the trailing 12 months up to the as-of date, rounded
  HALF_UP to whole days. Early payment counts as negative.
- With fewer than ``MIN_SAMPLE`` such invoices, no average is observed and 0 is used, with a
  note saying why.
- **override:** a per-customer setting (``Counterparty.days_late_override``) replaces the
  observed value.

An invoice is fully settled on the date of the allocation that completes it (allocations are
dated by the later of the two accounting dates). The calculation is deterministic: Decimal
arithmetic over posted lines and allocations dated up to the as-of date.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from .models import Allocation, Counterparty
from .services import RECEIVABLE, open_items

MIN_SAMPLE = 3
WINDOW = timedelta(days=365)
ZERO = Decimal(0)


@dataclass(frozen=True)
class Behaviour:
    counterparty_id: UUID
    counterparty_code: str
    observed_days_late: int | None  # None: too few settled invoices
    sample: int  # invoices fully settled in the window
    override: int | None
    note: str

    @property
    def days_late(self) -> int:
        """What the forecast uses: the override, else the observed average, else 0."""
        if self.override is not None:
            return self.override
        return self.observed_days_late or 0


def _settled_on(amount: Decimal, allocations: list[tuple[date, Decimal]]) -> date | None:
    covered = ZERO
    for day, part in sorted(allocations):
        covered += part
        if covered >= amount:
            return day
    return None


def payment_behaviour(ctx: WorkspaceContext, entity_id: UUID, as_of: date) -> list[Behaviour]:
    """Every customer's payment behaviour at ``as_of`` (needs ``registers.counterparty.read``)."""
    entity = get_entity(ctx, entity_id, "registers.counterparty.read")
    invoices = [
        i
        for i in open_items(ctx, entity.id, as_of=as_of, side=RECEIVABLE, include_settled=True)
        if i.kind == "INVOICE"
    ]
    parts: dict[UUID, list[tuple[date, Decimal]]] = defaultdict(list)
    for a in Allocation.objects.filter(
        legal_entity=entity,
        allocated_on__lte=as_of,
        debit_line_id__in=[i.line_id for i in invoices],
    ):
        parts[a.debit_line_id].append((a.allocated_on, a.amount))
    weighted: dict[UUID, Decimal] = defaultdict(lambda: ZERO)
    weights: dict[UUID, Decimal] = defaultdict(lambda: ZERO)
    counts: dict[UUID, int] = defaultdict(int)
    since = as_of - WINDOW
    for invoice in invoices:
        settled = _settled_on(invoice.amount, parts[invoice.line_id])
        if settled is None or settled <= since:
            continue
        late = (settled - invoice.due_date).days
        weighted[invoice.counterparty_id] += invoice.amount * late
        weights[invoice.counterparty_id] += invoice.amount
        counts[invoice.counterparty_id] += 1
    result = []
    customers = Counterparty.objects.filter(
        legal_entity=entity, kind__in=[Counterparty.Kind.CUSTOMER, Counterparty.Kind.BOTH]
    ).order_by("code")
    for c in customers:
        n = counts[c.id]
        observed = None
        if n >= MIN_SAMPLE:
            observed = int((weighted[c.id] / weights[c.id]).quantize(Decimal(1), ROUND_HALF_UP))
            note = f"Observed over {n} invoices settled in the last 12 months."
        else:
            note = (
                f"Only {n} invoice(s) settled in the last 12 months (at least {MIN_SAMPLE} "
                "needed): 0 days late is assumed."
            )
        if c.days_late_override is not None:
            note = f"Override set by a user. {note}"
        result.append(Behaviour(c.id, c.code, observed, n, c.days_late_override, note))
    return result
