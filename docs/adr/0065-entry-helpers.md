# ADR-0065: Help for data entry: a VAT code picker with favourites, and typing suggestions
Status: **Accepted** (V1-2i, #231) · Date: 2026-11-23

## Context
The owner asked on 23 November 2026 for easier data entry:
- a drop-down list of the VAT codes;
- favourite codes, to find them faster;
- suggestions while typing codes, descriptions and the like, "like Google search shows you
  things you have typed before".

## Decision
- **VAT code picker.** Each entry line has a combobox (WAI-ARIA 1.2 pattern) in place of the
  plain list. Typing filters by code, name or rate; a rate matches from its start, so "9%" finds
  9% and not 19%. The list shows, in order:
  - **★ Favourites**, the codes the user starred;
  - **Most used**, the five codes used most in this company, with how often;
  - every code by category, as before.

  Arrow keys move, Enter chooses, Escape closes. Typing a whole code (S19) chooses it.
- **Favourites** (`ledger_vat_favourite`) belong to a user and a company. They are kept on the
  server, so they follow the user to any browser, and are isolated like every tenant table (row-level
  security, composite tenant key). A star beside the picker adds or removes the chosen code. A
  favourite is a personal preference: it changes nothing in the books and is not audited.
- **The account's usual code.** When a line's account has a code it is usually used with and the
  line has none, the form offers "Use S19, the usual code for this account". It is never chosen
  for the user: the VAT treatment stays the user's decision.
- **Typing suggestions** for the entry's description and each line's memo and reference:
  - values used before in **this company's own entries** (voided entries and generated reversal
    descriptions are left out);
  - ranked: those that start with what was typed first, then the most used, then the most
    recent;
  - asked for once the user pauses typing (200 ms), at most 20; a failure leaves the field as
    it is.
- **No AI, no outside service, no cost.** Everything is a database query.

## Endpoints
`GET /vat-favourites`, `PUT` and `DELETE /vat-favourites/{vat_code_id}`, `GET /vat-usage`,
`GET /entry-suggestions?field=description|memo|reference&q=…&limit=…`. All need
`ledger.entry.read` on the company.

## Consequences
- Data entry needs fewer keystrokes, and repeated entries are typed the same way each time.
- Suggestions can repeat a past mistake. They are offered, never applied, and the user sees the
  text before saving.
