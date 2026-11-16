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
import { AssumptionsPage } from "./pages/Assumptions";

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const set = {
  id: "s1",
  family_id: "f1",
  version: 1,
  name: "Plan 2027",
  cutover: "2026-12-31",
  months: 12,
  start_from: "ACTUALS",
  note: "Started from the 12 months to 31/12/2026.",
  status: "DRAFT",
  supersedes_id: null,
  created_at: "2026-11-12T00:00:00Z",
  approved_at: null,
};
const months = Array.from({ length: 3 }, (_, i) => `2027-0${i + 1}-01`);
const grid = {
  assumption_set: set,
  months,
  nature: "FORECAST",
  rows: [
    {
      driver: "revenue",
      line: "REV.SALES",
      unit: "AMOUNT",
      values: ["1320", "1210", "0"],
      sources: ["ACTUALS", "ACTUALS", "ACTUALS"],
    },
    {
      driver: "dso",
      line: "",
      unit: "DAYS",
      values: ["47.6087", "47.6087", "47.6087"],
      sources: ["ACTUALS", "ACTUALS", "ACTUALS"],
    },
  ],
};

describe("Assumption sets (M6-2)", () => {
  it("edits a draft, fills a row to the right, saves and approves", async () => {
    const sent: { url: string; method: string; body: unknown }[] = [];
    document.cookie = "__Host-fcp_csrftoken=test";
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init: RequestInit) => {
        const method = init.method ?? "GET";
        if (method !== "GET") {
          sent.push({ url, method, body: JSON.parse(init.body as string) });
          return Promise.resolve(respond(method === "PUT" ? grid : set));
        }
        if (url.endsWith("/assumption-sets/s1"))
          return Promise.resolve(respond(grid));
        return Promise.resolve(respond([set]));
      }),
    );
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider locale="en">
          <MemoryRouter initialEntries={["/w/ws/e/e1/assumptions"]}>
            <Routes>
              <Route
                path="/w/:slug/e/:entityId/assumptions"
                element={<AssumptionsPage />}
              />
            </Routes>
          </MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    );
    const sets = await screen.findByRole("table", { name: "Assumption sets" });
    fireEvent.click(within(sets).getByRole("button", { name: "Open" }));
    const table = await screen.findByRole("table", {
      name: "Assumptions by month",
    });
    expect(
      screen.getByText(/Every value is a forecast assumption/),
    ).toBeInTheDocument();
    const jan = within(table).getByLabelText("Revenue: sales of goods 2027-01");
    expect(jan).toHaveValue("1320");
    expect(jan.closest("td")).toHaveAttribute(
      "title",
      "From last year's actuals",
    );
    fireEvent.change(jan, { target: { value: "1500" } });
    fireEvent.click(
      within(table).getByRole("button", {
        name: "Fill right: Revenue: sales of goods",
      }),
    );
    expect(
      within(table).getByLabelText("Revenue: sales of goods 2027-03"),
    ).toHaveValue("1500");
    // Approving waits until the changes are saved.
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Save changes (3)" }));
    await waitFor(() =>
      expect(sent[0]).toEqual({
        url: "/api/w/ws/entities/e1/assumption-sets/s1/values",
        method: "PUT",
        body: {
          changes: months.map((month) => ({
            driver: "revenue",
            line: "REV.SALES",
            month,
            value: "1500",
          })),
        },
      }),
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() =>
      expect(sent[1]?.url).toBe(
        "/api/w/ws/entities/e1/assumption-sets/s1/approve",
      ),
    );
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => v.id)).toEqual([]);
    vi.unstubAllGlobals();
  });
});
