"""Public interface of the ``taxrules`` module and its HTTP routes (M6F-2, #147).

Rule sets are reference data. The route shows the rule sets of an entity's jurisdiction, each
with its sources and verification status.
"""

from datetime import date
from uuid import UUID

from django.http import HttpRequest
from ninja import Field, Router, Schema

from fcp.core.api.permissions import requires
from fcp.modules.tenancy.api import get_entity, workspace_ctx

from .rules import CIT, Instalment, TaxRules, rule_sets, rules_for

__all__ = ["CIT", "Instalment", "TaxRules", "router", "rule_sets", "rules_for"]

router = Router(tags=["taxrules"])
BASE = "/w/{slug}/entities/{uuid:entity_id}"


class SourceOut(Schema):
    publisher: str
    title: str
    url: str
    note: str


class InstalmentOut(Schema):
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
    provisional_instalments: list[InstalmentOut]
    final_payment: str = Field(description="When the balance is due, after the tax year")
    verified: bool = Field(description="False until a qualified tax professional confirms it")
    verification_note: str
    sources: list[SourceOut]


def _out(r: TaxRules) -> TaxRuleSetOut:
    offset, month, day = r.final_payment
    return TaxRuleSetOut(
        id=r.id, jurisdiction=r.jurisdiction, tax=r.tax, effective_from=r.effective_from,
        effective_to=r.effective_to, rate=f"{r.rate.normalize():f}",
        loss_carryforward_years=r.loss_carryforward_years,
        tax_year_start_month=r.tax_year_start_month,
        provisional_instalments=[InstalmentOut(month=i.month, day=i.day, share=str(i.share))
                                 for i in r.instalments],
        final_payment=f"{day:02d}/{month:02d} of the year {offset} after the tax year",
        verified=r.verified, verification_note=r.verification_note,
        sources=[SourceOut(**{k: s.get(k, "") for k in ("publisher", "title", "url", "note")})
                 for s in r.sources],
    )  # fmt: skip


@router.get(f"{BASE}/tax-rules", response=list[TaxRuleSetOut])
@requires("planning.read")
def list_tax_rules(request: HttpRequest, slug: str, entity_id: UUID) -> list[TaxRuleSetOut]:
    """Corporate income tax rule sets of the entity's jurisdiction, oldest first."""
    ctx = workspace_ctx(request, slug, entity_id)
    entity = get_entity(ctx, entity_id, "planning.read")
    return [_out(r) for r in rule_sets(entity.jurisdiction)]
