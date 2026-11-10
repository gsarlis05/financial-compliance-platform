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
import { PersonalPlanPage } from "./pages/PersonalPlan";

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const account = (id: string, name: string, type: string) => ({
  id,
  code: id,
  name,
  type,
  balance: "0.00",
  amount: "0.00",
  nature: "ACTUAL",
  valuation_date: null,
});
const accounts = [
  account("a1", "Savings account", "ASSET"),
  account("l1", "Credit card", "LIABILITY"),
  account("c1", "Groceries", "EXPENSE"),
  account("c2", "Leisure", "EXPENSE"),
];

describe("Personal budget and goals (M5-2)", () => {
  it("edits the budget, adds a goal and shows the projection accessibly", async () => {
    const sent: { url: string; method: string; body: unknown }[] = [];
    document.cookie = "__Host-fcp_csrftoken=test";
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init: RequestInit) => {
        const method = init.method ?? "GET";
        if (method !== "GET") {
          sent.push({ url, method, body: JSON.parse(init.body as string) });
          return Promise.resolve(respond({}, method === "POST" ? 201 : 200));
        }
        if (url.includes("/personal/accounts"))
          return Promise.resolve(respond(accounts));
        if (url.includes("/personal/budget"))
          return Promise.resolve(
            respond({
              month: "2026-11-01",
              budgeted_spending: "350.00",
              actual_spending: "400.00",
              lines: [
                {
                  account_id: "c1",
                  name: "Groceries",
                  type: "EXPENSE",
                  budgeted: "350.00",
                  actual: "400.00",
                  remaining: "-50.00",
                  over: true,
                },
              ],
            }),
          );
        if (url.includes("/personal/goals"))
          return Promise.resolve(
            respond([
              {
                id: "g1",
                kind: "SAVINGS",
                name: "Holiday fund",
                account_ids: ["a1"],
                target_date: "2027-04-30",
                months: null,
                retired_at: null,
                current: "1900.00",
                target: "3000.00",
                months_left: 5,
                needed_per_month: "220.00",
                pace_per_month: "300.00",
                projected: "3400.00",
                status: "ON_TRACK",
                average_spending: null,
              },
            ]),
          );
        if (url.includes("/personal/projection"))
          return Promise.resolve(
            respond({
              as_of: "2026-11-10",
              opening_cash: "5800.00",
              first_negative: "2027-02-01",
              months: [
                {
                  month: "2026-12-01",
                  income: "2000.00",
                  spending: "1250.00",
                  closing_cash: "6550.00",
                  nature: "FORECAST",
                },
              ],
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
          <MemoryRouter initialEntries={["/w/me/e/hh/personal/plan"]}>
            <Routes>
              <Route
                path="/w/:slug/e/:entityId/personal/plan"
                element={<PersonalPlanPage />}
              />
            </Routes>
          </MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    );
    const budget = await screen.findByRole("region", {
      name: "Monthly budget",
    });
    const row = await within(budget).findByRole("row", { name: /Groceries/ });
    expect(row).toHaveTextContent("▼ over budget");
    fireEvent.change(within(row).getByLabelText("Per month Groceries"), {
      target: { value: "450" },
    });
    fireEvent.click(within(row).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(sent.find((s) => s.method === "PUT")?.body).toMatchObject({
        account_id: "c1",
        monthly_amount: "450",
      }),
    );

    const goals = screen.getByRole("region", { name: "Goals" });
    const holiday = await within(goals).findByRole("row", {
      name: /Holiday fund/,
    });
    expect(holiday).toHaveTextContent(
      "1,900.003,000.00220.00300.003,400.00On track",
    );
    fireEvent.change(within(goals).getByLabelText("Kind"), {
      target: { value: "DEBT_PAYOFF" },
    });
    fireEvent.change(within(goals).getByLabelText("Name"), {
      target: { value: "Clear the card" },
    });
    fireEvent.change(within(goals).getByLabelText("Account"), {
      target: { value: "l1" },
    });
    fireEvent.change(within(goals).getByLabelText("Owe at most"), {
      target: { value: "0" },
    });
    fireEvent.change(within(goals).getByLabelText("By"), {
      target: { value: "2027-04-30" },
    });
    fireEvent.click(within(goals).getByRole("button", { name: "Add" }));
    await waitFor(() =>
      expect(sent.find((s) => s.url.endsWith("/personal/goals"))?.body).toEqual(
        {
          kind: "DEBT_PAYOFF",
          name: "Clear the card",
          account_ids: ["l1"],
          target_date: "2027-04-30",
          target_amount: "0",
        },
      ),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Cash would fall below zero in 2027-02",
    );
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => v.id)).toEqual([]);
    vi.unstubAllGlobals();
  });
});
