// Exchange differences screen (V1-2h2, #230): positions with their difference and kind, a
// missing rate shown, and one draft entry prepared (never posted here).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import axe from "axe-core";
import { MemoryRouter, Route, Routes } from "react-router";
import { I18nProvider } from "./i18n/I18n";
import { FxDifferencesPage } from "./pages/FxDifferences";

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const positions = {
  on: "2026-03-31",
  positions: [
    {
      account_id: "ap",
      account_code: "2100",
      account_name: "Trade payables",
      counterparty_id: "s1",
      currency: "USD",
      foreign: "-100.00",
      euros: "-92.00",
      rate: "0.9500000000",
      rate_date: "2026-03-31",
      rate_source: "ECB reference rate (Demo) (CLOSING, 2026-03-31)",
      revalued: "-95.00",
      difference: "-3.00",
      kind: "UNREALISED",
    },
    {
      account_id: "ar",
      account_code: "1100",
      account_name: "Trade receivables",
      counterparty_id: null,
      currency: "GBP",
      foreign: "50.00",
      euros: "58.00",
      rate: null,
      rate_date: null,
      rate_source: "",
      revalued: null,
      difference: "0.00",
      kind: "NO_RATE",
    },
  ],
  unrealised: "-3.00",
  realised: "0.00",
  missing_rates: ["GBP"],
  fx_account_id: "fx",
  waiting_entry_id: null,
};

function mount() {
  const sent: { url: string; body: unknown }[] = [];
  document.cookie = "__Host-fcp_csrftoken=test";
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init: RequestInit) => {
      if ((init.method ?? "GET") !== "GET") {
        sent.push({ url, body: JSON.parse(init.body as string) });
        return Promise.resolve(respond({ id: "e9" }, 201));
      }
      if (url.includes("/counterparties"))
        return Promise.resolve(
          respond([{ id: "s1", code: "US1", name: "Supplier US (Demo)" }]),
        );
      return Promise.resolve(respond(positions));
    }),
  );
  const utils = render(
    <QueryClientProvider client={new QueryClient()}>
      <I18nProvider locale="en">
        <MemoryRouter initialEntries={["/w/ws/e/e1/fx-differences"]}>
          <Routes>
            <Route
              path="/w/:slug/e/:entityId/fx-differences"
              element={<FxDifferencesPage />}
            />
          </Routes>
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
  return { sent, ...utils };
}

describe("Exchange differences", () => {
  it("shows the positions and prepares one draft entry", async () => {
    const { sent, container } = mount();
    fireEvent.change(screen.getByLabelText("Revalue on"), {
      target: { value: "2026-03-31" },
    });
    const table = await screen.findByRole("table", {
      name: "Exchange differences",
    });
    const rows = within(table).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("2100 · Trade payables");
    expect(rows[1]).toHaveTextContent("Supplier US (Demo)");
    expect(rows[1]).toHaveTextContent("-3.00");
    expect(rows[1]).toHaveTextContent("Unrealised");
    expect(rows[2]).toHaveTextContent("No rate");
    expect(
      screen.getByText(/No closing rate is recorded for GBP/),
    ).toBeInTheDocument();
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);

    fireEvent.click(
      screen.getByRole("button", { name: "Prepare the draft entry" }),
    );
    const link = await screen.findByRole("link", { name: "Open the entry" });
    expect(link).toHaveAttribute("href", "/w/ws/e/e1/entries/e9");
    expect(sent).toEqual([
      {
        url: "/api/w/ws/entities/e1/fx-differences",
        body: { on: "2026-03-31" },
      },
    ]);
  });
});
