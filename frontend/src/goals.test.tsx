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
import { GoalsPage, formatValue, toFraction } from "./pages/Goals";

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const version = {
  id: "v1",
  number: 1,
  target_type: "ABSOLUTE",
  target_input: "0.35",
  target_value: "0.35",
  direction: "AT_LEAST",
  materiality: "0.05",
  owner_id: "u1",
  driver: "",
  baseline_value: "0.5714285714",
  baseline_nm_reason: "",
  baseline_from: "2025-01-01",
  baseline_to: "2025-12-31",
  baseline_run_id: "r0",
  reason: "",
  created_at: "2026-11-07T10:00:00Z",
  superseded_at: null,
};
const goal = {
  id: "g1",
  name: "EBITDA margin 35%",
  metric: "kpi:EBITDA_MARGIN",
  metric_name: "EBITDA margin",
  metric_kind: "RATIO",
  metric_ref: "CORE@1.0:EBITDA_MARGIN",
  unit: "ratio",
  display: "percent",
  period_start: "2026-01-01",
  period_end: "2026-12-31",
  status: "ACTIVE",
  current: version,
  versions: [version],
  latest: null,
};
const f = (key: string, value: string | null, extra: object = {}) => ({
  result_id: `${key}-${String(value)}`,
  key,
  dimensions: [],
  period_start: "2026-01-01",
  period_end: "2026-12-31",
  granularity: "POINT",
  nature: "TARGET",
  value,
  unit: "ratio",
  nm_reason: value === null ? "Not achievable within ±100% of REVENUE" : "",
  ...extra,
});
const evaluation = {
  goal_id: "g1",
  version: 1,
  run_id: "r1",
  run_status: "VALID",
  watermark: 12,
  as_of: "2026-03-31",
  cut_over: "2026-03-31",
  status: "OFF_TRACK",
  method: "BUDGET",
  method_note: "Actuals to 2026-03-31, then the approved budget",
  out_of_date: false,
  figures: [
    f("goal.target", "0.35"),
    f("goal.projected", "0.3", { nature: "BUDGET" }),
    f("goal.required.driver_change", "0.0855", { dimensions: ["REVENUE"] }),
    f("goal.comparison", "0.3", { dimensions: ["BUDGET"] }),
    f("goal.contribution", "-0.14", { dimensions: ["REV.SALES", "BUDGET"] }),
    f("goal.contribution.residual", "0.0233"),
    f("goal.contribution.total", "0"),
    f("goal.trend", "0.2", {
      key: "goal.trend",
      nature: "ACTUAL",
      period_start: "2026-03-01",
      period_end: "2026-03-31",
    }),
  ],
  history: [],
};

describe("Goals (M4-6)", () => {
  it("converts and formats percentages", () => {
    expect(toFraction("35", true)).toBe("0.35");
    expect(toFraction("12000", false)).toBe("12000");
    expect(formatValue("0.3", "ratio", "percent", "en")).toBe("30.00%");
  });

  it("creates, evaluates and explains a goal accessibly", async () => {
    const calls: { url: string; method: string; body: unknown }[] = [];
    let evaluated = false;
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
        if (url.includes("/goal-metrics"))
          return Promise.resolve(
            respond([
              {
                key: "kpi:EBITDA_MARGIN",
                ref: "CORE@1.0:EBITDA_MARGIN",
                name: "EBITDA margin",
                name_el: "",
                kind: "RATIO",
                formula: "x",
                direction: "HIGHER_BETTER",
                unit: "ratio",
                display: "percent",
                convention: "EBITDA over revenue.",
              },
            ]),
          );
        if (url.endsWith("/goals") && method === "POST")
          return Promise.resolve(respond(goal, 201));
        if (url.includes("/goals?")) return Promise.resolve(respond([goal]));
        if (url.endsWith("/evaluations") && method === "POST") {
          evaluated = true;
          return Promise.resolve(respond(evaluation, 201));
        }
        if (url.endsWith("/evaluations/latest"))
          return Promise.resolve(
            evaluated
              ? respond(evaluation)
              : respond({ status: 404, code: "not_found", detail: "x" }, 404),
          );
        return Promise.resolve(
          respond({ status: 404, code: "not_found", detail: "x" }, 404),
        );
      }),
    );
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider locale="en">
          <MemoryRouter initialEntries={["/w/demo/e/ent/goals"]}>
            <Routes>
              <Route
                path="/w/:slug/e/:entityId/goals"
                element={<GoalsPage />}
              />
            </Routes>
          </MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "New goal" }));
    const form = screen.getByRole("region", { name: "New goal" });
    fireEvent.change(within(form).getByLabelText("Name"), {
      target: { value: "EBITDA margin 35%" },
    });
    const metric = await within(form).findByRole("option", {
      name: "EBITDA margin",
    });
    fireEvent.change(within(form).getByLabelText("Metric"), {
      target: { value: (metric as HTMLOptionElement).value },
    });
    fireEvent.change(within(form).getByLabelText("Target (%)"), {
      target: { value: "35" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Create goal" }));
    await waitFor(() =>
      expect(
        calls.find((c) => c.url.endsWith("/goals") && c.method === "POST")
          ?.body,
      ).toMatchObject({
        metric: "kpi:EBITDA_MARGIN",
        target: "0.35",
        materiality: "0.05",
      }),
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "EBITDA margin 35%" }),
    );
    expect(await screen.findByText("Not evaluated yet: choose Evaluate."));
    fireEvent.click(screen.getByRole("button", { name: "Evaluate" }));
    const panel = await screen.findByRole("region", {
      name: /Evaluation as of 2026-03-31/,
    });
    expect(panel).toHaveTextContent("Off track");
    expect(panel).toHaveTextContent(
      "Actuals to 2026-03-31, then the approved budget",
    );
    expect(panel).toHaveTextContent("30.00%");
    expect(panel).toHaveTextContent("REVENUE: 8.55%");
    const table = within(panel).getByRole("table", {
      name: /Contribution analysis against budget/,
    });
    expect(table).toHaveTextContent("REV.SALES");
    expect(table).toHaveTextContent("Residual (interaction between lines)");

    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => v.id)).toEqual([]);
    vi.unstubAllGlobals();
  });
});
