import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import axe from "axe-core";
import { MemoryRouter, Route, Routes } from "react-router";
import { I18nProvider } from "./i18n/I18n";
import { PortfolioPage } from "./pages/Portfolio";

const ok = <T,>(data: T) => ({ status: "ok", reason: "", data });

const rows = [
  {
    entity_id: "e1",
    legal_name: "Client A",
    entity_type: "COMPANY",
    cash: ok({
      as_of: "2026-11-01",
      stale: false,
      opening: "12000.00",
      first_shortfall: "2026-12-14",
    }),
    kpis: ok({
      stale: false,
      cards: [
        {
          key: "GROSS_MARGIN",
          name: "Gross margin",
          name_el: "",
          display: "percent",
          direction: "HIGHER_BETTER",
          result_id: "r",
          value: "0.45",
          nm_reason: "",
          nature: "ACTUAL",
          comparison_value: null,
        },
        {
          key: "DSO",
          name: "DSO",
          name_el: "",
          display: "days",
          direction: "LOWER_BETTER",
          result_id: "r2",
          value: null,
          nm_reason: "Revenue is zero",
          nature: "ACTUAL",
          comparison_value: null,
        },
      ],
    }),
    goals: ok({
      ON_TRACK: 2,
      AT_RISK: 1,
      OFF_TRACK: 0,
      UNDETERMINED: 0,
      NOT_EVALUATED: 0,
    }),
    alerts: ok({ critical: 1, warning: 2 }),
  },
  {
    entity_id: "e2",
    legal_name: "Client B",
    entity_type: "COMPANY",
    client_slug: "client-b", // a client in its own workspace (engagement grant, M5-4)
    cash: {
      status: "empty",
      reason: "No cash forecast yet: run one first.",
      data: {},
    },
    kpis: {
      status: "empty",
      reason: "No KPI set for the year to date yet.",
      data: {},
    },
    goals: ok({
      ON_TRACK: 0,
      AT_RISK: 0,
      OFF_TRACK: 0,
      UNDETERMINED: 0,
      NOT_EVALUATED: 0,
    }),
    alerts: ok({ critical: 0, warning: 0 }),
  },
];

describe("Firm portfolio (M4-9)", () => {
  it("shows a row per accessible client with links and reasons", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(JSON.stringify(rows), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        ),
      ),
    );
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider locale="en">
          <MemoryRouter initialEntries={["/w/firm/e/e1/portfolio"]}>
            <Routes>
              <Route
                path="/w/:slug/e/:entityId/portfolio"
                element={<PortfolioPage />}
              />
            </Routes>
          </MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    );
    const table = await screen.findByRole("table", { name: "Clients" });
    const a = within(table).getByRole("row", { name: /Client A/ });
    expect(a).toHaveTextContent("12,000.00");
    expect(a).toHaveTextContent("First shortfall 2026-12-14");
    expect(a).toHaveTextContent("45.00%");
    expect(a).toHaveTextContent("Not meaningful");
    expect(a).toHaveTextContent("2 / 1 / 0");
    expect(a).toHaveTextContent("1 / 2");
    expect(within(a).getByRole("link", { name: "Client A" })).toHaveAttribute(
      "href",
      "/w/firm/e/e1/dashboard",
    );
    const b = within(table).getByRole("row", { name: /Client B/ });
    expect(b).toHaveTextContent("No cash forecast yet");
    expect(b).toHaveTextContent("No KPI set for the year to date yet.");
    expect(b).toHaveTextContent("client's own workspace");
    expect(within(b).getByRole("link", { name: "Client B" })).toHaveAttribute(
      "href",
      "/w/client-b/e/e2/dashboard",
    );
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => v.id)).toEqual([]);
    vi.unstubAllGlobals();
  });
});
