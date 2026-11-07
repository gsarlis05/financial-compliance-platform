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
import { CustomKpisPage } from "./pages/CustomKpis";

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const submitted = {
  id: "k1",
  key: "REVENUE_PER_EMPLOYEE",
  version: 1,
  scope: "WORKSPACE",
  status: "SUBMITTED",
  name: "Revenue per employee",
  formula: 'flow("REVENUE") / count_metric("HEADCOUNT")',
  unit: "EUR",
  display: "EUR",
  direction: "HIGHER_BETTER",
  convention: "",
  owner_name: "Mo",
  supersedes_id: null,
  decided_by_name: "",
  decided_at: null,
  decision_comment: "",
  created_at: "2026-11-06T10:00:00Z",
};
const month = (() => {
  const now = new Date();
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 1, 1))
    .toISOString()
    .slice(0, 10);
})();

describe("Custom KPIs and operational metrics (M4-5)", () => {
  it("checks before saving, approves, edits metric values and stays accessible", async () => {
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
        if (url.endsWith("/custom-kpis/check"))
          return Promise.resolve(
            respond({
              ok: true,
              unit: "ratio",
              problems: [],
              dry_run_month: month,
              dry_run_value: "1.6",
              dry_run_reason: "",
              non_ledger: false,
            }),
          );
        if (url.endsWith("/custom-kpis") && method === "POST")
          return Promise.resolve(
            respond(
              {
                ...submitted,
                key: "MARKUP",
                scope: "PERSONAL",
                status: "ACTIVE",
              },
              201,
            ),
          );
        if (url.endsWith("/custom-kpis"))
          return Promise.resolve(respond([submitted]));
        if (url.endsWith("/custom-kpis/k1/approve"))
          return Promise.resolve(respond({ ...submitted, status: "APPROVED" }));
        if (url.endsWith("/operational-metrics"))
          return Promise.resolve(
            respond([
              {
                id: "m1",
                key: "HEADCOUNT",
                name: "Employees",
                unit: "count",
                aggregation: "LAST",
                source: "MANUAL",
                nature: "ACTUAL",
                non_ledger: true,
                values: [
                  {
                    month,
                    value: "5",
                    version: 2,
                    note: "",
                    entered_by: "Ann",
                    entered_at: "2026-11-06T10:00:00Z",
                  },
                ],
              },
            ]),
          );
        if (url.endsWith("/operational-metrics/m1/values"))
          return Promise.resolve(
            respond({
              month,
              value: "6",
              version: 3,
              note: "",
              entered_by: "Ann",
              entered_at: "x",
            }),
          );
        return Promise.resolve(
          respond({ status: 404, code: "not_found", detail: "x" }, 404),
        );
      }),
    );
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider locale="en">
          <MemoryRouter initialEntries={["/w/demo/e/ent/custom-kpis"]}>
            <Routes>
              <Route
                path="/w/:slug/e/:entityId/custom-kpis"
                element={<CustomKpisPage />}
              />
            </Routes>
          </MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    );
    const list = await screen.findByRole("table", { name: "Custom KPIs" });
    const row = within(list).getByRole("row", { name: /REVENUE_PER_EMPLOYEE/ });
    expect(row).toHaveTextContent("Waiting for approval");
    fireEvent.click(within(row).getByRole("button", { name: /Approve/ }));
    await waitFor(() =>
      expect(calls.some((c) => c.url.endsWith("/k1/approve"))).toBe(true),
    );

    fireEvent.click(screen.getByRole("button", { name: "New KPI" }));
    const form = screen.getByRole("region", { name: "New KPI" });
    fireEvent.change(within(form).getByLabelText("Key"), {
      target: { value: "markup" },
    });
    fireEvent.change(within(form).getByLabelText("Name"), {
      target: { value: "Mark-up" },
    });
    fireEvent.change(within(form).getByLabelText("Formula"), {
      target: { value: 'flow("REVENUE") / flow("COST_OF_SALES")' },
    });
    const save = within(form).getByRole("button", { name: "Save" });
    expect(save).toBeDisabled(); // only after a successful check
    fireEvent.click(screen.getByRole("button", { name: "Check the formula" }));
    expect(await screen.findByText(/The formula works/)).toHaveTextContent(
      "1.6",
    );
    fireEvent.click(save);
    await waitFor(() =>
      expect(
        calls.find((c) => c.url.endsWith("/custom-kpis") && c.method === "POST")
          ?.body,
      ).toEqual({
        key: "MARKUP",
        name: "Mark-up",
        formula: 'flow("REVENUE") / flow("COST_OF_SALES")',
        display: "ratio",
        direction: "HIGHER_BETTER",
        convention: "",
        scope: "PERSONAL",
      }),
    );

    const values = screen.getByRole("table", { name: /Monthly values/ });
    expect(values).toHaveTextContent("Includes data not from the ledger");
    const cell = within(values).getByLabelText(
      `Employees ${month.slice(0, 7)}`,
    );
    expect(cell).toHaveValue("5");
    fireEvent.change(cell, { target: { value: "6" } });
    fireEvent.blur(cell);
    await waitFor(() =>
      expect(calls.find((c) => c.url.endsWith("/m1/values"))?.body).toEqual({
        month,
        value: "6",
        note: "",
      }),
    );

    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => v.id)).toEqual([]);
    vi.unstubAllGlobals();
  });
});
