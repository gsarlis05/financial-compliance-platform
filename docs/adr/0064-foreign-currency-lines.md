# ADR-0064: Foreign-currency lines converted at the rate of the transaction's date and time
Status: **Accepted** (V1-2h, #219) · Date: 2026-11-23 · Builds on ADR-0042

## Context
ADR-0042 laid the foundation: the ISO 4217 table, a transaction currency, amount and rate on
each journal line, and exchange rates recorded with their source. Entries in another currency
were refused until conversion was built.

The owner buys in other currencies, for example by card in US dollars, and decided on
23 November 2026: **a foreign amount is converted to euros at the exchange rate of the date and
time the purchase happened.** That rate is usually the one on the bank or card statement, not a
published daily rate. So the platform records the rate the user gives, with when it applied and
where it came from.

## Decision
- **Switched on per entity.** Ledger settings → Foreign currency.
  - Turning it on needs an income or expense account for exchange differences. The default
    chart has 7020 "Foreign exchange differences", mapped to `FX.DIFF`.
  - The change is audited (`ledger.currency_settings.updated`). The database constraint that
    kept foreign currency off is removed; the service now decides.
- **Each foreign line** carries:
  - the currency and the amount in that currency;
  - the rate in euros per unit;
  - the rate's date and time (`rate_at`);
  - its source (`rate_source`, for example "bank card statement").
- **The euro amount is checked, not computed silently.** It must equal the foreign amount × rate,
  rounded half up to the cent. The form fills it in as you type; the server and a database
  constraint refuse a line whose rate has no date and time or no source.
- **Stored rates help but never decide.** "Use the stored rate" offers the latest recorded rate
  on or before the entry date (spot first, either direction, to 10 decimals). The user can
  overwrite it with the statement's rate.
- **Hashes, reversals and corrections** include the foreign fields. A reversal mirrors the
  original's currency, amount and rate, so it cancels exactly in both currencies.
- **VAT.** The return is in euros. Each line in the report keeps its original currency, amount,
  rate, date and time and source; the CSV export has them; the report states the conversion
  policy whenever a line is foreign.

## Not in this decision
Exchange differences — revaluing open foreign balances at the period end and the realised
difference when a foreign invoice is paid at another rate — follow in #230. Until then, a payment
at another rate shows the difference on the receivable or payable account for the user to clear.

Whether the VAT law requires a particular rate for VAT (for example a published rate on the tax
point) is on the professional review list (#93).

## Consequences
- The amounts in the books always come from a rate the user can show evidence for.
- Turning foreign currency on needs no change to recorded data (ADR-0042's columns).
