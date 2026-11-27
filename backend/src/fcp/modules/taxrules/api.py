"""Public interface of the ``taxrules`` module and its HTTP routes (M6F-2, #147).

Rule sets are reference data. The routes show the rule sets of an entity's jurisdiction, each
with its sources and review status, and who has checked the rules and the engine (brief 27).
"""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.http import HttpRequest
from ninja import Field, Query, Router, Schema, Status

from fcp.core import reviews
from fcp.core.api.permissions import requires
from fcp.core.errors import ValidationFailedError
from fcp.modules.tenancy.api import get_entity, workspace_ctx

from . import corrections
from .corrections import Correction, Kind, add, all_for, in_force, latest_by_target
from .rules import CIT, Instalment, TaxRules, rule_sets, rules_for

__all__ = [
    "CIT",
    "Correction",
    "Instalment",
    "Kind",
    "TaxRules",
    "add_correction",
    "all_for",
    "in_force",
    "latest_by_target",
    "router",
    "rule_sets",
    "rules_for",
]

add_correction = add

router = Router(tags=["taxrules"])
BASE = "/w/{slug}/entities/{uuid:entity_id}"


class SourceOut(Schema):
    publisher: str
    title: str
    url: str
    note: str


class TaxInstalmentOut(Schema):
    month: int
    day: int
    share: str


class TaxRuleSetOut(Schema):
    id: str
    jurisdiction: str
    tax: str
    effective_from: date
    effective_to: date | None
    rate: str = Field(description="A fraction: 0.15 for 15%")
    loss_carryforward_years: int = Field(description="For losses arising in these tax years")
    tax_year_start_month: int
    provisional_instalments: list[TaxInstalmentOut]
    final_payment: str = Field(description="When the balance is due, after the tax year")
    verified: bool = Field(description="False until a qualified tax professional confirms it")
    verification_note: str
    review_status: str = Field(description="PENDING, OWNER_CHECKED or PROFESSIONALLY_VERIFIED")
    review_note: str = Field(description="Who checked the rules and when, in plain words")
    sources: list[SourceOut]


class ReviewOut(Schema):
    subject: str
    status: str
    on: date | None
    by: str
    note: str
    label: str


def _review(r: TaxRules) -> reviews.Review:
    if r.verified:
        return reviews.Review(r.id, "PROFESSIONALLY_VERIFIED", None, "", r.verification_note)
    return reviews.review(reviews.corporate_tax(r.jurisdiction))


def _out(r: TaxRules) -> TaxRuleSetOut:
    offset, month, day = r.final_payment
    return TaxRuleSetOut(
        id=r.id, jurisdiction=r.jurisdiction, tax=r.tax, effective_from=r.effective_from,
        effective_to=r.effective_to, rate=f"{r.rate.normalize():f}",
        loss_carryforward_years=r.loss_carryforward_years,
        tax_year_start_month=r.tax_year_start_month,
        provisional_instalments=[TaxInstalmentOut(month=i.month, day=i.day, share=str(i.share))
                                 for i in r.instalments],
        final_payment=f"{day:02d}/{month:02d} of the year {offset} after the tax year",
        verified=r.verified, verification_note=r.verification_note,
        review_status=_review(r).status, review_note=_review(r).label(),
        sources=[SourceOut(**{k: s.get(k, "") for k in ("publisher", "title", "url", "note")})
                 for s in r.sources],
    )  # fmt: skip


@router.get(f"{BASE}/tax-rules", response=list[TaxRuleSetOut])
@requires("planning.read")
def list_tax_rules(request: HttpRequest, slug: str, entity_id: UUID) -> list[TaxRuleSetOut]:
    """Corporate income tax rule sets of the entity's jurisdiction, oldest first."""
    ctx = workspace_ctx(request, slug, entity_id)
    entity = get_entity(ctx, entity_id, "planning.read")
    return [_out(r) for r in rule_sets(entity.jurisdiction, entity_id=entity.id)]


# --- corrections (brief 27, T-2) -----------------------------------------------------------------


class CorrectionOut(Schema):
    id: UUID
    kind: str
    target: str
    effective_from: date
    values: dict[str, Any]
    source: str
    note: str
    created_at: str
    created_by: str


def correction_out(c: Correction) -> CorrectionOut:
    return CorrectionOut(id=c.id, kind=c.kind, target=c.target, effective_from=c.effective_from,
                         values=c.values, source=c.source, note=c.note, created_at=c.created_at,
                         created_by=c.created_by)  # fmt: skip


class CorrectionQuery(Schema):
    kind: Kind | None = None


@router.get(f"{BASE}/rule-corrections", response=list[CorrectionOut])
@requires("tenancy.workspace.read")
def list_corrections(
    request: HttpRequest, slug: str, entity_id: UUID, q: Query[CorrectionQuery]
) -> list[CorrectionOut]:
    """Every correction of the entity's rules, the most recent first."""
    ctx = workspace_ctx(request, slug, entity_id)
    return [correction_out(c) for c in corrections.history(ctx, entity_id, q.kind)]


class CorporateTaxCorrectionIn(Schema):
    effective_from: date = Field(description="The first day of the first tax year it applies to")
    rate: str = Field(pattern=r"^0(\.\d{1,4})?$", description="A fraction: 0.15 for 15%")
    loss_carryforward_years: int = Field(ge=0, le=50)
    tax_year_start_month: int = Field(ge=1, le=12)
    provisional_instalments: list[TaxInstalmentOut] = Field(max_length=12)
    final_payment_years_after: int = Field(ge=0, le=3)
    final_payment_month: int = Field(ge=1, le=12)
    final_payment_day: int = Field(ge=1, le=31)
    source: str = Field(min_length=1, max_length=500)
    note: str = Field(default="", max_length=1000)


@router.post(f"{BASE}/tax-rules/corrections", response={201: CorrectionOut})
@requires("tax.rules.correct")
def correct_corporate_tax(
    request: HttpRequest, slug: str, entity_id: UUID, payload: CorporateTaxCorrectionIn
) -> Status[CorrectionOut]:
    """A corrected corporate income tax rule set for this entity, from the start of a tax year.
    Projections run after it use it for the years it covers; earlier runs keep theirs."""
    ctx = workspace_ctx(request, slug, entity_id)
    p = payload
    if p.effective_from.day != 1 or p.effective_from.month != p.tax_year_start_month:
        raise ValidationFailedError(
            "A corrected rule set starts on the first day of a tax year.",
            field_errors={"effective_from": ["not the first day of a tax year"]},
        )
    shares = [Decimal(i.share) for i in p.provisional_instalments]
    if any(x <= 0 for x in shares) or (shares and sum(shares) != 1):
        raise ValidationFailedError(
            "The provisional instalments' shares must be positive and add up to 1.",
            field_errors={"provisional_instalments": ["shares do not add up to 1"]},
        )
    values = {
        "rate": p.rate, "loss_carryforward_years": p.loss_carryforward_years,
        "tax_year_start_month": p.tax_year_start_month,
        "instalments": [{"month": i.month, "day": i.day, "share": i.share}
                        for i in p.provisional_instalments],
        "final_payment": [p.final_payment_years_after, p.final_payment_month,
                          p.final_payment_day],
    }  # fmt: skip
    found = add(ctx, entity_id, kind=Kind.CORPORATE_TAX, target="CIT",
                effective_from=p.effective_from, values=values, source=p.source,
                note=p.note)  # fmt: skip
    return Status(201, correction_out(found))


@router.get(f"{BASE}/reviews", response=list[ReviewOut])
@requires("tenancy.workspace.read")
def list_reviews(request: HttpRequest, slug: str, entity_id: UUID) -> list[ReviewOut]:
    """Who has checked the platform's rules and the projection engine, and when (brief 27)."""
    workspace_ctx(request, slug, entity_id)
    return [ReviewOut(subject=r.subject, status=r.status, on=r.on, by=r.by, note=r.note,
                      label=r.label()) for r in reviews.current()]  # fmt: skip
