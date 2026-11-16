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
import { FixedAssetsPage } from "./pages/FixedAssets";

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const account = (id: string, code: string, name: string, type: string) => ({
  id,
  code,
  name,
  name_el: "",
  type,
  normal_side: type === "EXPENSE" ? "DEBIT" : "DEBIT",
  parent_id: null,
  is_postable: true,
  status: "ACTIVE",
  currency: "EUR",
  control_type: "",
  vat_role: "",
});
const van = {
  id: "a1",
  code: "VAN-1",
  name: "Delivery van",
  category: "VEHICLES",
  asset_account_id: "c1",
  accumulated_account_id: "c2",
  expense_account_id: "x1",
  acquired_on: "2026-01-15",
  cost: "24000.00",
  residual_value: "0.00",
  useful_life_months: 48,
  method: "STRAIGHT_LINE",
  annual_rate: null,
  disposed_on: null,
  disposal_proceeds: null,
  locked: true,
  accumulated: "2500.00",
  book_value: "21500.00",
  status: "ACTIVE",
  disposal_gain: null,
};

describe("Fixed assets (M6-1)", () => {
  it("lists the register, shows a schedule and prepares a draft entry", async () => {
    const sent: { url: string; body: unknown }[] = [];
    document.cookie = "__Host-fcp_csrftoken=test";
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init: RequestInit) => {
        if ((init.method ?? "GET") !== "GET") {
          sent.push({ url, body: JSON.parse(init.body as string) });
          return Promise.resolve(respond({}, 201));
        }
        if (url.includes("/accounts"))
          return Promise.resolve(
            respond([
              account("c1", "1010", "PPE - cost", "ASSET"),
              account("c2", "1019", "PPE - accumulated depreciation", "ASSET"),
              account("x1", "6600", "Depreciation", "EXPENSE"),
            ]),
          );
        if (url.includes("/schedule"))
          return Promise.resolve(
            respond({
              asset_id: "a1",
              convention: "Monthly; starts the month after acquisition.",
              rows: [
                {
                  month: "2026-02-01",
                  opening: "24000.00",
                  depreciation: "500.00",
                  closing: "23500.00",
                  accumulated: "500.00",
                  entry_id: "e1",
                },
              ],
            }),
          );
        if (url.includes("/depreciation-runs"))
          return Promise.resolve(
            respond([
              {
                id: "r1",
                month: "2026-02-01",
                total: "500.00",
                assets: 1,
                entry_id: "e1",
                entry_ref: "",
                entry_status: "DRAFT",
                cancelled: false,
                created_at: "2026-11-12T00:00:00Z",
              },
            ]),
          );
        if (url.includes("/fixed-assets"))
          return Promise.resolve(respond([van]));
        return Promise.resolve(respond([]));
      }),
    );
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider locale="en">
          <MemoryRouter initialEntries={["/w/ws/e/e1/fixed-assets"]}>
            <Routes>
              <Route
                path="/w/:slug/e/:entityId/fixed-assets"
                element={<FixedAssetsPage />}
              />
            </Routes>
          </MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    );
    const table = await screen.findByRole("table", {
      name: "Fixed-asset register",
    });
    const row = within(table).getByRole("row", { name: /VAN-1/ });
    expect(row).toHaveTextContent("Straight-line · 48 months");
    expect(row).toHaveTextContent("21,500.00");
    fireEvent.click(within(row).getByRole("button", { name: "Schedule" }));
    const schedule = await screen.findByRole("table", {
      name: "Schedule: VAN-1 Delivery van",
    });
    expect(
      within(schedule).getByRole("link", { name: "Prepared" }),
    ).toHaveAttribute("href", "/w/ws/e/e1/entries/e1");

    const runs = await screen.findByRole("table", { name: "Prepared months" });
    expect(runs).toHaveTextContent("Draft · draft");
    fireEvent.change(screen.getByLabelText("Month"), {
      target: { value: "2026-03" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Prepare the draft entry" }),
    );
    await waitFor(() =>
      expect(sent).toEqual([
        {
          url: "/api/w/ws/entities/e1/depreciation-runs",
          body: { month: "2026-03-01" },
        },
      ]),
    );

    // The new-asset form picks the usual accounts by default.
    fireEvent.click(screen.getByRole("button", { name: "Add a fixed asset" }));
    expect(screen.getByLabelText("Cost account")).toHaveValue("c1");
    expect(
      screen.getByLabelText("Accumulated depreciation account"),
    ).toHaveValue("c2");
    expect(screen.getByLabelText("Depreciation expense account")).toHaveValue(
      "x1",
    );
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => v.id)).toEqual([]);
    vi.unstubAllGlobals();
  });
});
