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
import type { PersonalAccount } from "./api/personal";
import { I18nProvider } from "./i18n/I18n";
import { CounterpartSection } from "./pages/PersonalCounterpart";

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const account = (id: string, name: string, type: PersonalAccount["type"]) => ({
  id,
  code: id,
  name,
  type,
  balance: "0.00",
  amount: "0.00",
  nature: "ACTUAL" as const,
  valuation_date: null,
});
const accounts = [
  account("a1", "Current account", "ASSET"),
  account("i1", "Salary", "INCOME"),
];
const link = {
  id: "k1",
  business_slug: "biz",
  business_entity_id: "be",
  business_account_id: "ba",
  label: "Demo Trading · 2020 Director loans",
  account_id: "a1",
  category_id: "i1",
  since: "2026-01-01",
  created_at: "2026-11-10T00:00:00Z",
};
const line = (entry: string, debit: string, credit: string, text: string) => ({
  entry_id: entry,
  entry_ref: "GJ-1",
  accounting_date: "2026-03-20",
  description: text,
  memo: "",
  debit,
  credit,
  running_balance: "0.00",
  restated_after_lock: false,
});

describe("Counterpart hints (M5-3)", () => {
  it("suggests business payments to the owner and records one only on confirmation", async () => {
    const sent: { url: string; body: unknown }[] = [];
    const urls: string[] = [];
    document.cookie = "__Host-fcp_csrftoken=test";
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init: RequestInit) => {
        urls.push(url);
        if ((init.method ?? "GET") !== "GET") {
          sent.push({ url, body: JSON.parse(init.body as string) });
          return Promise.resolve(respond({}, 201));
        }
        if (url.includes("/personal/counterpart-links/k1/decisions"))
          return Promise.resolve(
            respond([
              {
                id: "d1",
                business_entry_id: "e0",
                decision: "DISMISSED",
                amount: "50.00",
                entry_date: "2026-02-01",
                personal_entry_id: null,
                created_at: "2026-11-10T00:00:00Z",
              },
            ]),
          );
        if (url.includes("/personal/counterpart-links"))
          return Promise.resolve(respond([link]));
        if (url.includes("/w/biz/entities/be/reports/general-ledger/ba"))
          return Promise.resolve(
            respond({
              account_id: "ba",
              code: "2020",
              name: "Director loans",
              date_from: "2026-01-01",
              date_to: "2026-11-10",
              opening_balance: "0.00",
              lines: [
                line("e0", "50.00", "0.00", "Already dismissed"),
                line("e1", "1500.00", "0.00", "Loan repaid"),
                line("e2", "0.00", "800.00", "Loan from the director"),
              ],
              closing_balance: "0.00",
            }),
          );
        if (url.endsWith("/workspaces"))
          return Promise.resolve(
            respond([{ slug: "biz", name: "Demo Trading", kind: "BUSINESS" }]),
          );
        return Promise.resolve(respond([]));
      }),
    );
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider locale="en">
          <MemoryRouter initialEntries={["/w/me/e/hh/personal/transactions"]}>
            <Routes>
              <Route
                path="/w/:slug/e/:entityId/personal/transactions"
                element={<CounterpartSection accounts={accounts} />}
              />
            </Routes>
          </MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    );
    const section = await screen.findByRole("region", {
      name: "From my business",
    });
    const table = await within(section).findByRole("table", {
      name: /Suggested payments/,
    });
    // Only the new payment to the owner: not the loan to the business, not the dismissed one.
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(1);
    const repaid = within(table).getByRole("row", { name: /Loan repaid/ });
    expect(sent).toEqual([]); // nothing is recorded without confirmation
    fireEvent.click(within(repaid).getByRole("button", { name: "Record it" }));
    await waitFor(() =>
      expect(sent).toEqual([
        {
          url: "/api/w/me/entities/hh/personal/counterpart-links/k1/confirm",
          body: {
            business_entry_id: "e1",
            date: "2026-03-20",
            amount: "1500.00",
            description: "Demo Trading · 2020 Director loans: Loan repaid",
          },
        },
      ]),
    );
    // Business figures are read from the business workspace only, never via the personal one.
    expect(
      urls.some((u) => u.includes("/w/me/") && u.includes("general-ledger")),
    ).toBe(false);
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => v.id)).toEqual([]);
    vi.unstubAllGlobals();
  });
});
