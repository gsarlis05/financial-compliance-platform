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
import { CounterpartiesPage } from "./pages/Counterparties";

const party = {
  id: "c1",
  code: "C1",
  name: "Alpha (Demo)",
  kind: "CUSTOMER",
  vat_no: "",
  email: "",
  payment_terms_days: 30,
  status: "ACTIVE",
  days_late_override: null,
};
const rows = [
  {
    counterparty_id: "c1",
    counterparty_code: "C1",
    observed_days_late: 4,
    sample: 4,
    override: null,
    days_late: 4,
    note: "Observed over 4 invoices settled in the last 12 months.",
  },
  {
    counterparty_id: "c2",
    counterparty_code: "C2",
    observed_days_late: null,
    sample: 1,
    override: null,
    days_late: 0,
    note: "Only 1 invoice(s) settled in the last 12 months (at least 3 needed): 0 days late is assumed.",
  },
];

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Payment behaviour (M3-6)", () => {
  const calls: { url: string; method: string; body: unknown }[] = [];
  beforeEach(() => {
    calls.length = 0;
    document.cookie = "__Host-fcp_csrftoken=test";
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init: RequestInit) => {
        const method = init.method ?? "GET";
        calls.push({
          url,
          method,
          body: init.body ? JSON.parse(init.body as string) : null,
        });
        if (method === "PATCH")
          return Promise.resolve(respond({ ...party, days_late_override: 15 }));
        if (url.includes("/payment-behaviour"))
          return Promise.resolve(respond(rows));
        if (url.endsWith("/counterparties"))
          return Promise.resolve(respond([party]));
        return Promise.resolve(respond({}, 404));
      }),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows observed days late, explains a small sample and saves an override", async () => {
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider locale="en">
          <MemoryRouter initialEntries={["/w/demo/e/ent/counterparties"]}>
            <Routes>
              <Route
                path="/w/:slug/e/:entityId/counterparties"
                element={<CounterpartiesPage />}
              />
            </Routes>
          </MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    );
    const section = await screen.findByRole("region", {
      name: "Payment behaviour",
    });
    const c1 = await within(section).findByRole("row", { name: /C1/ });
    expect(c1).toHaveTextContent("Observed over 4 invoices");
    const c2 = within(section).getByRole("row", { name: /C2/ });
    expect(c2).toHaveTextContent("not enough data");
    expect(c2).toHaveTextContent("at least 3 needed");
    fireEvent.change(within(c1).getByLabelText("Override (days) C1"), {
      target: { value: "15" },
    });
    fireEvent.click(within(c1).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "PATCH")).toBe(true),
    );
    const patch = calls.find((c) => c.method === "PATCH");
    expect(patch?.url).toMatch(/\/counterparties\/c1$/);
    expect(patch?.body).toEqual({ days_late_override: 15 });

    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => v.id)).toEqual([]);
  });
});
