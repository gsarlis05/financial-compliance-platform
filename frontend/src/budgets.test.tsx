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
  method_params: {},
  phasing_note: "",
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
          body: typeof init.body === "string" ? JSON.parse(init.body) : null,
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
        if (url.endsWith("/budget-versions/v2/phase"))
          return Promise.resolve(
            respond({
              months,
              amounts: months.map((_, i) => (i === 11 ? "8333.37" : "8333.33")),
              total: "100000.00",
              note: "",
            }),
          );
        if (url.includes("/budget-versions/v2/import"))
          return Promise.resolve(
            respond({
              applied: url.includes("apply=true"),
              problems: [],
              changes: [
                {
                  line: "REV.SALES",
                  kind: "CHANGED",
                  before: "1200.00",
                  after: "1800.00",
                  months_changed: 12,
                },
              ],
              unchanged: 0,
              draft_hash: "h1",
            }),
          );
        if (url.includes("/variance?"))
          return Promise.resolve(
            respond({
              version_id: "v1",
              month: "2026-12-01",
              view: "MONTH",
              comparison: "ACTUAL_VS_BUDGET",
              window: ["2026-12-01"],
              cutover: null,
              actuals_watermark: 42,
              unposted_entries: 2,
              explain_above_amount: "1000.00",
              explain_above_percent: "10.00",
              rows: [
                {
                  line_id: "l1",
                  taxonomy_code: "REV.SALES",
                  account_id: null,
                  dimension_value_id: null,
                  direction: "HIGHER_BETTER",
                  subject: "1200.00",
                  subject_nature: "ACTUAL",
                  comparison: "100.00",
                  comparison_nature: "BUDGET",
                  variance: "1100.00",
                  percent: "1100.00",
                  favourable: true,
                  requires_explanation: true,
                  explanation: null,
                },
              ],
              review: null,
            }),
          );
        if (url.endsWith("/explanations"))
          return Promise.resolve(respond({}, 201));
        if (url.endsWith("/budgets/b1/owners"))
          return Promise.resolve(respond({ code: "permission_denied" }, 403));
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

    // Phasing: even spread of an annual amount, previewed by the server.
    fireEvent.change(screen.getByLabelText("Phasing REV.SALES · Sales"), {
      target: { value: "EVEN" },
    });
    fireEvent.change(screen.getByLabelText("Annual amount"), {
      target: { value: "100000" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Show months" }));
    await waitFor(() =>
      expect(
        within(grid).getByRole("row", { name: /REV.SALES/ }),
      ).toHaveTextContent("8,333.37"),
    );
    const phaseCall = calls.find((c) => c.url.endsWith("/phase"));
    expect(phaseCall?.body).toEqual({
      taxonomy_code: "REV.SALES",
      account_id: null,
      method: "EVEN",
      params: { annual: "100000" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save lines" }));
    await waitFor(() =>
      expect(calls.filter((c) => c.method === "PUT").length).toBe(2),
    );
    const phasedSave = calls.filter((c) => c.method === "PUT")[1]?.body as {
      lines: { method: string; params: unknown; amounts: object }[];
    };
    expect(phasedSave.lines[0]).toMatchObject({
      method: "EVEN",
      params: { annual: "100000" },
      amounts: {},
    });

    // Import: preview the changes, then apply with the preview's hash.
    const file = new File(["x"], "b.xlsx");
    fireEvent.change(screen.getByLabelText("Workbook (.xlsx)"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Check and preview" }));
    const changes = await screen.findByRole("table", {
      name: /Changes this file would make/,
    });
    expect(changes).toHaveTextContent("1,800.00");
    fireEvent.click(
      screen.getByRole("button", { name: "Replace the lines with this file" }),
    );
    expect(await screen.findByText("Imported.")).toBeInTheDocument();
    expect(
      calls.some(
        (c) =>
          c.url.includes("apply=true") && c.url.includes("expected_hash=h1"),
      ),
    ).toBe(true);
    expect(
      screen.getByRole("link", { name: /Download as Excel/ }),
    ).toHaveAttribute(
      "href",
      "/api/w/demo/entities/ent/budget-versions/v2/export",
    );

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

    // Variance of the approved version: nature labels, direction-aware effect, explanation.
    const variance = await screen.findByRole("table", {
      name: /Actual vs budget/,
    });
    const sales = within(variance).getByRole("row", { name: /REV.SALES/ });
    expect(sales).toHaveTextContent("1,200.00 (Actual)");
    expect(sales).toHaveTextContent("100.00 (Budget)");
    expect(sales).toHaveTextContent("Favourable");
    expect(sales).toHaveTextContent("Explanation needed");
    expect(screen.getByText(/not yet posted/)).toHaveTextContent("2");
    fireEvent.change(within(sales).getByLabelText(/Explanation for/), {
      target: { value: "New customer" },
    });
    fireEvent.click(within(sales).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.find((c) => c.url.endsWith("/explanations"))?.body).toEqual({
        line_id: "l1",
        month: screen.getByLabelText<HTMLSelectElement>("Month").value,
        view: "MONTH",
        comparison: "ACTUAL_VS_BUDGET",
        comment: "New customer",
      }),
    );

    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => v.id)).toEqual([]);
  });
});
