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
import { BankPage } from "./pages/Bank";

const account = {
  id: "b1",
  name: "Current account",
  iban: "CY17002001280000001200527600",
  currency: "EUR",
  ledger_account_id: "a1300",
  status: "ACTIVE",
  csv_mapping: null,
  last_reconciled: null,
  unmatched_lines: 1,
};
const line = {
  id: "l1",
  booking_date: "2026-03-03",
  value_date: null,
  amount: "-4.00",
  description: "Bank fee",
  counterparty_name: "",
  reference: "",
  bank_ref: "B3",
  status: "UNMATCHED",
  matched_line_id: null,
  note: "",
};
const candidate = {
  journal_line_id: "j1",
  entry_id: "e1",
  entry_ref: "GJ-7",
  accounting_date: "2026-03-04",
  amount: "-4.00",
  reference: "",
  description: "Bank charges",
};

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Bank page (M2-5)", () => {
  const calls: { url: string; method: string; body: unknown }[] = [];
  beforeEach(() => {
    calls.length = 0;
    document.cookie = "__Host-fcp_csrftoken=test";
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init: RequestInit) => {
        const method = init.method ?? "GET";
        calls.push({ url, method, body: init.body });
        if (url.endsWith("/imports") && method === "POST") {
          return Promise.resolve(
            respond(
              {
                type: "x",
                title: "This file was already imported",
                status: 409,
                detail:
                  "This file was already imported on 2026-03-05; nothing was imported again.",
                code: "banking.import.duplicate",
              },
              409,
            ),
          );
        }
        if (url.includes("/reconcile")) {
          return Promise.resolve(
            respond({
              as_of: "2026-03-31",
              statement_balance: "939.50",
              ledger_balance: "935.50",
              difference: "-4.00",
              unmatched_lines: 1,
              reconciled: false,
            }),
          );
        }
        if (url.endsWith("/match"))
          return Promise.resolve(respond({ ...line, status: "MATCHED" }));
        if (url.includes("/candidates"))
          return Promise.resolve(respond([candidate]));
        if (url.includes("/suggestions")) return Promise.resolve(respond([]));
        if (url.includes("/lines")) return Promise.resolve(respond([line]));
        if (url.includes("/imports")) return Promise.resolve(respond([]));
        if (url.includes("/bank-accounts"))
          return Promise.resolve(respond([account]));
        return Promise.resolve(respond([]));
      }),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  it("imports, refuses a duplicate, resolves a line and reconciles", async () => {
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider locale="en">
          <MemoryRouter initialEntries={["/w/demo/e/ent/bank"]}>
            <Routes>
              <Route path="/w/:slug/e/:entityId/bank" element={<BankPage />} />
            </Routes>
          </MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    );
    const panel = await screen.findByRole("region", {
      name: "Current account",
    });
    expect(within(panel).getByTestId("last-reconciled")).toHaveTextContent(
      "Not reconciled yet · 1 unmatched lines",
    );

    const file = new File(["<Document/>"], "march.xml", { type: "text/xml" });
    fireEvent.change(within(panel).getByLabelText("Statement file"), {
      target: { files: [file] },
    });
    fireEvent.click(within(panel).getByRole("button", { name: "Import" }));
    await waitFor(() =>
      expect(calls.map((c) => `${c.method} ${c.url}`)).toContain(
        "POST /api/w/demo/entities/ent/bank-accounts/b1/imports",
      ),
    );
    expect(await within(panel).findByRole("alert")).toHaveTextContent(
      "already imported",
    );
    const upload = calls.find(
      (c) => c.method === "POST" && c.url.endsWith("/imports"),
    );
    expect(upload?.body).toBeInstanceOf(FormData);
    expect((upload?.body as FormData).get("format")).toBe("CAMT053");

    fireEvent.click(
      await within(panel).findByRole("button", { name: "Resolve" }),
    );
    fireEvent.click(
      await within(panel).findByRole("button", { name: "Match" }),
    );
    await waitFor(() =>
      expect(
        calls.some((c) => c.url.endsWith("/statement-lines/l1/match")),
      ).toBe(true),
    );
    const match = calls.find((c) => c.url.endsWith("/match"));
    expect(JSON.parse(match?.body as string)).toEqual({
      journal_line_id: "j1",
    });

    fireEvent.change(within(panel).getByLabelText("Statement balance"), {
      target: { value: "939.50" },
    });
    fireEvent.click(
      within(panel).getAllByRole("button", {
        name: "Reconcile",
      })[0] as HTMLElement,
    );
    expect(
      await within(panel).findByTestId("reconciliation"),
    ).toHaveTextContent("Not reconciled:");
    expect(within(panel).getByTestId("reconciliation")).toHaveTextContent(
      "difference -4.00",
    );

    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => v.id)).toEqual([]);
  });
});
