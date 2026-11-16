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
import { KpisPage, period } from "./pages/Kpis";

const value = (key: string, display: string, v: string | null, nm = "") => ({
  result_id: `r-${key}`,
  definition_id: `CORE@1.0:${key}`,
  key,
  name:
    key === "DSO"
      ? "Days sales outstanding"
      : key === "GROSS_MARGIN"
        ? "Gross margin"
        : "Cash runway",
  name_el: "",
  category:
    key === "DSO"
      ? "EFFICIENCY"
      : key === "GROSS_MARGIN"
        ? "PROFITABILITY"
        : "LIQUIDITY",
  display,
  direction: key === "DSO" ? "LOWER_BETTER" : "HIGHER_BETTER",
  convention: "Average receivables over revenue, times the days in the period.",
  nature: "ACTUAL",
  value: v,
  unit: "ratio",
  nm_reason: nm,
  non_ledger: key === "CASH_RUNWAY",
});
const set = {
  run_id: "run1",
  status: "VALID",
  stale: false,
  library: "CORE@1.0",
  date_from: "2026-01-01",
  date_to: "2026-03-31",
  actuals_watermark: 12,
  created_at: "2026-11-04T10:00:00Z",
  unmapped_accounts: 1,
  values: [
    value("GROSS_MARGIN", "percent", "0.4"),
    value("DSO", "days", "22.5"),
    value(
      "CASH_RUNWAY",
      "months",
      null,
      "Not burning cash: it did not decrease",
    ),
  ],
};

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("KPIs (M4-4)", () => {
  it("builds whole-month periods for the presets", () => {
    expect(period("YTD", "2026-03")).toEqual({
      date_from: "2026-01-01",
      date_to: "2026-03-31",
    });
    expect(period("QUARTER", "2026-05")).toEqual({
      date_from: "2026-04-01",
      date_to: "2026-05-31",
    });
    expect(period("LTM", "2026-03")).toEqual({
      date_from: "2025-04-01",
      date_to: "2026-03-31",
    });
    expect(period("MONTH", "2028-02")).toEqual({
      date_from: "2028-02-01",
      date_to: "2028-02-29",
    });
  });

  it("calculates, shows natures and reasons, drills down to entries, and stays accessible", async () => {
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
        if (url.includes("/kpi-sets/latest"))
          return Promise.resolve(
            respond(
              { status: 404, code: "not_found", detail: "No KPI set" },
              404,
            ),
          );
        if (url.endsWith("/kpi-sets/run1/personal"))
          return Promise.resolve(
            respond([
              {
                key: "MARKUP",
                definition_id: "PERSONAL:MARKUP@1",
                name: "My mark-up",
                display: "ratio",
                direction: "HIGHER_BETTER",
                nature: "ACTUAL",
                value: "1.6666",
                unit: "ratio",
                nm_reason: "",
                non_ledger: false,
              },
            ]),
          );
        if (url.endsWith("/kpi-sets"))
          return Promise.resolve(respond(set, 201));
        if (url.endsWith("/kpi-definitions"))
          return Promise.resolve(
            respond([
              {
                id: "CORE@1.0:DSO",
                key: "DSO",
                formula: 'avg_balance("BS.AR") / flow("REVENUE") * days()',
                nm_note: "Not meaningful when revenue is zero.",
                example: "10 days.",
              },
            ]),
          );
        if (url.endsWith("/results/r-DSO/explain"))
          return Promise.resolve(
            respond({
              lineage: [
                {
                  input_kind: "ACTUAL",
                  input_ref: "account:a1:closing",
                  amount: "500",
                  note: "",
                },
              ],
            }),
          );
        if (url.endsWith("/accounts"))
          return Promise.resolve(
            respond([{ id: "a1", code: "1200", name: "Trade receivables" }]),
          );
        if (url.includes("/reports/general-ledger/a1"))
          return Promise.resolve(
            respond({
              lines: [
                {
                  entry_id: "e1",
                  entry_ref: "GJ-1",
                  accounting_date: "2026-01-15",
                  description: "Invoice",
                  memo: "",
                  debit: "1000.00",
                  credit: "0.00",
                  running_balance: "1000.00",
                  restated_after_lock: false,
                },
              ],
            }),
          );
        return Promise.resolve(respond({}, 404));
      }),
    );
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider locale="en">
          <MemoryRouter initialEntries={["/w/demo/e/ent/kpis"]}>
            <Routes>
              <Route path="/w/:slug/e/:entityId/kpis" element={<KpisPage />} />
            </Routes>
          </MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    );
    expect(
      await screen.findByText(/No KPIs for this period yet/),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Ending in"), {
      target: { value: "2026-03" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Calculate KPIs" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({
        date_from: "2026-01-01",
        date_to: "2026-03-31",
      }),
    );
    const gross = (
      await screen.findByRole("heading", { name: "Gross margin" })
    ).closest("li");
    expect(gross).toHaveTextContent("40.00%");
    expect(gross).toHaveTextContent("Actual · higher is better");
    const dso = screen
      .getByRole("heading", { name: "Days sales outstanding" })
      .closest("li");
    expect(dso).toHaveTextContent("22.50 days");
    const runway = screen
      .getByRole("heading", { name: "Cash runway" })
      .closest("li");
    expect(runway).toHaveTextContent("Not meaningful");
    expect(runway).toHaveTextContent("Not burning cash");
    expect(screen.getByText(/no taxonomy line/)).toHaveTextContent("1");
    expect(runway).toHaveTextContent("Includes data not from the ledger");
    const personal = await screen.findByRole("region", {
      name: "Your personal KPIs",
    });
    expect(personal).toHaveTextContent("My mark-up");
    expect(personal).toHaveTextContent("1.67");

    if (!dso) throw new Error("no DSO card");
    fireEvent.click(
      within(dso).getByRole("button", { name: /How is this computed/ }),
    );
    const parts = await screen.findByRole("table", {
      name: "Accounts behind this value",
    });
    const row = await within(parts).findByRole("row", {
      name: /1200 · Trade receivables/,
    });
    expect(row).toHaveTextContent("closing balance");
    expect(row).toHaveTextContent("500.00");
    fireEvent.click(within(row).getByRole("button", { name: /Entries/ }));
    expect(await screen.findByText(/GJ-1 · Invoice/)).toBeInTheDocument();
    expect(screen.getByText(/avg_balance/)).toBeInTheDocument();

    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => v.id)).toEqual([]);
    vi.unstubAllGlobals();
  });
});
