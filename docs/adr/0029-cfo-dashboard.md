# ADR-0029: The CFO dashboard reads reports and runs; one request per period
Status: **Proposed** (M4-8; awaiting product owner review in PR) · Date: 2026-11-10

## Context
Doc 10 §10 and AC-DB1 to AC-DB5 ask for a dashboard with these properties:
- widgets for KPIs, cash, budget vs actual, goals, alerts and the top variances;
- period presets and comparisons that update every widget consistently, with widget values equal
  to the reports;
- the nature visual contract, in light and dark themes;
- drill-down within permissions, with clear denials;
- table alternatives, WCAG 2.2 AA, and an initial load p95 under 1.5 s on a 3-year fixture.

## Decision
- **One request, one period.**
  - `GET dashboard?preset&month&comparison` builds every widget of the user's layout for one
    period.
  - The period follows the entity's fiscal year, as the variance report does.
  - The comparison is the budget or the prior year, so every widget shows the same period
    (AC-DB4).
- **No copies.** Widgets read the latest KPI set, the latest 13-week forecast, the variance
  report, goal evaluations and alerts. Opening the page never starts a calculation.
  `POST dashboard/refresh` calculates the KPI sets the period needs and checks the budgets for
  alerts, on request.
- **Permission-aware widgets.** Each widget is `ok`, `empty` with a reason, or `denied`. A widget
  the user may not see does not fail the page (AC-DB3).
  - Drill-down goes to the existing pages: KPI → accounts → entries; budgets; goals; cash; alerts.
    Each enforces its own permissions.
- **Layouts.** `dashboards_layout` holds one row per user and one default per entity (no user). A
  layout is the widgets in order, plus the KPI keys for the cards.
  - Anyone who can read the dashboard can save their own layout.
  - Setting the default needs `dashboard.manage_default` (sign-off roles).
- **Charts stay SVG drawn in React**, with no new dependency, as in M3.
  - Every nature has a non-colour encoding: the actual is a solid point, the forecast a dashed
    line, the minimum a thin reference line.
  - Every chart has a text description and a table with the same numbers.
  - Colours come from the theme variables, so the light and dark themes keep the same encodings.
  - Doc 10 names Apache ECharts; staying with SVG is listed for owner confirmation.

## Consequences
- Tests prove the AC-DB4 equality: the budget rows equal the variance report line for line, and
  the KPI cards equal the KPI set.
- The AC-DB5 check runs in CI on a 3-year fixture of monthly activity.
- AC-DB1 "visual snapshot tests" are structural tests of the encodings in the frontend suite, plus
  light and dark screenshots in the live check. Pixel snapshots in CI would need a pinned browser
  image and are listed as an owner decision.
- The comparison with a forecast waits for rolling P&L forecasts (M6). The 13-week cash widget
  already shows the forecast nature.
