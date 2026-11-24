# ADR-0066: Exchange differences on foreign-currency positions, as draft entries
Status: **Accepted** (V1-2h2, #230) · Date: 2026-11-23 · Builds on ADR-0042 and ADR-0064

## Context
Since V1-2h (ADR-0064), lines in another currency are converted at the rate of the transaction's
date and time. A dollar invoice owed or a dollar bank balance keeps that rate until it is
revalued or settled. IAS 21 asks for monetary items to be translated at the closing rate at each
period end, with the difference in profit or loss, and for the difference on settlement to be
recognised too. Non-monetary items (an expense, an asset bought) stay at the historical rate.

## Decision
- **A position** is the posted foreign-currency lines of one monetary account, counterparty and
  currency on or before a date. Monetary accounts are:
  - receivable and payable control accounts;
  - accounts kept in a foreign currency (the account's currency is set), such as a dollar bank
    account.

  The position's foreign balance is the sum of the lines' foreign amounts. Its euro balance is
  the sum of their euro amounts, including earlier exchange differences.
- **Unrealised difference:** an open position revalued at the **closing rate** stored for the
  date (closing rates first, then the latest rate on or before it). The difference is the
  foreign balance times the rate, rounded half up to the cent, minus the euro balance. Because
  earlier differences are in the euro balance, each revaluation adds only what changed; no
  reversal at the start of the next period is needed.
- **Realised difference:** a position whose foreign balance is zero but whose euro balance is
  not is cleared. Unrealised amounts recognised earlier are not reclassified; both kinds go to
  the same account.
- **No rate, no guess.** A currency with no stored rate is listed as missing and its positions
  are left out of the draft.
- **One draft entry** against the exchange-differences account from Ledger settings (7020 in
  the Cyprus template). It has one line per position and one total line per kind. It follows the
  normal approval and posting. A new draft is refused while an earlier one is waiting, so a
  difference is never booked twice.
- **Exchange-difference lines** (`fx_difference` UNREALISED or REALISED) keep the position's
  currency with a zero foreign amount. An unrealised line has the rate it was revalued at; a
  realised line has none. The database shape constraint allows exactly these forms. They are
  hashed and mirrored by reversals like any line.

## Not in this decision
- How exchange differences are treated for tax is on the professional review list (#93). The
  platform makes no tax adjustment.
- Translating the statements into another presentation currency is not needed: the functional
  and presentation currencies are both euros.

## Consequences
- The books carry foreign balances at the closing rate after each revaluation, with the
  evidence of the rate used.
- The user decides when to revalue and approves every entry.
