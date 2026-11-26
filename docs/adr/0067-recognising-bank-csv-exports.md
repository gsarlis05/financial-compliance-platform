# ADR-0067: Recognising a bank's CSV export from the file itself
Status: **Accepted** (R-1, #244; brief 26) · Date: 2026-11-26

## Context
The owner banks with Bank of Cyprus, Hellenic Bank, Eurobank Cyprus and Revolut Business, and
wants their statements imported without setting columns by hand. The developer cannot see these
banks' real export files, and the project's rule is that nothing is invented: a hard-coded
layout per bank would be a guess presented as fact.

## Decision
- **The file is the source.** On upload, the import reads the file and works out:
  - the encoding (UTF-8, then Windows Greek when Greek letters appear, else Latin-1);
  - the delimiter (`,`, `;`, tab, `|`);
  - the header row, after up to 30 lines of account details;
  - which column is which, from the header names in English and Greek, compared without case,
    accents or punctuation. The names are data (`banking/headers.json`) and grow when a real
    export uses another;
  - the decimal separator and the date format, from the values.
- **Open questions, not guesses.** When the values fit more than one reading (every date fits
  both day-month and month-day; amounts with no decimals), the result carries a question with the
  options, and the screen asks.
- **Bank presets only break ties** (day-first; a decimal separator when the values do not
  decide). They never choose a column. Each is marked `TO_BE_CONFIRMED` until it has been checked
  against a real, anonymised export.
- **Nothing is imported by recognising.** `POST .../csv-detect` returns the layout, the questions
  and a preview. The user saves the layout as the account's mapping, and imports as before
  (unchanged pipeline: size limit, scanning, de-duplication, background parsing).
- The saved mapping gains `skip_rows`; date formats with a time and with two-digit years are read.

## Consequences
- Any bank whose export names its columns in English or Greek imports without manual set-up.
- A file with no recognisable header is refused with a clear message; the columns can still be
  set by hand through the mapping.
