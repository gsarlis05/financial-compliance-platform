# 27 — The owner's check of the rules, corrections on a screen, and drafts

Status: **APPROVED (2026-11-27)** by the owner's answers of 2026-11-27, quoted below.

## 1. The owner's decisions
Asked what remains for version 1, the owner answered:

1. **Tax rules (#93, #154):** "1 is ok I checked for now, leave the option to correct something in
   case anything changes". This covers the VAT codes, the VAT box rules and the corporate tax
   rules.
2. **Projection engine (#153):** "2 is ok also leave the option to correct something in case
   anything changes".
3. **Bank and package exports (#91, #92):** "leave it as unfinished". The presets stay "to be
   confirmed".
4. **Tax Department VAT XML (#220):** "not needed for now have the tab ready but as draft".
5. **Hosting (#94, #78):** "for later leave it as a draft".

On who corrects a rule, the owner chose **"Me, on a screen"**, 2026-11-27.

## 2. Rules that do not change
- **A check by the owner is recorded as exactly that.** The wording is "Checked by the owner on
  27/11/2026". It is not called a professional verification, and the details say "not a
  professional verification". A professional can still verify later, and that is recorded
  separately.
- **Rules stay versioned data.** A correction is a new version for the entity, starting from a
  date and carrying its source. It is checked like any other input, audited (who, when, what
  changed, and why), and never edits an earlier version.
- **Earlier figures never change.** A VAT return, a calculation run or a projection keeps the
  rules it used; they are pinned in its snapshot. A correction applies to returns and runs
  prepared after it, for the dates it covers.
- Nothing is invented. The platform never suggests a rate or a rule; it applies what the owner
  enters, with the source the owner gives.
- Nothing is submitted, and nothing is created on AWS.

## 3. Work, in order (one issue and one PR each)
| # | Item | What "done" means |
|---|---|---|
| T-1 | **The owner's check recorded** | The VAT codes, box rules, corporate tax rules and the projection engine show "Checked by the owner on 27/11/2026" on screens, in exports and in snapshots, instead of "pending verification" or "pending professional review". The detail still says it is not a professional verification. The status lives in data, with its history. Issues #93, #154 and #153 are closed as decided by the owner. |
| T-2 | **Correcting the rules on a screen** | A **Tax rules** screen lists the VAT codes, the VAT box rules and the corporate tax rules in force, with their status and source. The owner can add a correction for this entity, from a date and with a source: a VAT code's rate, treatment, category or name; a box rule (the boxes a category and line kind go to, or "excluded"); or a corporate tax rule set (rate, loss years, instalments, final payment). Every engine reads the corrected version for the dates it covers. Returns and runs pin what they used. Corrections are audited and can themselves be corrected by a later version, never edited. |
| T-3 | **Tax Department XML: the tab, as a draft** | The VAT screen has a "Tax Department XML" tab marked **draft**. It explains that the export waits for the official schema and guide, produces no file, and links to #220, which stays open. |

The projection engine is code, not data. "Correcting" it means correcting its inputs, which
already have screens: assumptions, tax rules (T-2), capital allowance classes and debt. If the
engine itself must change, the owner tells the developer. The golden model and its tests guard
the change, and the status is set back to "pending" until the owner checks it again.

Issues: T-1 #254 · T-2 #255 · T-3 #256.

Items 3 and 5 need no work. Their issues stay open, and the documents stay drafts.

## 4. Acceptance
- **AC-T1.** No screen, export or snapshot says "pending verification" for the checked rules. Each
  shows the owner's check and its date, and says that it is not a professional verification.
- **AC-T2.** A VAT return prepared after a VAT code correction uses the corrected rate, category or
  treatment for lines dated on or after its start. A return prepared before it is unchanged. The
  same holds for box rules and corporate tax rules, and for projections run after a correction.
- **AC-T3.** A correction without a source or a start date, or one that overlaps a later
  correction, is refused with the reason.
