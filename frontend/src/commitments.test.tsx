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
import { CommitmentsPage, fromPercent, toPercent } from "./pages/Commitments";

const rent = {
  id: "o1",
  series_id: "s1",
  version: 2,
  name: "Office rent",
  category: "RENT",
  direction: "OUTFLOW",
  amount: "1500.00",
  currency: "EUR",
  frequency: "MONTHLY",
  interval: 1,
  day_of_month: 1,
  start_date: "2026-01-01",
  end_date: null,
  adjust: "FOLLOWING",
  contractual: true,
  nature: "COMMITTED",
  counterparty_id: null,
  note: "",
  superseded_at: null,
  created_at: "2026-01-01T00:00:00Z",
};
const loan = {
  id: "d1",
  series_id: "s2",
  version: 1,
  name: "Term loan",
  kind: "TERM_LOAN",
  principal: "1200.00",
  facility_limit: null,
  start_date: "2026-01-15",
  maturity_date: "2027-01-15",
  payment_frequency_months: 1,
  rate_type: "VARIABLE",
  fixed_rate: null,
  reference_rate_key: "EURIBOR_3M",
  margin: "0.020000",
  assumed_reference_rate: "0.100000",
  day_count: "30_360",
  repayment_type: "ANNUITY",
  interest_only_periods: 0,
  adjust: "NONE",
  lender_id: null,
  note: "",
  superseded_at: null,
  created_at: "2026-01-01T00:00:00Z",
};
const instalment = {
  number: 1,
  period_start: "2026-01-15",
  period_end: "2026-02-15",
  due: "2026-02-15",
  opening: "1200.00",
  interest: "12.00",
  principal: "94.62",
  payment: "106.62",
  closing: "1105.38",
};
const flow = {
  due: "2026-02-02",
  scheduled: "2026-02-01",
  amount: "-1500.00",
  nature: "COMMITTED",
  source: "OBLIGATION",
  component: "PAYMENT",
  category: "RENT",
  name: "Office rent",
  series_id: "s1",
  version_id: "o1",
};

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("percent text", () => {
  it.each([
    ["0.05", "5"],
    ["0.0425", "4.25"],
    ["0.125000", "12.5"],
    ["0.100000", "10"],
    ["1.00", "100"],
    ["0", "0"],
  ])("shows the fraction %s as %s%%", (fraction, percent) => {
    expect(toPercent(fraction)).toBe(percent);
  });

  it.each([
    ["5", "0.05"],
    ["4.25", "0.0425"],
    ["12.5", "0.125"],
    ["0", "0.00"],
    ["150", "1.50"],
    ["0.5", "0.005"],
  ])("sends %s%% as the fraction %s", (percent, fraction) => {
    expect(fromPercent(percent)).toBe(fraction);
  });

  it("leaves empty and invalid text to the server", () => {
    expect(fromPercent("  ")).toBeNull();
    expect(fromPercent("5%")).toBe("5%");
    expect(toPercent(null)).toBe("");
  });
});

describe("Obligations and loans page (M3-4)", () => {
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
        if (method === "PUT" && url.endsWith("/obligations/s1")) {
          return Promise.resolve(
            respond({ ...rent, version: 3, amount: "1600.00" }),
          );
        }
        if (url.endsWith("/obligations"))
          return Promise.resolve(respond([rent]));
        if (url.endsWith("/debt-instruments"))
          return Promise.resolve(respond([loan]));
        if (url.endsWith("/s2/schedule"))
          return Promise.resolve(respond([instalment]));
        if (url.endsWith("/holidays")) {
          return Promise.resolve(
            respond([{ id: "h1", day: "2026-06-01", name: "Synthetic" }]),
          );
        }
        if (url.includes("/commitment-flows"))
          return Promise.resolve(respond([flow]));
        return Promise.resolve(respond({}, 404));
      }),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  it("lists commitments with their nature, shows a schedule and saves a new version", async () => {
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider locale="en">
          <MemoryRouter initialEntries={["/w/demo/e/ent/commitments"]}>
            <Routes>
              <Route
                path="/w/:slug/e/:entityId/commitments"
                element={<CommitmentsPage />}
              />
            </Routes>
          </MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    );
    const obligations = await screen.findByRole("region", {
      name: "Recurring obligations",
    });
    const row = await within(obligations).findByRole("row", {
      name: /Office rent/,
    });
    expect(row).toHaveTextContent("Committed");
    expect(row).toHaveTextContent("-1,500.00");
    const debts = screen.getByRole("region", { name: "Loans and facilities" });
    expect(
      await within(debts).findByText("EURIBOR_3M + 2% (assumed 10%)"),
    ).toBeInTheDocument();
    fireEvent.click(within(debts).getByRole("button", { name: "Schedule" }));
    expect(
      await screen.findByRole("table", { name: "Instalments" }),
    ).toHaveTextContent("106.62");
    const upcoming = screen.getByRole("region", {
      name: "Upcoming flows (next 90 days)",
    });
    expect(
      await within(upcoming).findByText("Office rent"),
    ).toBeInTheDocument();

    fireEvent.click(within(row).getByRole("button", { name: "Change" }));
    const form = within(obligations)
      .getByRole("heading", { name: "Change obligation (new version)" })
      .closest("form") as HTMLFormElement;
    fireEvent.change(within(form).getByLabelText("Amount"), {
      target: { value: "1600.00" },
    });
    fireEvent.click(
      within(form).getByRole("button", { name: "Save new version" }),
    );
    await waitFor(() =>
      expect(calls.some((c) => c.method === "PUT")).toBe(true),
    );
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.url).toMatch(/\/obligations\/s1$/);
    expect(put?.body).toMatchObject({
      amount: "1600.00",
      day_of_month: 1,
      contractual: true,
    });

    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => v.id)).toEqual([]);
  });
});
