"""Who has checked the platform's rules and the projection engine, and when (brief 27, #254).

The record is data (``reviews.json``): an append-only list, the latest entry per subject applies.
A check by the owner (``OWNER_CHECKED``) is never presented as a professional verification; the
per-row ``verified`` flags of VAT codes and tax rule sets keep meaning a professional's
verification. Everything that used to say "pending verification" reads its status from here.
"""

import json
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any, Literal

Status = Literal["PENDING", "OWNER_CHECKED", "PROFESSIONALLY_VERIFIED"]
STATUSES: tuple[Status, ...] = ("PENDING", "OWNER_CHECKED", "PROFESSIONALLY_VERIFIED")
ENGINE = "PROJECTION_ENGINE"


def vat_codes(jurisdiction: str) -> str:
    return f"{jurisdiction}:VAT_CODES"


def vat_box_rules(jurisdiction: str) -> str:
    return f"{jurisdiction}:VAT_BOX_RULES"


def corporate_tax(jurisdiction: str) -> str:
    return f"{jurisdiction}:CORPORATE_INCOME_TAX"


@dataclass(frozen=True)
class Review:
    subject: str
    status: Status
    on: date | None
    by: str
    note: str

    @property
    def pending(self) -> bool:
        return self.status == "PENDING"

    def label(self) -> str:
        """In plain words, for exports and snapshots."""
        if self.status == "PROFESSIONALLY_VERIFIED":
            return f"Verified by {self.by} on {self.on:%d/%m/%Y}." if self.on else "Verified."
        if self.status == "OWNER_CHECKED" and self.on:
            return f"Checked by the owner on {self.on:%d/%m/%Y} (not a professional verification)."
        return "Pending verification."

    def as_dict(self) -> dict[str, Any]:
        return {"subject": self.subject, "status": self.status,
                "on": self.on.isoformat() if self.on else None, "by": self.by,
                "note": self.note}  # fmt: skip


def _parse(entry: dict[str, Any]) -> Review:
    status = entry["status"]
    if status not in STATUSES:
        raise ValueError(f"unknown review status {status!r}")
    on = date.fromisoformat(entry["on"]) if entry.get("on") else None
    if status != "PENDING" and (on is None or not entry.get("by")):
        raise ValueError(f"{entry['subject']}: a check needs a date and who made it")
    return Review(entry["subject"], status, on, entry.get("by", ""), entry.get("note", ""))


@cache
def _data() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((Path(__file__).parent / "reviews.json").read_text("utf-8"))
    return data


@cache
def history() -> tuple[Review, ...]:
    return tuple(_parse(e) for e in _data()["reviews"])


def review(subject: str) -> Review:
    """The latest entry for ``subject``; pending when there is none."""
    found = [r for r in history() if r.subject == subject]
    return found[-1] if found else Review(subject, "PENDING", None, "", "")


def current() -> list[Review]:
    subjects = dict.fromkeys(r.subject for r in history())
    return [review(s) for s in subjects]


def _words(kind: str, r: Review, lang: str, **extra: str) -> str:
    text: str = _data()["wording"][kind][r.status]["el" if lang == "el" else "en"]
    return text.format(on=f"{r.on:%d/%m/%Y}" if r.on else "", by=r.by, **extra)


def engine_status() -> str:
    """The projection engine's status as runs and snapshots record it."""
    r = review(ENGINE)
    return "PENDING_PROFESSIONAL_REVIEW" if r.pending else r.status


def engine_note(lang: str = "en") -> str:
    """One sentence for exports and report packs."""
    return _words("engine", review(ENGINE), lang)


def rules_note(subject: str, what: str, lang: str = "en") -> str:
    """One sentence on a set of rules (``what``: e.g. "Box rules CY-VAT-BOXES@1")."""
    return rules_note_for(review(subject), what, lang)


def rules_note_for(found: Review, what: str, lang: str = "en") -> str:
    """The same for a review pinned earlier (e.g. in a VAT report's snapshot)."""
    return _words("rules", found, lang, what=what)
