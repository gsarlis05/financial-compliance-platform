# Management report packs

A report pack is the monthly (or quarterly, or yearly) management pack you send to the owner or the
board: statements, budget performance, KPIs, cash, the forecast and goals, with your commentary.
**Its figures are frozen when you generate it**, so it reads the same in a year as on the day it
was made.

The Excel and PDF exports and the screens follow in later releases (M8-3 to M8-6); everything below
is available through the API.

## Generating a pack
Choose a period (a month, or the fiscal quarter or fiscal year that contains a month) and generate.
The pack takes, at that moment and **with your own permissions**:
- the income statement, balance sheet and cash flow for the period, with the same period a year
  earlier;
- budget performance: the current approved annual budget against actual for the month, quarter to
  date, year to date and full year, against the original budget and against the prior year, with
  each variance's explanation;
- the KPI set for the period, the latest 13-week cash forecast, the latest published projection
  for the next 12 months (marked **pending professional review**) and your goals.

A part you may not see is left out and says so; a part without data says why (for example "No KPI
set for this period yet"). The pack records the last posting it includes and the runs it used.

## Sections and comparison columns
A pack has up to ten sections, in the order you choose: executive overview, revenue and
profitability, cash flow (with the 13-week forecast), financial position and working capital (with
the working-capital KPIs), budget performance, KPI scorecard, forecast (the published projection,
marked pending professional review), risks, goal progress and commentary.

**Comparison columns:** actual is always shown. Add any of budget (the current approved budget),
original budget, prior year and variance (the variance, its percentage, whether it is favourable,
and its explanation). "Forecast" adds the full-year outlook to budget performance: actual months
plus the budget for the rest of the year.

Budget performance has a table for the pack's period and for each longer view after it (a March
pack: the month, the quarter to date and the year to date, and the full-year outlook). For a cost,
spending below budget is favourable.

Every figure says what it is: actual, budget, blended (actual plus budget) or forecast.

## Commentary and risks
Write a comment for any section, and keep a short list of risks with an owner, a status (open,
monitoring or closed) and the mitigation. They are written by people; nothing is generated.
Earlier texts are kept. Commentary and risks change only while the pack is a draft, so a pack in
review or final keeps exactly what was reviewed. A new version starts with the commentary and
risks of the version it corrects.

## Review and sign-off
1. The preparer **submits** the draft. Until then it can be **regenerated** (the figures are taken
   again) or retitled.
2. A reviewer (owner, partner or finance manager) **returns** it with a note, or **finalises** it.
   The person who prepared a pack can never finalise it.
3. Finalising is refused, with what to do, while:
   - a variance above the budget's thresholds has no explanation in the pack: explain it in the
     budget review, return the pack to draft and regenerate it;
   - entries dated in or before the period were posted after the pack was generated, so its
     figures have changed: return it and regenerate it.
   Entries for later months never block a pack.

A **final** pack never changes and is never deleted. To correct it, start a **new version**: a new
draft with figures taken now. When the new version is finalised, the earlier one is marked
**superseded** and stays readable.

## Who can do what
| Action | Read only | Accountant | Finance manager, partner, owner |
|---|---|---|---|
| See packs | ✔ | ✔ | ✔ |
| Generate, regenerate, retitle, submit, new version | | ✔ | ✔ |
| Return or finalise (not your own) | | | ✔ |

Every step is recorded in the audit trail.
