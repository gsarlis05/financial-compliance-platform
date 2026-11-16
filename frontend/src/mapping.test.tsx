import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import axe from "axe-core";
import { MemoryRouter, Route, Routes } from "react-router";
import { I18nProvider } from "./i18n/I18n";
import { MappingPage } from "./pages/Mapping";

const taxonomy = [
  { code: "BS.CASH", name: "Cash and cash equivalents", name_el: "", statement: "BS", section: "CURRENT_ASSETS",
    account_types: ["ASSET"], direction: "HIGHER_BETTER", order: 90 },
  { code: "OPEX.RENT", name: "Rent", name_el: "", statement: "PL", section: "OPERATING_EXPENSES",
    account_types: ["EXPENSE"], direction: "LOWER_BETTER", order: 230 },
];
const rows = [
  { account_id: "a1", account_code: "1300", account_name: "Bank", account_type: "ASSET", line_code: null,
    balance: "-100.00", has_activity: true },
  { account_id: "a2", account_code: "6100", account_name: "Rent", account_type: "EXPENSE", line_code: "OPEX.RENT",
    balance: "100.00", has_activity: true },
];
const completeness = {
  as_of: "2026-12-31", taxonomy: "IFRS_SME_CY@1.0", complete: false, mapped: 1,
  unmapped_blocking: [rows[0]], unmapped_warning: [], unmapped_idle: 0,
};

function respond(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

describe("Statement mapping page (M2-6)", () => {
  const calls: { url: string; method: string; body: string | undefined }[] = [];
  beforeEach(() => {
    calls.length = 0;
    document.cookie = "__Host-fcp_csrftoken=test";
    vi.stubGlobal("fetch", vi.fn((url: string, init: RequestInit) => {
      calls.push({ url, method: init.method ?? "GET", body: init.body as string | undefined });
      if (url.includes("/taxonomy")) return Promise.resolve(respond(taxonomy));
      if (url.includes("/account-mapping/completeness")) return Promise.resolve(respond(completeness));
      if (url.includes("/account-mapping?")) return Promise.resolve(respond(rows));
      return Promise.resolve(respond({ account_id: "a1", line_code: "BS.CASH" }));
    }));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows what blocks statements and offers only compatible lines", async () => {
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider locale="en">
          <MemoryRouter initialEntries={["/w/demo/e/ent/mapping"]}>
            <Routes>
              <Route path="/w/:slug/e/:entityId/mapping" element={<MappingPage />} />
            </Routes>
          </MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByTestId("mapping-status")).toHaveTextContent("Statements are blocked");
    expect(screen.getByTestId("mapping-status")).toHaveTextContent("1300");
    const cash = await screen.findByLabelText<HTMLSelectElement>("Statement line 1300");
    await waitFor(() => expect(cash.options.length).toBe(2));
    expect(Array.from(cash.options).map((o) => o.text)).toEqual([
      "— not mapped —",
      "BS.CASH · Cash and cash equivalents",
    ]);
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((v) => v.id)).toEqual([]);
    fireEvent.change(cash, { target: { value: "BS.CASH" } });
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.url).toBe("/api/w/demo/entities/ent/account-mapping/a1");
    expect(JSON.parse(put?.body ?? "{}")).toEqual({ line_code: "BS.CASH" });
  });
});
