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
import { CashForecastPage } from "./pages/CashForecast";

const week = (i: number, closing: string, shortfall = false) => ({
  index: i,
  label: `2026-W${String(44 + i).padStart(2, "0")}`,
  start: `2026-11-${String(2 + 7 * (i - 1)).padStart(2, "0")}`,
  end: `2026-11-${String(8 + 7 * (i - 1)).padStart(2, "0")}`,
  opening: i === 1 ? "10000.00" : "8000.00",
  opening_nature: i === 1 ? "ACTUAL" : "FORECAST",
  inflows: i === 1 ? "500.00" : "0.00",
  outflows: i === 1 ? "2500.00" : "0.00",
  net: i === 1 ? "-2000.00" : "0.00",
  closing,
  minimum: "9000.00",
  headroom: "-1000.00",
  undrawn_facilities: "5000.00",
  liquidity: "13000.00",
  shortfall,
  nature: "FORECAST",
  flows:
    i === 1
      ? [
          {
            direction: "IN",
            category: "CUSTOMERS",
            nature: "COMMITTED",
            amount: "500.00",
          },
          {
            direction: "OUT",
            category: "TAX",
            nature: "EXPECTED",
            amount: "2500.00",
          },
        ]
      : [],
});
const forecast = {
  run_id: "r1",
  status: "VALID",
  as_of: "2026-11-04",
  actuals_watermark: 7,
  stale: true,
  stale_reasons: ["new postings since the forecast was made"],
  created_at: "2026-11-04T10:00:00Z",
  opening_cash: "10000.00",
  overdue: "-2500.00",
  beyond_horizon: "0.00",
  first_shortfall: { date: "2026-11-04", balance: "8000.00" },
  warnings: [
    { code: "unreconciled", message: "Current account: never reconciled" },
  ],
  weeks: [
    week(1, "8000.00", true),
    week(2, "8000.00", true),
    week(3, "9500.00"),
  ],
};
const whatIf = {
  run_id: "r1",
  nature: "HYPOTHETICAL",
  saved: false,
  matched: [1],
  base_first_shortfall: forecast.first_shortfall,
  what_if_first_shortfall: { date: "2026-11-04", balance: "7500.00" },
  hypothetical_total: "500.00",
  weeks: forecast.weeks.map((w) => ({
    label: w.label,
    start: w.start,
    base_closing: w.closing,
    what_if_closing: w.index === 1 ? "7500.00" : w.closing,
    delta: w.index === 1 ? "-500.00" : "0.00",
    base_shortfall: w.shortfall,
    what_if_shortfall: w.shortfall,
  })),
};

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Cash forecast dashboard (M3-10)", () => {
  const calls: { url: string; method: string; body: unknown }[] = [];
  beforeEach(() => {
    calls.length = 0;
    document.cookie = "__Host-fcp_csrftoken=test";
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init: RequestInit) => {
        const method = init.method ?? "GET";
        calls.push({
          url,
          method,
          body: init.body ? JSON.parse(init.body as string) : null,
        });
        if (url.endsWith("/cash-forecasts/latest"))
          return Promise.resolve(respond(forecast));
        if (url.endsWith("/what-if")) return Promise.resolve(respond(whatIf));
        if (url.includes("/cash-forecasts/history")) {
          return Promise.resolve(
            respond([
              {
                run_id: "r1",
                as_of: "2026-11-04",
                created_at: "2026-11-04T10:00:00Z",
                status: "VALID",
                stale: true,
                trigger: "USER",
                opening_cash: "10000.00",
                closing_week_13: "9500.00",
                first_shortfall: "2026-11-04",
              },
            ]),
          );
        }
        if (url.includes("/cash-forecasts/accuracy")) {
          return Promise.resolve(
            respond({
              weeks: [
                {
                  label: "2026-W43",
                  start: "2026-10-19",
                  actual: "400.00",
                  comparisons: [
                    {
                      horizon_weeks: 1,
                      run_id: "r0",
                      forecast: "0.00",
                      error: "-400.00",
                      ape_percent: "100.00",
                    },
                  ],
                },
              ],
              mape_percent: { "1": "100.00", "4": null, "13": null },
              samples: { "1": 1, "4": 0, "13": 0 },
              note: "",
            }),
          );
        }
        if (url.endsWith("/cash-forecast-settings")) {
          return Promise.resolve(
            respond({
              minimum_cash: "9000.00",
              unreconciled_warning_days: 7,
              payables_policy: "DUE_DATE",
              payables_weekday: 4,
            }),
          );
        }
        if (url.endsWith("/calc-runs/r1")) {
          return Promise.resolve(
            respond({
              results: [
                {
                  id: "x1",
                  series_key: "cash.flow",
                  dimensions: ["OUT", "TAX"],
                  period_start: "2026-11-02",
                  nature: "EXPECTED",
                  value: "2500",
                },
              ],
            }),
          );
        }
        if (url.endsWith("/results/x1/explain")) {
          return Promise.resolve(
            respond({
              lineage: [
                {
                  input_kind: "SCHEDULE",
                  input_ref: "tax:abc",
                  amount: "-2500",
                  note: "overdue",
                },
              ],
            }),
          );
        }
        return Promise.resolve(respond({}, 404));
      }),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows weeks with natures, drills down, compares a what-if and stays accessible", async () => {
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider locale="en">
          <MemoryRouter initialEntries={["/w/demo/e/ent/cash-forecast"]}>
            <Routes>
              <Route
                path="/w/:slug/e/:entityId/cash-forecast"
                element={<CashForecastPage />}
              />
            </Routes>
          </MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    );
    expect(
      await screen.findByRole("img", { name: "Cash over the next 13 weeks" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("This forecast is out of date:"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("new postings since the forecast was made"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Current account: never reconciled"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/First shortfall below the minimum on 2026-11-04/),
    ).toBeInTheDocument();
    const table = screen.getByRole("table", { name: /Weeks/ });
    const first = within(table).getByRole("row", { name: /2026-W45/ });
    expect(first).toHaveTextContent("shortfall");
    expect(first).toHaveTextContent("Actual");
    expect(first).toHaveTextContent("Forecast");
    expect(first).toHaveTextContent("-2,500.00");

    fireEvent.click(within(first).getByRole("button", { name: "2026-W45" }));
    const detail = await screen.findByRole("region", {
      name: /Flows in 2026-W45/,
    });
    fireEvent.click(within(detail).getByRole("button", { name: /Tax/ }));
    expect(
      await within(detail).findByText(/Scheduled payment/),
    ).toHaveTextContent("overdue");

    const panel = screen.getByRole("region", { name: "What-if" });
    fireEvent.change(
      within(panel).getByLabelText("Customer or supplier code"),
      { target: { value: "c1" } },
    );
    fireEvent.click(within(panel).getByRole("button", { name: "Add change" }));
    fireEvent.click(
      within(panel).getByRole("button", { name: "Compare with the forecast" }),
    );
    await waitFor(() =>
      expect(calls.some((c) => c.url.endsWith("/what-if"))).toBe(true),
    );
    const sent = calls.find((c) => c.url.endsWith("/what-if"));
    expect(sent?.body).toEqual({
      overrides: [
        {
          type: "TIMING_SHIFT",
          party: "C1",
          category: "",
          days: 30,
          percent: "0",
          day: null,
          amount: "0",
          reason: "",
        },
      ],
    });
    expect(await within(panel).findByText(/Not saved/)).toBeInTheDocument();
    expect(within(panel).getByText("Hypothetical")).toBeInTheDocument();
    expect(
      within(table).getByRole("columnheader", { name: "What-if change" }),
    ).toBeInTheDocument();
    expect(within(first).getByText("-500.00")).toBeInTheDocument();
    expect(
      screen.getByText("What-if, hypothetical (dotted)"),
    ).toBeInTheDocument();

    expect(
      await screen.findByRole("region", { name: "Earlier forecasts" }),
    ).toHaveTextContent("A user");
    expect(
      await screen.findByText(/Average error 1 week\(s\) ahead: 100.00%/),
    ).toBeInTheDocument();

    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => v.id)).toEqual([]);
  });
});
