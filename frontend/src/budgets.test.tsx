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
import { BudgetsPage } from "./pages/Budgets";

const months = Array.from(
  { length: 12 },
  (_, i) => `2026-${String(i + 1).padStart(2, "0")}-01`,
);
const version = (id: string, number: number, status: string) => ({
  id,
  number,
  status,
  reason: number > 1 ? "New customer" : "",
  supersedes_id: number > 1 ? "v1" : null,
  content_hash: "",
  created_by_id: "u1",
  submitted_by_id: null,
  submitted_at: null,
  approved_by_id: null,
  approved_at: status === "DRAFT" ? null : "2026-11-04T10:00:00Z",
  sod_applied: null,
  locked_at: null,
  superseded_at: null,
});
const budget = {
  id: "b1",
  name: "Budget 2026",
  kind: "ANNUAL",
  fiscal_year_id: "fy1",
  fiscal_year_start: "2026-01-01",
  fiscal_year_end: "2026-12-31",
  dimension_value_id: null,
  original_version_id: "v1",
  current_version_id: "v1",
  open_version_id: "v2",
  versions: [version("v1", 1, "APPROVED"), version("v2", 2, "DRAFT")],
};
const line = (amount: string) => ({
  id: "l1",
  seq: 1,
  taxonomy_code: "REV.SALES",
  taxonomy_name: "Sales",
  direction: "HIGHER_BETTER",
  account_id: null,
  dimension_value_id: null,
  method: "MANUAL",
  note: "",
  nature: "BUDGET",
  amounts: months.map(() => amount),
  quarters: ["300.00", "300.00", "300.00", "300.00"],
  total: "1200.00",
});
const detail = (id: string, number: number, status: string) => ({
  ...version(id, number, status),
  budget_id: "b1",
  months,
  lines: [line("100.00")],
  month_totals: months.map(() => "100.00"),
  total: "1200.00",
});

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Budgets (M4-1)", () => {
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
        if (url.endsWith("/fiscal-years"))
          return Promise.resolve(
            respond([
              {
                id: "fy1",
                name: "FY2026",
                start_date: "2026-01-01",
                end_date: "2026-12-31",
                status: "OPEN",
                periods: [],
              },
            ]),
          );
        if (url.includes("/budgets?"))
          return Promise.resolve(respond([budget]));
        if (url.endsWith("/budgets/b1/events"))
          return Promise.resolve(
            respond([
              {
                version_number: 1,
                seq: 1,
                action: "APPROVED",
                actor_id: "u2",
                actor_name: "Mo Manager",
                comment: "Fine",
                at: "2026-11-04T10:00:00Z",
              },
            ]),
          );
        if (url.endsWith("/budget-settings"))
          return Promise.resolve(respond({ sod_required: true }));
        if (url.endsWith("/budget-versions/v2/lines"))
          return Promise.resolve(respond(detail("v2", 2, "DRAFT")));
        if (url.endsWith("/budget-versions/v2"))
          return Promise.resolve(respond(detail("v2", 2, "DRAFT")));
        if (url.endsWith("/budget-versions/v1"))
          return Promise.resolve(respond(detail("v1", 1, "APPROVED")));
        if (url.endsWith("/taxonomy"))
          return Promise.resolve(
            respond([
              {
                code: "REV.SALES",
                name: "Sales",
                name_el: "",
                statement: "PL",
                section: "REVENUE",
                account_types: ["INCOME"],
                direction: "HIGHER_BETTER",
                order: 1,
              },
            ]),
          );
        if (url.endsWith("/accounts") || url.endsWith("/dimensions"))
          return Promise.resolve(respond([]));
        return Promise.resolve(respond({}, 404));
      }),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  it("edits a draft, shows the approved original and the trail, and stays accessible", async () => {
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider locale="en">
          <MemoryRouter initialEntries={["/w/demo/e/ent/budgets"]}>
            <Routes>
              <Route
                path="/w/:slug/e/:entityId/budgets"
                element={<BudgetsPage />}
              />
            </Routes>
          </MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    );
    const list = await screen.findByRole("table", {
      name: "Budgets for the fiscal year",
    });
    expect(list).toHaveTextContent("Version 1: Approved; Version 2: Draft");
    fireEvent.click(within(list).getByRole("button", { name: "Budget 2026" }));

    // The open draft is shown first, as an editable grid.
    const jan = await screen.findByLabelText("REV.SALES · Sales Jan");
    fireEvent.change(jan, { target: { value: "150.5" } });
    const grid = screen.getByRole("table", { name: "Budget lines" });
    expect(
      within(grid).getByRole("row", { name: /REV.SALES/ }),
    ).toHaveTextContent("1,250.50");
    fireEvent.change(jan, { target: { value: "1.234" } });
    expect(screen.getByText(/at most 2 decimals/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save lines" })).toBeDisabled();
    fireEvent.change(jan, { target: { value: "150.50" } });
    fireEvent.click(screen.getByRole("button", { name: "Save lines" }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "PUT")).toBe(true),
    );
    const sent = calls.find((c) => c.method === "PUT")?.body as {
      lines: { taxonomy_code: string; amounts: Record<string, string> }[];
    };
    expect(sent.lines[0]?.taxonomy_code).toBe("REV.SALES");
    expect(sent.lines[0]?.amounts["2026-01-01"]).toBe("150.50");
    expect(sent.lines[0]?.amounts["2026-12-01"]).toBe("100.00");

    // The approved original is read-only, with quarters and its nature.
    fireEvent.click(
      screen.getByRole("button", {
        name: /Version 1 · Approved \(original, current\)/,
      }),
    );
    const approved = await screen.findByRole("table", { name: "Budget lines" });
    await waitFor(() => expect(approved).toHaveTextContent("Q 4"));
    expect(approved).toHaveTextContent("Budget");
    expect(
      screen.getByRole("button", { name: "Start a revision" }),
    ).toBeDisabled();
    expect(await screen.findByText(/approved · Mo Manager/)).toHaveTextContent(
      "“Fine”",
    );

    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => v.id)).toEqual([]);
  });
});
