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
import {
  PersonalOverviewPage,
  PersonalTransactionsPage,
} from "./pages/Personal";

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const acc = (
  id: string,
  code: string,
  name: string,
  type: string,
  amount = "0.00",
  nature = "ACTUAL",
  valuation_date: string | null = null,
) => ({
  id,
  code,
  name,
  type,
  balance: nature === "ACTUAL" ? amount : "0.00",
  amount,
  nature,
  valuation_date,
});
const accounts = [
  acc("a1", "1100", "Current account", "ASSET", "4580.00"),
  acc("a2", "1300", "Property", "ASSET", "250000.00", "EXPECTED", "2026-03-31"),
  acc("l1", "2100", "Credit card", "LIABILITY"),
  acc("c1", "6100", "Groceries", "EXPENSE", "120.00"),
  acc("i1", "4000", "Salary", "INCOME", "3000.00"),
];

function wrap(path: string, element: React.ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <I18nProvider locale="en">
        <MemoryRouter initialEntries={[`/w/me/e/hh/${path}`]}>
          <Routes>
            <Route path={`/w/:slug/e/:entityId/${path}`} element={element} />
          </Routes>
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("Personal finances (M5-1)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("offers setup, then shows net worth with valuations labelled", async () => {
    let ready = false;
    const calls: string[] = [];
    document.cookie = "__Host-fcp_csrftoken=test";
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init: RequestInit) => {
        calls.push(`${init.method ?? "GET"} ${url}`);
        if (url.includes("/personal/setup")) {
          ready = true;
          return Promise.resolve(respond({ created: true }));
        }
        if (url.includes("/personal/accounts"))
          return Promise.resolve(respond(ready ? accounts : []));
        if (url.includes("/personal/net-worth"))
          return Promise.resolve(
            respond({
              as_of: "2026-06-30",
              assets: accounts.slice(0, 2),
              liabilities: [accounts[2]],
              total_assets: "254580.00",
              total_liabilities: "0.00",
              net_worth: "254580.00",
              includes_valuations: true,
              trend: [
                {
                  date: "2026-06-30",
                  net_worth: "254580.00",
                  includes_valuations: true,
                },
              ],
            }),
          );
        return Promise.resolve(
          respond({ status: 404, code: "not_found", detail: "x" }, 404),
        );
      }),
    );
    const { container } = wrap("personal", <PersonalOverviewPage />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Set up my accounts" }),
    );
    await waitFor(() =>
      expect(
        calls.some(
          (c) => c.startsWith("POST") && c.endsWith("/personal/setup"),
        ),
      ).toBe(true),
    );
    const worth = await screen.findByRole("region", {
      name: /Net worth 2026-06-30/,
    });
    expect(worth).toHaveTextContent("254,580.00");
    expect(worth).toHaveTextContent("Includes values you entered");
    const owned = within(worth).getByRole("table", { name: "What I own" });
    expect(
      within(owned).getByRole("row", { name: /Property/ }),
    ).toHaveTextContent("Valuation 2026-03-31");
    expect(
      within(owned).getByRole("row", { name: /Current account/ }),
    ).toHaveTextContent("Actual");
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => v.id)).toEqual([]);
  });

  it("records what was spent and undoes a transaction with a reason", async () => {
    const posted: { url: string; body: unknown }[] = [];
    document.cookie = "__Host-fcp_csrftoken=test";
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init: RequestInit) => {
        if (init.method === "POST") {
          posted.push({ url, body: JSON.parse(init.body as string) });
          return Promise.resolve(respond({}, 201));
        }
        if (url.includes("/personal/accounts"))
          return Promise.resolve(respond(accounts));
        if (url.includes("/personal/transactions"))
          return Promise.resolve(
            respond([
              {
                entry_id: "e1",
                ref: "GJ-1",
                date: "2026-11-02",
                description: "Supermarket",
                kind: "SPENT",
                amount: "120.00",
                account_id: "a1",
                other_id: "c1",
                undone: false,
              },
            ]),
          );
        if (url.includes("/personal/spending"))
          return Promise.resolve(
            respond({
              date_from: "",
              date_to: "",
              income: [],
              total_income: "0.00",
              spending: [
                { account_id: "c1", name: "Groceries", amount: "120.00" },
              ],
              total_spending: "120.00",
              left_over: "-120.00",
            }),
          );
        return Promise.resolve(
          respond({ status: 404, code: "not_found", detail: "x" }, 404),
        );
      }),
    );
    vi.stubGlobal("prompt", () => "Entered twice");
    const { container } = wrap(
      "personal/transactions",
      <PersonalTransactionsPage />,
    );
    const form = await screen.findByRole("region", {
      name: "Record money in or out",
    });
    fireEvent.change(within(form).getByLabelText("Amount"), {
      target: { value: "45.20" },
    });
    fireEvent.change(within(form).getByLabelText("Description"), {
      target: { value: "Market" },
    });
    fireEvent.change(within(form).getByLabelText("From"), {
      target: { value: "a1" },
    });
    fireEvent.change(within(form).getByLabelText("Category"), {
      target: { value: "c1" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(posted[0]?.body).toMatchObject({
        kind: "SPENT",
        amount: "45.20",
        description: "Market",
        account_id: "a1",
        category_id: "c1",
      }),
    );
    const table = await screen.findByRole("table", { name: "Transactions" });
    const row = within(table).getByRole("row", { name: /Supermarket/ });
    expect(row).toHaveTextContent("SpentCurrent accountGroceries120.00");
    fireEvent.click(within(row).getByRole("button", { name: "Undo" }));
    await waitFor(() =>
      expect(posted.find((p) => p.url.endsWith("/e1/undo"))?.body).toEqual({
        reason: "Entered twice",
      }),
    );
    expect(screen.getByRole("status")).toHaveTextContent("Left over: -120.00");
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => v.id)).toEqual([]);
  });
});
