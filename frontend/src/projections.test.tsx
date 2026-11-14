import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import axe from "axe-core";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { I18nProvider } from "./i18n/I18n";
import { OutlookPage } from "./pages/Outlook";
import { ProjectionsPage } from "./pages/Projections";

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const run = {
  id: "r1",
  status: "VALID",
  as_of_date: "2026-12-31",
  assumption_set_id: "s1",
  actuals_watermark: 7,
  input_hash: "a",
  output_hash: "b",
  invariants: {
    balance_sheet_balances: true,
    cash_ties: true,
    retained_earnings_roll: true,
    opening_equals_previous_closing: true,
    roll_forwards_tie: true,
    aggregation_consistent: true,
  },
  error: "",
  stale: false,
  is_published: false,
  created_at: "2026-11-12T10:00:00Z",
};
const statements = {
  projection: run,
  columns: [
    { start: "2026-12-01", end: "2026-12-31", nature: "ACTUAL" },
    { start: "2027-01-01", end: "2027-01-31", nature: "FORECAST" },
    { start: "2027-02-01", end: "2027-02-28", nature: "FORECAST" },
  ],
  rows: {
    "PL.REVENUE": [null, "1320.00", "1210.00"],
    "PL.COGS": [null, "459.13", "420.87"],
    "BS.CASH": ["100.00", "900.00", "1500.00"],
    "BS.TOTAL_ASSETS": ["400.00", "1300.00", "1900.00"],
  },
  failures: [],
  result_ids: {
    "PL.REVENUE": [null, "x1", "x2"],
    "PL.COGS": [null, "x3", "x4"],
    "BS.CASH": ["x5", "x6", "x7"],
  },
};
const set = {
  id: "s1",
  family_id: "f1",
  version: 1,
  name: "Plan 2027",
  cutover: "2026-12-31",
  months: 12,
  start_from: "ACTUALS",
  note: "",
  status: "APPROVED",
  supersedes_id: null,
  created_at: "2026-11-12T00:00:00Z",
  approved_at: "2026-11-12T00:00:00Z",
};
const rolling = {
  configured: true,
  family_id: "f1",
  assumption_set_id: "s1",
  horizon: 12,
  active: true,
  latest: { ...run, id: "r2", as_of_date: "2026-10-31" },
  stale: true,
  stale_reasons: ["new postings since the forecast was made"],
  history: [],
};
const accuracy = [
  {
    month: "2026-10-01",
    actual: { "PL.REVENUE": "1000.00" },
    comparisons: {
      "PL.REVENUE": [
        {
          months_before: 1,
          run_id: "r0",
          forecast: "1200.00",
          error: "200.00",
          error_pct: "20.00",
        },
      ],
      "PL.EBITDA": [],
      "BS.CASH": [],
    },
  },
];

function mount(path: string, route: string, element: ReactElement) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <I18nProvider locale="en">
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path={route} element={element} />
          </Routes>
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("Projections (M6-6)", () => {
  it("shows natures, the checks, explains a line, publishes and keeps a rolling forecast", async () => {
    const sent: { url: string; method: string }[] = [];
    document.cookie = "__Host-fcp_csrftoken=test";
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init: RequestInit) => {
        const method = init.method ?? "GET";
        if (method !== "GET") {
          sent.push({ url, method });
          return Promise.resolve(
            respond(url.includes("rolling") ? rolling : run),
          );
        }
        if (url.includes("/explain"))
          return Promise.resolve(
            respond({
              lineage: [
                {
                  input_kind: "ASSUMPTION",
                  input_ref: "assumption_set:s1:gross_margin:2027-01",
                  amount: null,
                  note: "cost of sales = sales and services x (100% - gross margin)",
                },
              ],
            }),
          );
        if (url.includes("/rolling-forecast/accuracy"))
          return Promise.resolve(respond(accuracy));
        if (url.includes("/rolling-forecast"))
          return Promise.resolve(respond(rolling));
        if (url.includes("/projections/r1"))
          return Promise.resolve(respond(statements));
        if (url.includes("/projections"))
          return Promise.resolve(respond([run]));
        return Promise.resolve(respond([set]));
      }),
    );
    const { container } = mount(
      "/w/ws/e/e1/projections",
      "/w/:slug/e/:entityId/projections",
      <ProjectionsPage />,
    );
    const bs = await screen.findByRole("table", {
      name: "Projected balance sheet",
    });
    // Nature in words on every column, the opening first.
    const natureRow = within(bs).getByRole("row", { name: /Nature/ });
    expect(within(natureRow).getAllByText("Actual")).toHaveLength(1);
    expect(within(natureRow).getAllByText("Forecast")).toHaveLength(2);
    expect(
      within(bs).getByRole("columnheader", { name: "Opening" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Assets equal liabilities plus equity"),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/✓ holds/)).toHaveLength(6);
    // The income statement has no opening column.
    const is = screen.getByRole("table", {
      name: "Projected income statement",
    });
    expect(within(is).queryByText("Opening")).toBeNull();
    fireEvent.click(
      within(is).getByRole("button", { name: "Explain Cost of sales 2027-01" }),
    );
    expect(
      await screen.findByText(/cost of sales = sales and services/),
    ).toBeInTheDocument();
    // A chart with a text description; the table above holds the figures.
    expect(
      screen.getByRole("img", { name: "Cash at the end of each period" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Export to Excel" }),
    ).toHaveAttribute(
      "href",
      "/api/w/ws/entities/e1/projections/r1/export?granularity=MONTH",
    );
    fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    await waitFor(() =>
      expect(sent[0]?.url).toBe("/api/w/ws/entities/e1/calc-runs/r1/publish"),
    );
    // Rolling forecast: stale with its reason, refresh, and accuracy.
    expect(
      await screen.findByText(/new postings since the forecast was made/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh now" }));
    await waitFor(() =>
      expect(sent[1]?.url).toBe(
        "/api/w/ws/entities/e1/rolling-forecast/refresh",
      ),
    );
    const acc = await screen.findByRole("table", {
      name: "Forecast against actual for closed months",
    });
    expect(within(acc).getByText("20.00%")).toBeInTheDocument();
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations).toEqual([]);
  });
});

describe("Full-year outlook (M6-6)", () => {
  it("marks each column's nature and the divider", async () => {
    const months = Array.from(
      { length: 12 },
      (_, i) => `2026-${String(i + 1).padStart(2, "0")}-01`,
    );
    const columns = [
      ...months.map((m, i) => ({
        start: m,
        end: m.replace(/01$/, "28"),
        granularity: "MONTH",
        nature: i < 6 ? "ACTUAL" : "FORECAST",
      })),
      ...[0, 3, 6, 9].map((q) => ({
        start: months[q],
        end: months[q + 2],
        granularity: "QUARTER",
        nature: q < 6 ? "ACTUAL" : "FORECAST",
      })),
      {
        start: months[0],
        end: "2026-12-31",
        granularity: "YEAR",
        nature: "ACTUAL+FORECAST",
      },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          respond({
            year_start: "2026-01-01",
            cutover: "2026-06-30",
            projection_id: "r1",
            note: "Actuals to 30/06/2026, then the published projection of 12/11/2026.",
            columns,
            rows: {
              "PL.REVENUE": [
                ...Array(12).fill("100.00"),
                "300.00",
                "300.00",
                "300.00",
                "300.00",
                "1200.00",
              ],
            },
          }),
        ),
      ),
    );
    const { container } = mount(
      "/w/ws/e/e1/outlook",
      "/w/:slug/e/:entityId/outlook",
      <OutlookPage />,
    );
    const table = await screen.findByRole("table", {
      name: /Full-year outlook 2026/,
    });
    expect(screen.getByText(/Actuals to 30\/06\/2026/)).toBeInTheDocument();
    expect(within(table).getByText("Actual + Forecast")).toBeInTheDocument();
    expect(within(table).getAllByText("Forecast")).toHaveLength(8);
    const june = within(table).getByRole("columnheader", { name: "2026-06" });
    expect(june).toHaveClass("divider-after");
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations).toEqual([]);
  });
});
