# ADR-0042: Currency foundation — ISO 4217, transaction/functional/reporting currencies, multi-currency disabled
Status: **Proposed** (M6F-1, #80; awaiting product owner review in PR) · Date: 2026-11-15

## Context
Owner decision D8 (2026-11-15): EUR is the default functional and reporting currency for the first
release; the architecture must be ready for multi-currency (transaction, functional and reporting
currencies, exchange rates, FX gains and losses) without major restructuring later, while
multi-currency transactions stay disabled until their full accounting treatment is implemented and
tested. IAS 21 distinguishes the transaction currency, the functional currency (in which the
entity measures its results) and the presentation (reporting) currency.

## Decision
- **ISO 4217 reference data.** `core_currency` (code, numeric code, minor units) is global,
  read-only for the runtime role and changed only by migrations; it matches
  `fcp.core.money.currency` (a test keeps them equal). A trigger function `core_currency_guard`
  is attached to every currency column (entity functional and reporting currencies, accounts,
  journal entries, transaction currency on lines, bank accounts, obligations, debt instruments,
  exchange rates), so the database refuses any code that is not in the table.
- **Three currencies, stored where they belong.**
  - *Functional* (per legal entity): the amounts every ledger line already stores (`debit`,
    `credit`). Entries are recorded in it (database guard).
  - *Transaction* (per line): `txn_currency`, `txn_debit`, `txn_credit` and `exchange_rate`
    (functional units per transaction unit). All four are empty for a functional-currency line,
    or all set on the same side with a positive rate (check constraint). Empty fields keep every
    existing line, and its content hash, unchanged: no posted data needs rework.
  - *Reporting* (per legal entity): `reporting_currency`, equal to the functional currency in
    this release. Presentation in another currency is a translation at report time (IAS 21.39),
    not stored amounts.
- **Exchange rates as data.** `ledger_exchange_rate` (tenant-owned, FORCE row-level security,
  never changed or deleted): date, base and quote currency, rate, type (spot, closing, average),
  source and source-file hash, who entered it. No live market feed (doc 10 §13).
- **Disabled in this release.** `multi_currency_enabled` is false for every entity and the
  database refuses true (`tenancy_entity_multi_currency_off`). A line with transaction-currency
  fields is refused by the database unless the entity has multi-currency enabled; the API refuses
  an entry whose currency differs from the functional currency with a clear message.
- **FX gains and losses** post to accounts the entity maps to the existing taxonomy line
  `FX.DIFF`; realised and unrealised differences can be split into separate accounts without a
  taxonomy change.
- **Planning values carry the entity's functional currency** as their unit (pinned in each
  projection run), instead of a fixed "EUR".

## Enabling multi-currency later (not in this release)
A later milestone implements and tests: conversion at posting (`debit = round(txn_debit × rate,
minor units, half-up)` with an explicit rounding line within limits); period-end revaluation of
monetary items at closing rates with unrealised FX differences; realised differences on
settlement; translation for a reporting currency; FX in projections. Only then is the database
constraint dropped (a migration) and the switch offered per entity.

## Consequences
- No schema restructuring is needed to add multi-currency; the remaining work is behaviour and
  tests.
- Existing data and hashes are untouched.
- Until then, foreign-currency bank statements and entries are refused, as today.
