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
import { AlertsPage } from "./pages/Alerts";

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const open = {
  id: "a1",
  key: "goal:g1:status",
  kind: "GOAL_STATUS",
  state: "OFF_TRACK",
  severity: "CRITICAL",
  title: "Goal Revenue 12k is off track",
  detail: "Evaluated as of 2026-03-31; gap to target 2000.00",
  subject_type: "goal",
  subject_id: "g1",
  period: "2026-12-31",
  source_run_id: "r1",
  created_at: "2026-11-10T12:00:00Z",
  acknowledged_by_name: "",
  acknowledged_at: null,
  acknowledgement_note: "",
};

describe("Alerts (M4-7)", () => {
  it("lists, checks budgets and acknowledges accessibly", async () => {
    const calls: { url: string; method: string; body: unknown }[] = [];
    let acknowledged = false;
    document.cookie = "__Host-fcp_csrftoken=test";
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init: RequestInit) => {
        const method = init.method ?? "GET";
        calls.push({
          url,
          method,
          body: typeof init.body === "string" ? JSON.parse(init.body) : null,
        });
        if (url.includes("/check-budgets"))
          return Promise.resolve(respond({ raised: 0 }));
        if (url.endsWith("/acknowledge")) {
          acknowledged = true;
          return Promise.resolve(respond({ ...open, acknowledged_at: "x" }));
        }
        if (url.includes("/alerts?"))
          return Promise.resolve(respond(acknowledged ? [] : [open]));
        return Promise.resolve(
          respond({ status: 404, code: "not_found", detail: "x" }, 404),
        );
      }),
    );
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider locale="en">
          <MemoryRouter initialEntries={["/w/demo/e/ent/alerts"]}>
            <Routes>
              <Route
                path="/w/:slug/e/:entityId/alerts"
                element={<AlertsPage />}
              />
            </Routes>
          </MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    );
    const card = await screen.findByRole("region", {
      name: /Goal Revenue 12k is off track/,
    });
    expect(card).toHaveTextContent("Critical");
    expect(within(card).getByRole("link", { name: "Open" })).toHaveAttribute(
      "href",
      "/w/demo/e/ent/goals",
    );
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => v.id)).toEqual([]);

    fireEvent.click(screen.getByRole("button", { name: "Check budgets now" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "New alerts: 0",
    );

    fireEvent.change(within(card).getByLabelText("Note (optional)"), {
      target: { value: "Plan agreed" },
    });
    fireEvent.click(within(card).getByRole("button", { name: "Acknowledge" }));
    await waitFor(() =>
      expect(
        calls.find((c) => c.url.endsWith("/a1/acknowledge"))?.body,
      ).toEqual({
        note: "Plan agreed",
      }),
    );
    expect(await screen.findByText("No open alerts.")).toBeInTheDocument();
    vi.unstubAllGlobals();
  });
});
