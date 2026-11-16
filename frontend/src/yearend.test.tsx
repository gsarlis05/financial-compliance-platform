import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import axe from "axe-core";
import { MemoryRouter, Route, Routes } from "react-router";
import { I18nProvider } from "./i18n/I18n";
import { PeriodsPage } from "./pages/Periods";

const year = (status: string) => ({
  id: "fy1", name: "2026", start_date: "2026-01-01", end_date: "2026-12-31", status,
  periods: [{ id: "p1", number: 1, start_date: "2026-01-01", end_date: "2026-01-31", status: "OPEN",
              is_adjustment: false }],
});
const accounts = [
  { id: "a3000", code: "3000", name: "Share capital", name_el: "", type: "EQUITY", is_postable: true, status: "ACTIVE" },
  { id: "a3200", code: "3200", name: "Retained earnings", name_el: "", type: "EQUITY", is_postable: true, status: "ACTIVE" },
  { id: "a4000", code: "4000", name: "Sales", name_el: "", type: "INCOME", is_postable: true, status: "ACTIVE" },
];
const openStatus = {
  fiscal_year_id: "fy1", name: "2026", status: "OPEN", end_date: "2026-12-31", result: "700.00",
  lines: [], blockers: [], closing_entry_id: null, closing_entry_status: null, reopen_entry_id: null, checks: [],
};
const closedStatus = {
  ...openStatus, status: "CLOSED", result: "0.00", closing_entry_id: "e9", closing_entry_status: "POSTED",
  checks: [{ code: "result_closed", ok: true, details: [] },
           { code: "opening_equals_closing_balance_sheet", ok: true, details: [] }],
};

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <I18nProvider locale="en">
        <MemoryRouter initialEntries={["/w/demo/e/ent/periods"]}>
          <Routes>
            <Route path="/w/:slug/e/:entityId/periods" element={<PeriodsPage />} />
          </Routes>
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("Year-end close (M2-9)", () => {
  const calls: { url: string; method: string; body: string | undefined }[] = [];
  afterEach(() => vi.unstubAllGlobals());

  function stub(fyStatus: string, status: unknown) {
    calls.length = 0;
    document.cookie = "__Host-fcp_csrftoken=test";
    vi.stubGlobal("fetch", vi.fn((url: string, init: RequestInit) => {
      calls.push({ url, method: init.method ?? "GET", body: init.body as string | undefined });
      if (url.includes("/close") && (init.method ?? "GET") === "POST") {
        return Promise.resolve(respond({ id: "e9", status: "SUBMITTED" }, 201));
      }
      if (url.includes("/close")) return Promise.resolve(respond(status));
      if (url.includes("/fiscal-years")) return Promise.resolve(respond([year(fyStatus)]));
      if (url.includes("/accounts")) return Promise.resolve(respond(accounts));
      return Promise.resolve(respond([]));
    }));
  }

  it("previews the result and generates the closing entry to retained earnings", async () => {
    stub("OPEN", openStatus);
    const { container } = renderPage();
    fireEvent.click(await screen.findByText("Year-end close"));
    const panel = screen.getByText("Year-end close").closest("details") as HTMLElement;
    expect(await within(panel).findByText("700.00")).toBeInTheDocument();
    const account = within(panel).getByLabelText<HTMLSelectElement>("Retained earnings account");
    await waitFor(() => expect(account.value).toBe("a3200"));
    expect(Array.from(account.options).map((o) => o.value)).toEqual(["a3000", "a3200"]);
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((v) => v.id)).toEqual([]);
    fireEvent.click(within(panel).getByRole("button", { name: "Generate closing entry" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const post = calls.find((c) => c.method === "POST");
    expect(post?.url).toBe("/api/w/demo/entities/ent/fiscal-years/fy1/close");
    expect(JSON.parse(post?.body ?? "{}")).toEqual({ retained_earnings_account_id: "a3200" });
    expect(await within(panel).findByRole("link", { name: "Closing entry" })).toHaveAttribute(
      "href", "/w/demo/e/ent/entries/e9");
  });

  it("shows a closed year with its checks and offers to re-open it", async () => {
    stub("CLOSED", closedStatus);
    renderPage();
    expect(await screen.findByText("Closed")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Year-end close"));
    expect(await screen.findByText(/Income and expense accounts are zero/)).toHaveTextContent("✓");
    expect(screen.getByRole("button", { name: "Re-open the year" })).toBeInTheDocument();
  });
});
