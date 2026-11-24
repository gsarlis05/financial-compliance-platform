"""Seeding the tax rule sets from ``data/<jurisdiction>.json`` (idempotent, by id)."""

import json
from datetime import date
from decimal import Decimal
from importlib import resources
from typing import Any

FILES = ("cy.json",)


def _check(rule: dict[str, Any]) -> None:
    shares = sum((Decimal(i["share"]) for i in rule["provisional_instalments"]), Decimal(0))
    if rule["provisional_instalments"] and shares != 1:
        raise ValueError(f"{rule['id']}: provisional instalment shares add up to {shares}, not 1")
    if not rule["sources"]:
        raise ValueError(f"{rule['id']}: every rule set needs at least one source")


def seed_rules(model: Any) -> int:
    count = 0
    for name in FILES:
        data = json.loads(resources.files(__package__).joinpath("data", name).read_text())
        for rule in data["rule_sets"]:
            _check(rule)
            final = rule["final_payment"]
            model.objects.update_or_create(id=rule["id"], defaults={
                "jurisdiction": data["jurisdiction"], "tax": rule["tax"],
                "effective_from": date.fromisoformat(rule["effective_from"]),
                "effective_to": (date.fromisoformat(rule["effective_to"])
                                 if rule["effective_to"] else None),
                "rate": Decimal(rule["rate"]),
                "loss_carryforward_years": rule["loss_carryforward_years"],
                "tax_year_start_month": rule["tax_year_start_month"],
                "provisional_instalments": rule["provisional_instalments"],
                "final_payment_year_offset": final["year_offset"],
                "final_payment_month": final["month"], "final_payment_day": final["day"],
                "sources": rule["sources"],
                "verification_note": rule["verification_note"],
            })  # fmt: skip
            count += 1
    return count
