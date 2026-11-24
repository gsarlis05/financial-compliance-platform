// Foreign currency (V1-2h, #219): a line in another currency converts to euros at the rate of
// the purchase's date and time, with its source; the ledger settings switch it on.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import axe from "axe-core";
import { MemoryRouter, Route, Routes } from "react-router";
import type { Account, FiscalYear } from "./api/types";
import { I18nProvider } from "./i18n/I18n";
import { converted, EntryForm } from "./pages/EntryForm";
import { LedgerSettingsPage } from "./pages/LedgerSettings";

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function account(id: string, code: string, type: Account["type"]): Account {
  return {
    id,
    code,
    name: `Account ${code}`,
    name_el: "",
    type,
    normal_side: type === "INCOME" ? "CREDIT" : "DEBIT",
    parent_id: null,
    is_postable: true,
    status: "ACTIVE",
    currency: "",
    control_type: "",
    vat_role: "",
  };
}

const accounts = [
  account("a1", "6100", "EXPENSE"),
  account("a2", "2100", "LIABILITY"),
  account("fx", "7020", "EXPENSE"),
];
const years: FiscalYear[] = [
  {
    id: "fy",
    name: "2026",
    start_date: "2026-01-01",
    end_date: "2026-12-31",
    status: "OPEN",
    periods: [],
  },
];

function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

async function noAxeViolations(container: HTMLElement) {
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

describe("converted", () => {
  it("rounds half up to the cent, as the server checks", () => {
    expect(converted("100", "0.92")).toBe("92.00");
    expect(converted("10.005", "1")).toBe("10.01");
    expect(converted("1,5", "2")).toBe("3.00");
    expect(converted("", "0.92")).toBe("");
    expect(converted("100", "abc")).toBe("");
    expect(converted("-1", "0.92")).toBe("");
  });
});

describe("EntryForm in a foreign currency", () => {
  it("converts the amount at the rate and sends the rate's date, time and source", async () => {
    const onSave = vi.fn();
    const suggest = vi.fn().mockResolvedValue({
      currency: "USD",
      rate: "0.9300000000",
      rate_date: "2026-03-09",
      rate_type: "SPOT",
      source: "Central bank",
    });
    const { container } = render(
      <I18nProvider locale="en">
        <EntryForm
          accounts={accounts}
          fiscalYears={years}
          saving={false}
          error={null}
          onSave={onSave}
          foreign={{ functional: "EUR", suggest }}
        />
      </I18nProvider>,
    );
    fill("Description", "Laptop from a US shop");
    fill("Accounting date", "2026-03-10");
    fill("Account 1", "a1");
    fill("Currency 1", "USD");
    fill("Amount in currency 1", "100");
    fill("Rate (euros per unit) 1", "0.92");
    expect(screen.getByLabelText("Debit 1")).toHaveValue("92.00");

    fireEvent.click(
      screen.getByRole("button", { name: "Use the stored rate" }),
    );
    await waitFor(() =>
      expect(screen.getByLabelText("Debit 1")).toHaveValue("93.00"),
    );
    expect(suggest).toHaveBeenCalledWith("USD", "2026-03-10");
    expect(screen.getByLabelText("Rate's source 1")).toHaveValue(
      "Central bank (SPOT, 2026-03-09)",
    );

    fill("Rate (euros per unit) 1", "0.92");
    fill("Rate's date and time 1", "2026-03-10T14:32");
    fill("Rate's source 1", "Bank card statement");
    fill("Account 2", "a2");
    fill("Credit 2", "92.00");
    await noAxeViolations(container);
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    const [body] = onSave.mock.calls[0] as [
      { lines: Record<string, unknown>[] },
    ];
    expect(body.lines[0]).toMatchObject({
      debit: "92.00",
      txn_currency: "USD",
      txn_amount: "100",
      exchange_rate: "0.92",
      rate_at: new Date("2026-03-10T14:32").toISOString(),
      rate_source: "Bank card statement",
    });
    expect(body.lines[1]).not.toHaveProperty("txn_currency");
  });

  it("says so when no rate is stored, and hides the block when switched off", async () => {
    const suggest = vi.fn().mockResolvedValue(null);
    const { rerender } = render(
      <I18nProvider locale="en">
        <EntryForm
          accounts={accounts}
          fiscalYears={years}
          saving={false}
          error={null}
          onSave={vi.fn()}
          foreign={{ functional: "EUR", suggest }}
        />
      </I18nProvider>,
    );
    fill("Currency 1", "GBP");
    fireEvent.click(
      screen.getByRole("button", { name: "Use the stored rate" }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "No stored rate for that currency",
    );
    rerender(
      <I18nProvider locale="en">
        <EntryForm
          accounts={accounts}
          fiscalYears={years}
          saving={false}
          error={null}
          onSave={vi.fn()}
        />
      </I18nProvider>,
    );
    expect(screen.queryByLabelText("Currency 1")).not.toBeInTheDocument();
  });
});

describe("Ledger settings page", () => {
  it("switches foreign currency on with the exchange-differences account and records a rate", async () => {
    const sent: { url: string; method: string; body: unknown }[] = [];
    document.cookie = "__Host-fcp_csrftoken=test";
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init: RequestInit) => {
        const method = init.method ?? "GET";
        if (method !== "GET") {
          const body: unknown = JSON.parse(init.body as string);
          sent.push({ url, method, body });
          return Promise.resolve(
            respond(
              url.endsWith("/currency-settings")
                ? { functional_currency: "EUR", ...(body as object) }
                : body,
              method === "POST" ? 201 : 200,
            ),
          );
        }
        if (url.endsWith("/ledger-settings"))
          return Promise.resolve(
            respond({ approval_policy: "NONE", approval_threshold: null }),
          );
        if (url.endsWith("/currency-settings"))
          return Promise.resolve(
            respond({
              functional_currency: "EUR",
              multi_currency_enabled: false,
              fx_account_id: null,
            }),
          );
        if (url.includes("/exchange-rates"))
          return Promise.resolve(
            respond([
              {
                id: "x1",
                rate_date: "2026-03-09",
                base_currency: "USD",
                quote_currency: "EUR",
                rate: "0.9300000000",
                rate_type: "SPOT",
                source: "Central bank",
                source_hash: "h",
                created_at: "2026-03-09T10:00:00Z",
              },
            ]),
          );
        if (url.includes("/accounts"))
          return Promise.resolve(respond(accounts));
        return Promise.resolve(respond({}));
      }),
    );
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider locale="en">
          <MemoryRouter initialEntries={["/w/ws/e/e1/ledger-settings"]}>
            <Routes>
              <Route
                path="/w/:slug/e/:entityId/ledger-settings"
                element={<LedgerSettingsPage />}
              />
            </Routes>
          </MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    );
    const toggle = await screen.findByLabelText("Allow foreign currency");
    expect(screen.getByLabelText("Approval")).toHaveValue("NONE");
    expect(await screen.findByText("Central bank")).toBeInTheDocument();
    const choices = screen.getByLabelText<HTMLSelectElement>(
      "Account for exchange differences",
    );
    await waitFor(() => expect(choices.options.length).toBe(3));
    expect(Array.from(choices.options).map((o) => o.value)).toEqual([
      "",
      "a1",
      "fx",
    ]);
    await noAxeViolations(container);

    fireEvent.click(toggle);
    fireEvent.change(choices, { target: { value: "fx" } });
    fireEvent.click(
      screen.getAllByRole("button", { name: "Save" })[1] as HTMLElement,
    );
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({
      method: "PUT",
      body: { multi_currency_enabled: true, fx_account_id: "fx" },
    });
    expect(await screen.findAllByText("Saved.")).toHaveLength(1);

    fill("Date", "2026-03-10");
    fill("1 unit of", "USD");
    fill("In", "EUR");
    fill("Rate", "0,92");
    fill("Source", "Bank card statement");
    fireEvent.click(screen.getByRole("button", { name: "Record rate" }));
    await waitFor(() => expect(sent).toHaveLength(2));
    expect(sent[1]).toMatchObject({
      method: "POST",
      body: {
        rate_date: "2026-03-10",
        base_currency: "USD",
        quote_currency: "EUR",
        rate: "0.92",
        source: "Bank card statement",
      },
    });
  });
});
