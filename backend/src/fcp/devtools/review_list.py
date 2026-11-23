"""The owner's list for the professional review (#93): every rate, rule and method the platform uses
that a qualified Cyprus tax professional has not yet confirmed.

Generated from the data the platform actually uses, so it never drifts from it:
``python -m fcp.devtools.review_list`` writes ``docs/review/professional-review-list.md``, and a
test fails when the file is out of date.
"""

import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from fcp.modules.tax.boxes import ruleset

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / "docs" / "review" / "professional-review-list.md"
MODULES = Path(__file__).resolve().parents[1] / "modules"


def _json(path: Path) -> Any:
    return json.loads(path.read_text())


def _pct(rate: str | None) -> str:
    if rate is None:
        return "no rate"
    value = f"{(Decimal(rate) * 100).quantize(Decimal('0.01')):f}".rstrip("0").rstrip(".")
    return f"{value}%"


def _vat_codes() -> list[str]:
    data = _json(MODULES / "ledger" / "vat" / "cy.json")
    lines = ["## 1. VAT codes and rates", "",
             f"Source note in the data: *{data['note']}*", "",
             "| ✓ | Code | Name | Greek name | Category | Treatment | Rate |",
             "|---|---|---|---|---|---|---|"]  # fmt: skip
    for c in data["codes"]:
        lines.append(f"| ☐ | {c['code']} | {c['name']} | {c['name_el']} | {c['category']} | "
                     f"{c['treatment']} | {_pct(c.get('rate'))} |")  # fmt: skip
    lines += ["", "For each code, check:",
              "- the rate, and the date from which it applies (all are open-ended today);",
              "- that the category says what the transaction is (it decides the return's boxes);",
              "- that no code is missing, for example for temporary reliefs."]  # fmt: skip
    return lines


def _boxes() -> list[str]:
    rules = ruleset()
    lines = ["## 2. The VAT return's boxes", "",
             f"Rules `{rules['id']}`, status **{rules['status']}**. Sources:", ""]  # fmt: skip
    lines += [f"- {s['title']}" + (f" ({s['url']})" if s.get("url") else "")
              for s in rules["sources"]]  # fmt: skip
    lines += ["", "### 2.1 Box labels", "", "| ✓ | Box | Label used | Kind |", "|---|---|---|---|"]
    lines += [f"| ☐ | {b['box']} | {b['label']} | {b['kind']} |" for b in rules["boxes"]]
    lines += ["", "Labels are shown in English in both languages. Please give the official Greek "
              "wording if it should be shown.", "",
              "### 2.2 Which boxes each kind of line feeds", "",
              "| ✓ | Category | Line | Boxes | Source |", "|---|---|---|---|---|"]  # fmt: skip
    lines += [f"| ☐ | {r['category']} | {r['line']} | {', '.join(r['boxes'])} | {r['source']} |"
              for r in rules["rules"]]  # fmt: skip
    lines += ["", "### 2.3 Left out of the return", "", "| ✓ | Category | Why |", "|---|---|---|"]
    lines += [f"| ☐ | {r['category']} | {r['reason']} |" for r in rules["excluded"]]
    lines += ["", "### 2.4 Not covered: shown as exceptions, never guessed", "",
              "| ✓ | Case | What the platform says | Question for you |",
              "|---|---|---|---|"]  # fmt: skip
    questions = {
        "EXEMPT": "Should exempt supplies and purchases appear in Box 6 or Box 7?",
        "IMPORT": "Should the value of imports appear in Box 7?",
        "LEGACY_REVERSE_CHARGE": "None: the old code is replaced by specific codes.",
    }
    for r in rules["unsupported"]:
        case = r["category"] + (f" ({r['line']})" if r.get("line") else "")
        lines.append(f"| ☐ | {case} | {r['reason']} | {questions.get(r['category'], '')} |")
    return lines


METHODS = [
    (
        "Rounding",
        "Boxes 1 to 5 to the cent; Boxes 6 to 11B to the nearest euro, half up, with the "
        "rounding shown (ADR-0059).",
    ),
    (
        "Which return a line belongs to",
        "Lines are chosen by their accounting date. A tax point "
        "in another period is flagged, not moved (ADR-0059).",
    ),
    (
        "Partial recovery",
        "Box 4 takes only the recoverable input VAT; the non-recoverable part "
        "is kept on the line and in no box (ADR-0058, ADR-0059).",
    ),
    (
        "Reverse charge",
        "The VAT goes to Box 1 (EU acquisitions of goods: Box 2) and, as far as "
        "it is recoverable, Box 4; the net value to Boxes 6 and 7, and 11B for EU services.",
    ),
    ("Credit notes", "A credit note or reversal reduces every box its original fed."),
    (
        "Checks",
        "Box 6 ≥ 8A + 8B + 9 + 10 + 11B and Box 7 ≥ 11A + 11B; a shortfall is reported, "
        "with the note that a credit note can explain it.",
    ),
    (
        "EU member states",
        "The 27 member states, GR for Greece (EL in VAT numbers), used to check EU trade partners.",
    ),
    (
        "Imports",
        "Import VAT in Box 4 needs the customs declaration recorded; its taxable value at "
        "the code's rate must give that VAT (ADR-0062).",
    ),
    (
        "VIES",
        "Partners matched on country and VAT number without the prefix; triangular amounts "
        "kept apart and compared with no box: how should they be reported? (ADR-0063)",
    ),
    (
        "Corrections of a filed return",
        "A new version is prepared and compared with the filed "
        "one; the procedure for filing a correction is not described by the platform (ADR-0060).",
    ),
    (
        "Adjustments",
        "Manual adjustments change one box with a reason and evidence, approved by "
        "a second person except in a one-person workspace (ADR-0060).",
    ),
]


def _methods() -> list[str]:
    lines = ["## 3. How the platform prepares the return", "",
             "| ✓ | Topic | What the platform does |", "|---|---|---|"]  # fmt: skip
    lines += [f"| ☐ | {topic} | {text} |" for topic, text in METHODS]
    return lines


def _income_tax() -> list[str]:
    data = _json(MODULES / "taxrules" / "data" / "cy.json")
    lines = ["## 4. Corporate income tax (projections only)", "",
             f"Source note in the data: *{data['note']}*", ""]  # fmt: skip
    for r in data["rule_sets"]:
        to = r.get("effective_to") or "open"
        instalments = ", ".join(f"{i['day']}/{i['month']} ({_pct(i['share'])})"
                                for i in r.get("provisional_instalments", []))  # fmt: skip
        final = r.get("final_payment", {})
        lines += [f"### {r['id']}: {r['effective_from']} to {to}", "",
                  f"- ☐ Rate: {_pct(r.get('rate'))}",
                  f"- ☐ Losses carried forward: {r.get('loss_carryforward_years')} years",
                  f"- ☐ Provisional tax instalments: {instalments}",
                  f"- ☐ Final payment: {final.get('day')}/{final.get('month')} of the following "
                  "year",
                  f"- Note: {r.get('verification_note', '')}", ""]  # fmt: skip
    return lines


FIXED = """## 5. Capital allowances

The allowance classes and rates are entered by you for each company (Fixed assets, Allowance
classes), each with its source. Please have the classes you entered checked.

## 6. The projection engine

The validation package is in `docs/validation/`. Its reviewer sign-off form,
`docs/validation/05-reviewer-sign-off.md`, is for an independent qualified accountant (ACA, ACCA,
CPA or equivalent) to complete. Until then, projections are marked
**PENDING_PROFESSIONAL_REVIEW**.

## 7. Already decided by you (no review needed)

- A VIES correction carries the month's full figures (23 November 2026).
- Foreign-currency purchases are converted to euros at the exchange rate of the date and time of
  the purchase (23 November 2026; being built, #219).
- The Tax Department's XML file is left for later (23 November 2026; reminder in #220).
"""


def build() -> str:
    head = ["# Professional review list", "",
            "Everything below is used by the platform and has **not yet been confirmed by a "
            "qualified Cyprus tax professional** (#93). Tick each item when it is confirmed, or "
            "write the correction and its source next to it, and send the list back: corrections "
            "become new versions of the data.", "",
            "This file is generated from the platform's data (`python -m fcp.devtools.review_list`)"
            "; do not edit it by hand.", ""]  # fmt: skip
    parts = [head, _vat_codes(), [""], _boxes(), [""], _methods(), [""], _income_tax()]
    return "\n".join(line for part in parts for line in part) + "\n" + FIXED


def main() -> None:
    import os  # noqa: PLC0415

    import django  # noqa: PLC0415

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fcp.settings.dev")
    django.setup()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build())
    sys.stdout.write(f"Wrote {OUT}\n")


if __name__ == "__main__":
    main()
