// Tax rules (brief 27, T-2, #255): the rules in force with their corrections, and a correction
// sent with its start and source. Rates are typed as percentages and sent as exact fractions.
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
import { TaxRulesPage, percentToFraction } from "./pages/TaxRules";

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const s19 = {
  id: "CY:S19:open",
  code: "S19",
  name: "Standard rate (Demo)",
  name_el: "",
  treatment: "STANDARD",
  category: "DOMESTIC",
  rate: "0.2000",
  valid_from: null,
  valid_to: null,
  verified: false,
  verification_note: "",
  review_status: "OWNER_CHECKED",
  corrected_from: "2026-04-01",
  correction_source: "Synthetic notice (Demo)",
};

describe("Tax rules", () => {
  it("converts percentages without floating point", () => {
    expect(percentToFraction("19")).toBe("0.19");
    expect(percentToFraction("19,5")).toBe("0.195");
    expect(percentToFraction("5")).toBe("0.05");
    expect(percentToFraction("0")).toBe("0");
    expect(percentToFraction("12.25")).toBe("0.1225");
    expect(percentToFraction("150")).toBeNull();
    expect(percentToFraction("abc")).toBeNull();
  });

  it("shows a correction in force and sends a new one", async () => {
    const sent: { url: string; body: unknown }[] = [];
    document.cookie = "__Host-fcp_csrftoken=test";
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init: RequestInit) => {
        if ((init.method ?? "GET") === "POST") {
          sent.push({ url, body: JSON.parse(init.body as string) });
          return Promise.resolve(respond({}, 201));
        }
        if (url.includes("/vat-codes")) return Promise.resolve(respond([s19]));
        if (url.includes("/vat-box-rules"))
          return Promise.resolve(
            respond([
              {
                category: "EXEMPT",
                line: "NET_PURCHASE",
                status: "UNSUPPORTED",
                boxes: [],
                reason: "Not in the specification.",
                corrected_from: null,
              },
            ]),
          );
        return Promise.resolve(respond([]));
      }),
    );
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider locale="en">
          <MemoryRouter initialEntries={["/w/ws/e/e1/tax-rules"]}>
            <Routes>
              <Route
                path="/w/:slug/e/:entityId/tax-rules"
                element={<TaxRulesPage />}
              />
            </Routes>
          </MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    );
    const codes = await screen.findByRole("table", { name: "VAT codes" });
    await within(codes).findByText("20%");
    expect(codes).toHaveTextContent("01/04/2026 · Synthetic notice (Demo)");
    expect(
      await screen.findByRole("table", { name: "VAT return box rules" }),
    ).toHaveTextContent("Not mapped (an exception)");
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);

    const form = within(
      screen.getByRole("form", { name: "Correct a VAT code" }),
    );
    fireEvent.change(form.getByLabelText("Code"), { target: { value: "S19" } });
    fireEvent.change(form.getByLabelText(/New rate/), {
      target: { value: "21" },
    });
    fireEvent.change(form.getByLabelText("For lines dated from"), {
      target: { value: "2027-01-01" },
    });
    fireEvent.change(form.getByLabelText(/Source/), {
      target: { value: "Synthetic law (Demo)" },
    });
    fireEvent.click(form.getByRole("button", { name: "Save the correction" }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toEqual({
      url: "/api/w/ws/entities/e1/vat-codes/S19/corrections",
      body: {
        effective_from: "2027-01-01",
        rate: "0.21",
        source: "Synthetic law (Demo)",
        note: "",
      },
    });
  });
});
