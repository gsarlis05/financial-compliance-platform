import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import axe from "axe-core";
import { MemoryRouter, Route, Routes } from "react-router";
import { I18nProvider } from "./i18n/I18n";
import { StatementsPage } from "./pages/Statements";

const account = (
  code: string,
  name: string,
  current: string,
  comparative: string | null,
) => ({
  account_id: `id-${code}`,
  code,
  name,
  name_el: "",
  current,
  comparative,
});
const row = (
  kind: string,
  code: string,
  name: string,
  current: string | null,
  comparative: string | null,
  accounts: unknown[] = [],
) => ({ kind, code, name, name_el: "", current, comparative, accounts });
const statement = (kind: string, name: string, rows: unknown[]) => ({
  kind,
  name,
  name_el: "",
  rows,
  checks: [],
});
const data = {
  entity_name: "Demo Trading Ltd (Demo)",
  taxonomy: "IFRS_SME_CY@1.0",
  watermark: 98,
  date_from: "2026-01-01",
  date_to: "2026-12-31",
  comparative_from: "2025-01-01",
  comparative_to: "2025-12-31",
  ok: true,
  profit_and_loss: statement("PL", "Profit and loss", [
    row("heading", "REVENUE", "Revenue", null, null),
    row("line", "REV.SALES", "Revenue — sales of goods", "9000.00", "5000.00", [
      account("4000", "Sales of goods", "9000.00", "5000.00"),
    ]),
    row(
      "total",
      "PL.RESULT",
      "Profit (loss) for the period",
      "5550.00",
      "4000.00",
    ),
  ]),
  balance_sheet: statement("BS", "Balance sheet", [
    row("heading", "CURRENT_ASSETS", "Current assets", null, null),
    row(
      "line",
      "BS.CASH",
      "Cash and cash equivalents",
      "19450.00",
      "14000.00",
      [account("1300", "Bank", "19450.00", "14000.00")],
    ),
    row("total", "BS.TOTAL_ASSETS", "Total assets", "19450.00", "14000.00"),
  ]),
  cash_flow: statement("CF", "Cash flow statement", [
    row(
      "line",
      "CF.INV.PPE",
      "Property, plant and equipment",
      "-3000.00",
      "0.00",
      [
        account("1010", "Equipment", "-3000.00", "0.00"),
        {
          ...account(
            "",
            "Less: depreciation and amortisation",
            "-600.00",
            "0.00",
          ),
          account_id: null,
        },
      ],
    ),
  ]),
};
const ledger = {
  account_id: "id-1300",
  code: "1300",
  name: "Bank",
  date_from: "2026-01-01",
  date_to: "2026-12-31",
  opening_balance: "14000.00",
  closing_balance: "19450.00",
  lines: [
    {
      entry_id: "e1",
      entry_ref: "GJ-7",
      accounting_date: "2026-06-30",
      description: "Cash sales",
      memo: "",
      debit: "7000.00",
      credit: "0.00",
      running_balance: "21000.00",
      restated_after_lock: false,
    },
  ],
};

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/problem+json" },
  });
}

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <I18nProvider locale="en">
        <MemoryRouter initialEntries={["/w/demo/e/ent/statements"]}>
          <Routes>
            <Route
              path="/w/:slug/e/:entityId/statements"
              element={<StatementsPage />}
            />
          </Routes>
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("Financial statements page (M2-8)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows the statements with comparatives, drill-down to accounts and ledger lines, and exports", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        Promise.resolve(
          respond(url.includes("/general-ledger/") ? ledger : data),
        ),
      ),
    );
    const { container } = renderPage();
    const table = await screen.findByRole("table", { name: "Profit and loss" });
    expect(within(table).getByText("Prior year")).toBeInTheDocument();
    expect(within(table).getByText("5,550.00")).toBeInTheDocument();
    expect(screen.getByText(/Checks passed/)).toHaveTextContent("#98");
    expect(screen.getByRole("link", { name: "Export PDF" })).toHaveAttribute(
      "href",
      expect.stringContaining("/statements/export?date_from=") as string,
    );

    fireEvent.click(screen.getByRole("tab", { name: "Balance sheet" }));
    const bs = await screen.findByRole("table", { name: "Balance sheet" });
    fireEvent.click(
      within(bs).getByRole("button", { name: /Cash and cash equivalents/ }),
    );
    fireEvent.click(within(bs).getByRole("button", { name: "1300 · Bank" }));
    const panel = await screen.findByRole("region", {
      name: "Ledger lines: 1300 · Bank",
    });
    expect(
      await within(panel).findByRole("link", { name: "GJ-7" }),
    ).toHaveAttribute("href", "/w/demo/e/ent/entries/e1");

    fireEvent.click(screen.getByRole("tab", { name: "Cash flow" }));
    const cf = await screen.findByRole("table", {
      name: "Cash flow statement",
    });
    expect(within(cf).getByText("-3,000.00")).toBeInTheDocument();
    fireEvent.click(
      within(cf).getByRole("button", { name: /Property, plant and equipment/ }),
    );
    expect(
      within(cf).getByText(/Less: depreciation and amortisation \(computed\)/),
    ).toBeInTheDocument();

    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => v.id)).toEqual([]);
  });

  it("explains what blocks the statements and links to the mapping", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          respond(
            {
              type: "urn:fcp:problem:metrics.statements.mapping_incomplete",
              title: "Blocked",
              status: 409,
              detail: "1 account(s) with a balance are not mapped.",
              code: "metrics.statements.mapping_incomplete",
              errors: { "9999": ["unmapped and has a balance on 2026-12-31"] },
            },
            409,
          ),
        ),
      ),
    );
    renderPage();
    const blocked = await screen.findByTestId("statements-blocked");
    expect(blocked).toHaveTextContent("9999");
    expect(
      within(blocked).getByRole("link", { name: "Open statement mapping" }),
    ).toHaveAttribute("href", "/w/demo/e/ent/mapping");
  });
});
