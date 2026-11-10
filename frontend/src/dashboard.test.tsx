import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import axe from "axe-core";
import { MemoryRouter, Route, Routes } from "react-router";
import { I18nProvider } from "./i18n/I18n";
import { DashboardPage, formatCard, lastMonth } from "./pages/Dashboard";

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const board = {
  period: {
    preset: "YTD",
    month: "2026-03-01",
    date_from: "2026-01-01",
    date_to: "2026-03-31",
    fiscal_year_start: "2026-01-01",
    comparison: "BUDGET",
  },
  layout_source: "BUILT_IN",
  widgets: [
    {
      type: "kpis",
      status: "ok",
      reason: "",
      options: { kpis: ["GROSS_MARGIN", "DSO"] },
      data: {
        run_id: "r1",
        stale: false,
        cards: [
          {
            key: "GROSS_MARGIN",
            name: "Gross margin",
            name_el: "",
            display: "percent",
            direction: "HIGHER_BETTER",
            result_id: "x1",
            value: "0.4",
            nm_reason: "",
            nature: "ACTUAL",
            comparison_value: null,
          },
          {
            key: "DSO",
            name: "Days sales outstanding",
            name_el: "",
            display: "days",
            direction: "LOWER_BETTER",
            result_id: "x2",
            value: null,
            nm_reason: "Revenue is zero",
            nature: "ACTUAL",
            comparison_value: null,
          },
        ],
      },
    },
    {
      type: "cash",
      status: "ok",
      reason: "",
      options: {},
      data: {
        run_id: "c1",
        as_of: "2026-03-31",
        stale: false,
        opening: "2400.00",
        first_shortfall: null,
        weeks: [
          {
            label: "2026-W14",
            start: "2026-03-30",
            end: "2026-04-05",
            closing: "2300.00",
            minimum: "1000.00",
          },
          {
            label: "2026-W15",
            start: "2026-04-06",
            end: "2026-04-12",
            closing: "2500.00",
            minimum: "1000.00",
          },
        ],
      },
    },
    {
      type: "budget",
      status: "denied",
      reason: "You do not have permission to see this.",
      options: {},
      data: {},
    },
    {
      type: "top_variances",
      status: "ok",
      reason: "",
      options: {},
      data: {
        budget_name: "Plan 2026",
        top: [
          {
            line: "REV.SALES",
            dimension_value_id: null,
            direction: "HIGHER_BETTER",
            actual: "1000.00",
            actual_nature: "ACTUAL",
            comparison: "3000.00",
            comparison_nature: "BUDGET",
            variance: "-2000.00",
            percent: "-66.67",
            favourable: false,
            requires_explanation: true,
          },
        ],
      },
    },
    {
      type: "goals",
      status: "empty",
      reason: "No goals yet.",
      options: {},
      data: {},
    },
    {
      type: "alerts",
      status: "ok",
      reason: "",
      options: {},
      data: {
        warning: 0,
        critical: 1,
        latest: [
          {
            id: "a1",
            title: "Goal Revenue is off track",
            severity: "CRITICAL",
            kind: "GOAL_STATUS",
            created_at: "2026-03-31T10:00:00Z",
          },
        ],
      },
    },
  ],
};

describe("CFO dashboard (M4-8)", () => {
  it("formats cards and picks the last complete month", () => {
    expect(formatCard("0.4", "percent", "en")).toBe("40.00%");
    expect(formatCard("22.5", "days", "en")).toBe("22.50");
    expect(lastMonth(new Date(Date.UTC(2026, 0, 15)))).toBe("2025-12-01");
  });

  it("renders every widget with the nature contract, refreshes and saves a layout", async () => {
    const calls: { url: string; method: string; body: unknown }[] = [];
    document.cookie = "__Host-fcp_csrftoken=test";
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init: RequestInit) => {
        const method = init.method ?? "GET";
        calls.push({
          url,
          method,
          body: typeof init.body === "string" ? JSON.parse(init.body) : null,
        });
        if (url.includes("/dashboard/refresh"))
          return Promise.resolve(respond({ kpi_sets: 1, alerts_raised: 0 }));
        if (url.includes("/dashboard-layout"))
          return Promise.resolve(respond({ widgets: [], source: "USER" }));
        if (url.includes("/dashboard?")) return Promise.resolve(respond(board));
        return Promise.resolve(
          respond({ status: 404, code: "not_found", detail: "x" }, 404),
        );
      }),
    );
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider locale="en">
          <MemoryRouter initialEntries={["/w/demo/e/ent/dashboard"]}>
            <Routes>
              <Route
                path="/w/:slug/e/:entityId/dashboard"
                element={<DashboardPage />}
              />
            </Routes>
          </MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    );
    const kpis = await screen.findByRole("region", { name: "KPIs" });
    // AC-DB2: every card states its nature.
    expect(kpis).toHaveTextContent("Gross marginActual40.00%");
    expect(kpis).toHaveTextContent("Revenue is zero");
    expect(
      screen.getByRole("region", { name: "Budget vs actual" }),
    ).toHaveTextContent("You do not have permission to see this widget.");
    expect(screen.getByRole("region", { name: "Goals" })).toHaveTextContent(
      "No goals yet.",
    );
    const top = screen.getByRole("region", {
      name: "Top unfavourable variances",
    });
    expect(within(top).getByRole("table")).toHaveTextContent("▼ Unfavourable");

    // Visual contract (doc 10 §10.1): each nature has its own non-colour encoding, and the chart
    // has a text description and a table with the same numbers.
    const cash = screen.getByRole("region", { name: "13-week cash" });
    const svg = cash.querySelector("svg");
    expect(svg?.querySelector('[data-nature="ACTUAL"]')?.tagName).toBe(
      "circle",
    );
    expect(
      svg?.querySelector('[data-nature="FORECAST"]')?.getAttribute("class"),
    ).toBe("chart-forecast");
    expect(svg?.querySelector('[data-encoding="reference"]')).not.toBeNull();
    // AC-DB2: the cut-over (the forecast's as-of date) is marked on the chart.
    expect(svg?.querySelector('[data-encoding="cut-over"]')).not.toBeNull();
    expect(svg).toHaveTextContent("As of 2026-03-31");
    expect(within(cash).getByRole("img")).toHaveAccessibleName(
      "Opening cash 2,400.00; week 13 closing 2,500.00.",
    );
    expect(
      within(cash).getByRole("table", { name: "13-week cash by week" }),
    ).toHaveTextContent("2026-W15Forecast2,500.00");

    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => v.id)).toEqual([]);

    fireEvent.change(screen.getByLabelText("Compare with"), {
      target: { value: "PRIOR_YEAR" },
    });
    await waitFor(() =>
      expect(calls.some((c) => c.url.includes("comparison=PRIOR_YEAR"))).toBe(
        true,
      ),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Calculate KPIs and check budgets" }),
    );
    await waitFor(() =>
      expect(
        calls.find((c) => c.url.includes("/dashboard/refresh"))?.body,
      ).toMatchObject({
        preset: "YTD",
        comparison: "PRIOR_YEAR",
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Customise" }));
    const form = screen.getByRole("region", { name: "Customise" });
    fireEvent.click(within(form).getByLabelText("Alerts"));
    fireEvent.click(
      within(form).getByRole("button", { name: "Move up 13-week cash" }),
    );
    fireEvent.change(within(form).getByLabelText(/KPI cards/), {
      target: { value: "dso, roe" },
    });
    fireEvent.click(
      within(form).getByRole("button", { name: "Save my layout" }),
    );
    await waitFor(() =>
      expect(
        calls.find(
          (c) => c.url.endsWith("/dashboard-layout") && c.method === "PUT",
        )?.body,
      ).toEqual({
        widgets: [
          { type: "cash" },
          { type: "kpis", kpis: ["DSO", "ROE"] },
          { type: "budget" },
          { type: "top_variances" },
          { type: "goals" },
        ],
      }),
    );
    vi.unstubAllGlobals();
  });
});
