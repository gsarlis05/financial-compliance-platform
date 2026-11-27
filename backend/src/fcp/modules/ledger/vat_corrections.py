"""Corrections of VAT codes for one entity (brief 27, T-2, #255).

The catalogue stays as seeded. A correction changes a code's rate, treatment, category or name
for the entity, from a date and with its source. A line uses the version in force on its tax point
(or, without one, on its accounting date); the entry form uses the version in force on the date
shown. The corrections are kept by ``taxrules``. This module checks what a correction may say,
and lays the correction over the code.
"""

from dataclasses import replace
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from fcp.core.errors import NotFoundError, ValidationFailedError
from fcp.modules.taxrules.api import Correction, Kind, add_correction, all_for
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from .models import VatCode

FIELDS = ("rate", "treatment", "category", "name", "name_el")


def _invalid(field: str, message: str) -> ValidationFailedError:
    return ValidationFailedError(message, field_errors={field: [message]})


def _rate(value: Any) -> str | None:
    if value is None or value == "":
        return None
    try:
        rate = Decimal(str(value))
    except InvalidOperation as exc:
        raise _invalid("rate", "Enter the rate as a fraction, such as 0.19 for 19%.") from exc
    if not rate.is_finite() or rate < 0 or rate >= 1 or rate != rate.quantize(Decimal("0.0001")):
        raise _invalid("rate", "Enter the rate as a fraction from 0 to 0.9999, such as 0.19.")
    return f"{rate:.4f}"


def correct(  # noqa: PLR0913 - keyword-only parts of a correction
    ctx: WorkspaceContext,
    entity_id: UUID,
    code: str,
    *,
    effective_from: date,
    values: dict[str, Any],
    source: str,
    note: str = "",
) -> Correction:
    """Check and record a correction of ``code`` for the entity."""
    entity = get_entity(ctx, entity_id, "tax.rules.correct")
    known = VatCode.objects.filter(jurisdiction=entity.jurisdiction, code=code).exists()
    if not known:
        raise NotFoundError(f"VAT code {code} is not in the {entity.jurisdiction} catalogue.")
    unknown = set(values) - set(FIELDS)
    if unknown:
        raise _invalid("values", f"A VAT code correction can change {', '.join(FIELDS)} only.")
    clean: dict[str, Any] = {}
    if "rate" in values:
        clean["rate"] = _rate(values["rate"])
    if "treatment" in values:
        if values["treatment"] not in VatCode.Treatment.values:
            raise _invalid("treatment", "Unknown treatment.")
        clean["treatment"] = values["treatment"]
    if "category" in values:
        categories = set(VatCode.objects.filter(jurisdiction=entity.jurisdiction)
                         .exclude(category="").values_list("category", flat=True))  # fmt: skip
        if values["category"] not in categories:
            raise _invalid("category", "Choose one of the catalogue's VAT categories.")
        clean["category"] = values["category"]
    for name in ("name", "name_el"):
        if name in values:
            text = str(values[name]).strip()[:200]
            if name == "name" and not text:
                raise _invalid("name", "A code needs a name.")
            clean[name] = text
    return add_correction(ctx, entity.id, kind=Kind.VAT_CODE, target=code,
                          effective_from=effective_from, values=clean, source=source,
                          note=note)  # fmt: skip


class Overlay:
    """The entity's VAT code corrections, read once, laid over codes by date."""

    def __init__(self, entity_id: UUID) -> None:
        self.by_code: dict[str, list[Correction]] = {}
        for c in all_for(entity_id, Kind.VAT_CODE):
            self.by_code.setdefault(c.target, []).append(c)

    def __bool__(self) -> bool:
        return bool(self.by_code)

    def find(self, code: str, day: date) -> Correction | None:
        found = None
        for c in self.by_code.get(code, []):  # oldest first: the last one started wins
            if c.effective_from <= day:
                found = c
        return found

    def apply(self, vat_code: VatCode, day: date) -> tuple[VatCode, Correction | None]:
        """A copy of ``vat_code`` as corrected on ``day`` (never saved)."""
        fix = self.find(vat_code.code, day)
        if fix is None:
            return vat_code, None
        v = fix.values
        changed: dict[str, Any] = {
            k: v[k] for k in ("treatment", "category", "name", "name_el") if k in v
        }
        if "rate" in v:
            changed["rate"] = Decimal(v["rate"]) if v["rate"] is not None else None
        copy = VatCode(**{f.attname: getattr(vat_code, f.attname)
                          for f in VatCode._meta.concrete_fields})  # fmt: skip
        for key, value in changed.items():
            setattr(copy, key, value)
        return copy, fix


def corrected(values: Any, fix: Correction | None) -> Any:
    """A dataclass with the corrected fields replaced (for read models such as VAT lines)."""
    if fix is None:
        return values
    v = fix.values
    changes: dict[str, Any] = {k: v[k] for k in ("treatment", "category") if k in v}
    if "rate" in v:
        changes["rate"] = Decimal(v["rate"]) if v["rate"] is not None else None
    return replace(values, **changes)
