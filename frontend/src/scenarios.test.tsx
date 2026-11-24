import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import axe from "axe-core";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { I18nProvider } from "./i18n/I18n";
import { GoalScenarios } from "./pages/GoalScenarios";
import { ScenariosPage, toParams } from "./pages/Scenarios";
import { SensitivityPage } from "./pages/Sensitivity";
import { WorkingCapitalPage } from "./pages/WorkingCapital";

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const API = "/api/w/ws/entities/e1";
const set = {
  id: "s1",
  family_id: "f1",
  version: 2,
  name: "Plan 2027",
  cutover: "2026-12-31",
  months: 12,
  start_from: "ACTUALS",
  note: "",
  status: "APPROVED",
  supersedes_id: null,
  created_at: "2026-11-12T00:00:00Z",
  approved_at: "2026-11-12T00:00:00Z",
};
const scenario = {
  id: "sc1",
  name: "Slow second half",
  description: "",
  status: "DRAFT",
  base_set_id: "s1",
  copied_from_id: null,
  created_by_id: "u1",
  created_at: "2026-11-15T00:00:00Z",
  shared_at: null,
  archived_at: null,
  nature: "HYPOTHETICAL",
};
const shared = { ...scenario, id: "sc2", name: "Price rise", status: "SHARED" };
const detail = {
  scenario,
  base: {
    id: "s1",
    name: "Plan 2027",
    version: 2,
    status: "APPROVED",
    newer_version_approved: false,
    first_month: "2027-01-01",
    last_month: "2027-12-01",
    loans: ["TERM-1"],
  },
  overrides: [
    {
      id: "o1",
      seq: 1,
      type: "PCT_CHANGE",
      params: { driver: "revenue", percent: "-25", start_month: "2027-07" },
      rationale: "Slower orders",
    },
  ],
};
const liquidity = {
  lowest_cash: "100.00",
  lowest_cash_month: "2026-12-01",
  first_negative_month: null,
  months_below_minimum: 0,
  peak_facility: "0.00",
  closing_debt: "0.00",
};
const comparison = {
  scenario,
  base: detail.base,
  watermark: 7,
  granularity: "YEAR",
  columns: [
    { start: "2026-12-01", end: "2026-12-31", nature: "ACTUAL" },
    { start: "2027-01-01", end: "2027-12-31", nature: "HYPOTHETICAL" },
  ],
  rows: [
    {
      key: "PL.REVENUE",
      base: [null, "12000.00"],
      scenario: [null, "10500.00"],
      difference: [null, "-1500.00"],
      overrides: [[], ["o1"]],
    },
    {
      key: "BS.CASH",
      base: ["100.00", "4000.00"],
      scenario: ["100.00", "2500.00"],
      difference: ["0.00", "-1500.00"],
      overrides: [[], ["o1"]],
    },
  ],
  effects: [
    {
      override_id: "o1",
      seq: 1,
      type: "PCT_CHANGE",
      label: "Percent change",
      changes: { "PL.REVENUE": "-1500.00", "BS.CASH": "-1500.00" },
    },
    {
      override_id: null,
      seq: null,
      type: "TOTAL",
      label: "Total change",
      changes: { "PL.REVENUE": "-1500.00", "BS.CASH": "-1500.00" },
    },
  ],
  liquidity: { base: liquidity, scenario: { ...liquidity } },
  valid: true,
  failures: [],
  notes: [],
  nature: "HYPOTHETICAL",
  engine_status: "PENDING_PROFESSIONAL_REVIEW",
};

function mount(path: string, route: string, element: ReactElement) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <I18nProvider locale="en">
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path={route} element={element} />
          </Routes>
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

type Sent = { url: string; method: string; body?: unknown };

function stub(get: (url: string) => unknown, post: (url: string) => unknown) {
  const sent: Sent[] = [];
  document.cookie = "__Host-fcp_csrftoken=test";
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init: RequestInit) => {
      const method = init.method ?? "GET";
      if (method === "GET") return Promise.resolve(respond(get(url)));
      sent.push(
        init.body
          ? { url, method, body: JSON.parse(init.body as string) }
          : { url, method },
      );
      return Promise.resolve(respond(post(url)));
    }),
  );
  return sent;
}

async function accessible(container: HTMLElement) {
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);
}

describe("override parameters", () => {
  it("sends only the visible fields, whole numbers as numbers", () => {
    expect(
      toParams("TIMING_SHIFT", { mode: "DAYS", driver: "dso", days: "30" }),
    ).toEqual({ mode: "DAYS", driver: "dso", days: 30 });
    expect(
      toParams("RATE_CHANGE", {
        target: "LOANS",
        loans: "TERM-1, TERM-2",
        points: "2",
      }),
    ).toEqual({ target: "LOANS", loans: ["TERM-1", "TERM-2"], points: "2" });
    // A select left untouched sends its first option; empty optional fields are left out.
    expect(toParams("PCT_CHANGE", { percent: "-15", end_month: "" })).toEqual({
      driver: "revenue",
      percent: "-15",
    });
  });
});

describe("Scenarios (M7-7)", () => {
  it("builds a scenario, compares it with its base and says it is hypothetical", async () => {
    const sent = stub(
      (url) => {
        if (url.includes("/comparison")) return comparison;
        if (url.includes("/scenarios/sc1")) return detail;
        if (url.includes("/scenarios")) return [scenario];
        return [set];
      },
      (url) =>
        url.endsWith("/runs")
          ? { id: "r9", status: "VALID", output_hash: "h" }
          : detail.overrides[0],
    );
    const { container } = mount(
      "/w/ws/e/e1/scenarios",
      "/w/:slug/e/:entityId/scenarios",
      <ScenariosPage />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Slow second half" }),
    );
    const builder = await screen.findByRole("region", {
      name: /Slow second half/,
    });
    expect(within(builder).getByText("Hypothetical")).toBeInTheDocument();
    const changes = within(builder).getByRole("table", {
      name: "Changes, in the order they apply",
    });
    expect(within(changes).getByText("Percent change")).toBeInTheDocument();
    expect(within(changes).getByText(/percent: -25/)).toBeInTheDocument();

    // Add a change: the form shows the fields of the chosen kind.
    fireEvent.change(within(builder).getByLabelText("Kind of change"), {
      target: { value: "NEW_HIRE" },
    });
    fireEvent.change(within(builder).getByLabelText("Role"), {
      target: { value: "Analyst" },
    });
    fireEvent.change(within(builder).getByLabelText("How many"), {
      target: { value: "2" },
    });
    fireEvent.click(within(builder).getByRole("button", { name: "Add" }));
    await waitFor(() =>
      expect(sent[0]).toMatchObject({
        url: `${API}/scenarios/sc1/overrides`,
        method: "POST",
        body: { type: "NEW_HIRE", params: { role: "Analyst", headcount: 2 } },
      }),
    );

    // Compare: base and scenario per line, the difference, and what changed adds up.
    const panel = screen.getByRole("region", { name: "Compare with the base" });
    expect(within(panel).getByRole("note")).toHaveTextContent(
      /Pending professional review/,
    );
    fireEvent.click(within(panel).getByRole("button", { name: "Compare now" }));
    const table = await within(panel).findByRole("table", {
      name: "The base and the scenario, with the difference",
    });
    expect(within(table).getByText("10,500.00")).toBeInTheDocument();
    expect(within(table).getAllByText("-1,500.00").length).toBeGreaterThan(0);
    expect(
      within(table).getAllByText("Slow second half (Hypothetical)"),
    ).toHaveLength(2);
    const changed = within(panel).getByRole("table", {
      name: /What changed and why/,
    });
    expect(
      within(changed).getByRole("rowheader", { name: "1. Percent change" }),
    ).toBeInTheDocument();
    expect(
      within(changed).getByRole("rowheader", { name: "Total change" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "Cash: base and scenario" }),
    ).toBeInTheDocument();
    // KPIs only once shared; export carries the granularity and language.
    expect(
      screen.getByText("Share the scenario to see its KPIs next to the base."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Export to Excel" }),
    ).toHaveAttribute(
      "href",
      `${API}/scenarios/sc1/comparison/export?granularity=YEAR&lang=en`,
    );
    fireEvent.click(screen.getByRole("button", { name: "Save this run" }));
    await waitFor(() => expect(sent[1]?.url).toBe(`${API}/scenarios/sc1/runs`));
    expect(await screen.findByText(/Saved: VALID/)).toBeInTheDocument();
    await accessible(container);
  });
});

describe("Sensitivity (M7-7)", () => {
  it("runs a tornado from a shared scenario and shows the table with the chart", async () => {
    const analysis = {
      kind: "TORNADO",
      output: "MIN_CASH",
      year: null,
      base_label: "Price rise",
      base: { value: "1000.00", month: "2027-03-01" },
      points: [],
      bars: [
        {
          driver: "revenue",
          label: "Revenue",
          low: { value: "400.00", month: null },
          high: { value: "1600.00", month: null },
          swing: "1200.00",
        },
        {
          driver: "opex",
          label: "Operating costs",
          low: { value: "1300.00", month: null },
          high: { value: "700.00", month: null },
          swing: "600.00",
        },
      ],
      input_hash: "x",
      watermark: 7,
      cached: true,
      nature: "HYPOTHETICAL",
      engine_status: "PENDING_PROFESSIONAL_REVIEW",
    };
    const sent = stub(
      (url) => (url.includes("/scenarios") ? [scenario, shared] : [set]),
      () => analysis,
    );
    const { container } = mount(
      "/w/ws/e/e1/sensitivity",
      "/w/:slug/e/:entityId/sensitivity",
      <SensitivityPage />,
    );
    const picker = screen.getByLabelText("Start from");
    // Only shared scenarios and approved sets can be analysed.
    await screen.findByRole("option", { name: "Price rise" });
    expect(
      within(picker).queryByRole("option", { name: "Slow second half" }),
    ).toBeNull();
    fireEvent.change(picker, { target: { value: "scenario:sc2" } });
    fireEvent.click(screen.getByRole("button", { name: "Analyse" }));
    await waitFor(() =>
      expect(sent[0]).toEqual({
        url: `${API}/sensitivity/tornado`,
        method: "POST",
        body: {
          scenario_id: "sc2",
          output: "MIN_CASH",
          year: null,
          drivers: [],
          percent: "10",
        },
      }),
    );
    const ranked = await screen.findByRole("table", {
      name: "Ranked by how much the result moves",
    });
    const rows = within(ranked).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("Revenue");
    expect(rows[1]).toHaveTextContent("1,200.00");
    expect(
      screen.getByRole("img", {
        name: "Tornado: the result at each assumption moved down and up",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/from the cache/)).toBeInTheDocument();
    expect(screen.getByText(/Hypothetical/)).toBeInTheDocument();
    await accessible(container);
  });
});

describe("Working capital (M7-7)", () => {
  it("shows the days by month and works out what N days are worth", async () => {
    const view = {
      base_label: "Plan 2027 v2",
      nature: "FORECAST",
      watermark: 7,
      cutover: "2026-12-31",
      observed: { dso: "31", dio: "0", dpo: "28" },
      observed_ccc: "3",
      months: [
        {
          month: "2027-01-01",
          receivables: "1000.00",
          inventory: "0.00",
          payables: "500.00",
          net: "500.00",
          change: "500.00",
          cash_effect: "-500.00",
          dso: "30",
          dio: "0",
          dpo: "30",
          ccc: "0",
        },
      ],
      engine_status: "PENDING_PROFESSIONAL_REVIEW",
    };
    const worth = {
      driver: "dso",
      days: -10,
      closing_cash_change: "330.00",
      lowest_cash_change: "120.00",
      net_working_capital_change: "-330.00",
      by_month: [],
      nature: "HYPOTHETICAL",
    };
    const sent = stub(
      (url) =>
        url.includes("/working-capital")
          ? view
          : url.includes("/scenarios")
            ? []
            : [set],
      () => worth,
    );
    const { container } = mount(
      "/w/ws/e/e1/working-capital",
      "/w/:slug/e/:entityId/working-capital",
      <WorkingCapitalPage />,
    );
    await screen.findByRole("option", { name: "Plan 2027 v2" });
    fireEvent.change(screen.getByLabelText("Start from"), {
      target: { value: "set:s1" },
    });
    const table = await screen.findByRole("table", {
      name: "Working capital by month",
    });
    expect(within(table).getByText("2027-01")).toBeInTheDocument();
    expect(within(table).getByText("-500.00")).toBeInTheDocument();
    expect(screen.getByText(/Seen over the last 12 months/)).toHaveTextContent(
      "DSO 31",
    );
    fireEvent.click(screen.getByRole("button", { name: "Work it out" }));
    await waitFor(() =>
      expect(sent[0]).toEqual({
        url: `${API}/working-capital/days-worth`,
        method: "POST",
        body: { base_set_id: "s1", driver: "dso", days: -10 },
      }),
    );
    expect(await screen.findByText(/330\.00/)).toHaveTextContent(
      "Hypothetical",
    );
    await accessible(container);
  });
});

describe("Goals against scenarios (M7-7)", () => {
  it("compares the goal under its base and chosen shared scenarios", async () => {
    const outlooks = [
      {
        label: "Base",
        applicable: true,
        reason: "",
        status: "ON_TRACK",
        method: "SCENARIO",
        note: "From the approved plan",
        nature: "FORECAST",
        projected: "5000.00",
        gap: "0.00",
      },
      {
        label: "Price rise",
        applicable: true,
        reason: "",
        status: "AT_RISK",
        method: "SCENARIO",
        note: "From the scenario",
        nature: "HYPOTHETICAL",
        projected: "4000.00",
        gap: "-1000.00",
      },
    ];
    let asked = "";
    stub(
      (url) => {
        if (url.includes("/scenario-outlooks")) {
          asked = url;
          return outlooks;
        }
        return [scenario, shared];
      },
      () => null,
    );
    const { container } = mount(
      "/w/ws/e/e1/goals",
      "/w/:slug/e/:entityId/goals",
      <GoalScenarios goalId="g1" format={(v) => (v ? `€${v}` : "")} />,
    );
    // Drafts are private: only shared scenarios are offered.
    const box = await screen.findByRole("checkbox", { name: "Price rise" });
    expect(
      screen.queryByRole("checkbox", { name: "Slow second half" }),
    ).toBeNull();
    fireEvent.click(box);
    const table = await screen.findByRole("table", {
      name: "The goal under its base and each scenario",
    });
    expect(asked).toContain("scenario_ids=sc2");
    expect(
      within(table).getByRole("rowheader", { name: "Base (forecast)" }),
    ).toBeInTheDocument();
    const row = within(table).getByRole("row", { name: /Price rise/ });
    expect(row).toHaveTextContent("Hypothetical");
    expect(row).toHaveTextContent("€-1000.00"); // in the goal's own format
    await accessible(container);
  });
});
