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
import { AlertsPage } from "./pages/Alerts";
import { DashboardPage } from "./pages/Dashboard";
import { ReportPacksPage } from "./pages/ReportPacks";

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const API = "/api/w/ws/entities/e1";
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

async function accessible(container: HTMLElement) {
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);
}

const pack = {
  id: "p1",
  family_id: "f1",
  version: 1,
  supersedes_id: null,
  title: "Management pack, March 2026",
  period_kind: "MONTH",
  period_start: "2026-03-01",
  period_end: "2026-03-31",
  status: "DRAFT",
  sections: ["budget", "risks", "commentary"],
  columns: ["actual", "budget", "variance"],
  snapshot_hash: "h",
  watermark: 13,
  generated_at: "2026-11-17T08:00:00Z",
  created_by_id: "u1",
  created_at: "2026-11-17T08:00:00Z",
  submitted_at: null,
  reviewed_by_id: null,
  review_note: "",
  finalised_at: null,
  superseded_at: null,
  blocks: { statements: "ok", budget: "ok" },
  blockers: [],
};
const sections = [
  {
    key: "budget",
    title: "Budget performance",
    title_el: "Απόδοση προϋπολογισμού",
    status: "ok",
    reason: "",
    notice: "",
    notice_el: "",
    tables: [
      {
        caption: "Month",
        caption_el: "Μήνας",
        columns: [
          { key: "line", label: "Line", label_el: "Γραμμή" },
          { key: "actual", label: "Actual", label_el: "Πραγματικό" },
          { key: "budget", label: "Budget", label_el: "Προϋπολογισμός" },
          { key: "variance", label: "Variance", label_el: "Απόκλιση" },
        ],
        rows: [
          {
            key: "REV.SALES",
            label: "Sales of goods",
            label_el: "Πωλήσεις αγαθών",
            kind: "line",
            cells: [
              { value: "0.00", nature: "ACTUAL" },
              { value: "1000.00", nature: "BUDGET" },
              { value: "-1000.00", nature: "ACTUAL" },
            ],
          },
        ],
      },
    ],
    comment: "Orders moved to April",
    risks: [],
  },
  {
    key: "risks",
    title: "Risks",
    title_el: "Κίνδυνοι",
    status: "ok",
    reason: "",
    notice: "",
    notice_el: "",
    tables: [],
    comment: null,
    risks: [
      {
        ref: 1,
        title: "Customer C1 pays late",
        owner: "CFO",
        status: "OPEN",
        mitigation: "",
      },
    ],
  },
  {
    key: "commentary",
    title: "Commentary",
    title_el: "Σχόλια",
    status: "ok",
    reason: "",
    notice: "",
    notice_el: "",
    tables: [],
    comment: null,
    risks: [],
  },
];

describe("Report packs (M8-6)", () => {
  it("generates a pack, shows natures, edits commentary and risks, and sends it for review", async () => {
    let current = { ...pack };
    const sent = stub(
      (url) => {
        if (url.includes("/sections")) return { pack: current, sections };
        if (url.includes("/report-packs/p1")) return current;
        return [current];
      },
      (url) => {
        if (url.endsWith("/submit"))
          current = { ...current, status: "IN_REVIEW" };
        if (url.includes("/risks")) return sections[1]?.risks;
        if (url.includes("/comments")) return { budget: "Orders moved to May" };
        return current;
      },
    );
    const { container } = mount(
      "/w/ws/e/e1/report-packs",
      "/w/:slug/e/:entityId/report-packs",
      <ReportPacksPage />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Generate" }));
    await waitFor(() =>
      expect(sent[0]).toMatchObject({
        url: `${API}/report-packs`,
        method: "POST",
        body: { period_kind: "MONTH", title: "" },
      }),
    );
    const view = await screen.findByRole("region", {
      name: /Management pack, March 2026/,
    });
    expect(within(view).getByRole("note")).toHaveTextContent(/DRAFT/);
    const table = await within(view).findByRole("table", { name: "Month" });
    const natures = within(table).getByRole("row", { name: /Nature/ });
    expect(natures).toHaveTextContent("Actual");
    expect(natures).toHaveTextContent("Budget");
    expect(
      within(table).getByRole("row", { name: /Sales of goods/ }),
    ).toHaveTextContent("-1,000.00");
    // Commentary: edited in the draft and saved.
    const box = within(view).getByLabelText<HTMLTextAreaElement>(
      "Commentary: Budget performance",
    );
    expect(box.value).toBe("Orders moved to April");
    fireEvent.change(box, { target: { value: "Orders moved to May" } });
    fireEvent.click(
      within(view).getAllByRole("button", {
        name: "Save commentary",
      })[0] as HTMLElement,
    );
    await waitFor(() =>
      expect(sent.at(-1)).toEqual({
        url: `${API}/report-packs/p1/comments`,
        method: "POST",
        body: { section: "budget", text: "Orders moved to May" },
      }),
    );
    // Risks: listed with owner and status; a new one is added.
    expect(within(view).getByText("Customer C1 pays late")).toBeInTheDocument();
    fireEvent.change(within(view).getByLabelText("Risk"), {
      target: { value: "Rent review in June" },
    });
    fireEvent.click(within(view).getByRole("button", { name: "Add a risk" }));
    await waitFor(() =>
      expect(sent.at(-1)).toMatchObject({
        url: `${API}/report-packs/p1/risks`,
        body: { title: "Rent review in June", status: "OPEN" },
      }),
    );
    // Exports carry the language; then it is sent for review.
    expect(within(view).getByRole("link", { name: "PDF" })).toHaveAttribute(
      "href",
      `${API}/report-packs/p1/export?format=pdf&lang=en`,
    );
    fireEvent.click(
      within(view).getByRole("button", { name: "Send for review" }),
    );
    await waitFor(() =>
      expect(sent.at(-1)?.url).toBe(`${API}/report-packs/p1/submit`),
    );
    await accessible(container);
  });

  it("shows why a pack in review cannot be final, and lets a reviewer return it", async () => {
    const inReview = {
      ...pack,
      status: "IN_REVIEW",
      blockers: [
        "These variances need an explanation before the pack is final: REV.SALES (MONTH).",
      ],
    };
    const sent = stub(
      (url) => {
        if (url.includes("/sections")) return { pack: inReview, sections };
        if (url.includes("/report-packs/p1")) return inReview;
        return [inReview];
      },
      () => ({ ...inReview, status: "DRAFT" }),
    );
    const { container } = mount(
      "/w/ws/e/e1/report-packs",
      "/w/:slug/e/:entityId/report-packs",
      <ReportPacksPage />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: /Management pack/ }),
    );
    const status = await screen.findByText(/It cannot be finalised yet/);
    expect(status.parentElement).toHaveTextContent("REV.SALES (MONTH)");
    expect(
      screen.queryByRole("button", { name: "Save commentary" }),
    ).toBeNull();
    const back = screen.getByRole("button", { name: "Return to the preparer" });
    expect(back).toBeDisabled(); // a note says what to change
    fireEvent.change(screen.getByLabelText("Review note"), {
      target: { value: "Explain the sales" },
    });
    fireEvent.click(back);
    await waitFor(() =>
      expect(sent[0]).toEqual({
        url: `${API}/report-packs/p1/return`,
        method: "POST",
        body: { note: "Explain the sales" },
      }),
    );
    await accessible(container);
  });
});

describe("Dashboard v2 (M8-6)", () => {
  it("shows the waterfall and scenario widgets, half width, LTM and saved views", async () => {
    const board = {
      period: {
        preset: "YTD",
        month: "2026-03-01",
        date_from: "2026-01-01",
        date_to: "2026-03-31",
        fiscal_year_start: "2026-01-01",
        comparison: "BUDGET",
      },
      layout_source: "USER",
      widgets: [
        {
          type: "waterfall",
          status: "ok",
          reason: "",
          options: { width: "half" },
          data: {
            budget_name: "Plan 2026",
            start: "750.00",
            start_nature: "BUDGET",
            end: "250.00",
            end_nature: "ACTUAL",
            steps: [
              { line: "REV.SALES", value: "-2000.00", favourable: false },
            ],
          },
        },
        {
          type: "scenario",
          status: "ok",
          reason: "",
          options: { scenario_id: "s1", width: "half" },
          data: {
            name: "Price rise",
            base_name: "Plan",
            base_version: 1,
            nature: "HYPOTHETICAL",
            changes: { "PL.REVENUE": "6000.00" },
            lowest_cash: { base: "100.00", scenario: "300.00" },
          },
        },
      ],
    };
    const views = [
      { id: "v1", name: "Board", preset: "QTD", comparison: "PRIOR_YEAR" },
    ];
    const sent = stub(
      (url) => {
        if (url.includes("/dashboard-views")) return views;
        if (url.includes("/scenarios")) return [];
        return board;
      },
      () => views[0],
    );
    const { container } = mount(
      "/w/ws/e/e1/dashboard",
      "/w/:slug/e/:entityId/dashboard",
      <DashboardPage />,
    );
    const waterfall = await screen.findByRole("region", {
      name: "Budget to actual (waterfall)",
    });
    expect(waterfall).toHaveClass("dash-half");
    const table = within(waterfall).getByRole("table");
    expect(
      within(table).getByRole("row", { name: /Budgeted result/ }),
    ).toHaveTextContent("750.00");
    expect(
      within(table).getByRole("row", { name: /REV.SALES/ }),
    ).toHaveTextContent("▼ -2,000.00");
    expect(
      within(table).getByRole("row", { name: /Actual result/ }),
    ).toHaveTextContent("Actual");
    const scenario = screen.getByRole("region", {
      name: "Scenario comparison",
    });
    expect(within(scenario).getByText("Hypothetical")).toBeInTheDocument();
    expect(within(scenario).getByRole("note")).toHaveTextContent(
      /Pending professional review/,
    );
    expect(
      within(scenario).getByRole("row", { name: /Revenue/ }),
    ).toHaveTextContent("6,000.00");
    expect(
      screen.getByRole("option", { name: "Last twelve months" }),
    ).toBeInTheDocument();
    // A saved view sets the period and comparison; the current one can be saved by name.
    await screen.findByRole("option", { name: "Board" });
    fireEvent.change(screen.getByLabelText("Saved views"), {
      target: { value: "v1" },
    });
    expect(screen.getByLabelText("Period")).toHaveValue("QTD");
    fireEvent.change(screen.getByLabelText("Save this view as"), {
      target: { value: "Monthly" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save view" }));
    await waitFor(() =>
      expect(sent[0]).toEqual({
        url: `${API}/dashboard-views`,
        method: "PUT",
        body: { name: "Monthly", preset: "QTD", comparison: "PRIOR_YEAR" },
      }),
    );
    await accessible(container);
  });
});

describe("Alert emails (M8-6)", () => {
  it("is off by default and saves the chosen mode and language", async () => {
    const sent = stub(
      (url) =>
        url.includes("alert-email-preference")
          ? { mode: "OFF", language: "en" }
          : [],
      () => ({ mode: "DIGEST", language: "el" }),
    );
    const { container } = mount(
      "/w/ws/e/e1/alerts",
      "/w/:slug/e/:entityId/alerts",
      <AlertsPage />,
    );
    const mode = await screen.findByLabelText("Email me");
    expect(mode).toHaveValue("OFF");
    fireEvent.change(mode, { target: { value: "DIGEST" } });
    fireEvent.change(screen.getAllByLabelText("Language")[0] as HTMLElement, {
      target: { value: "el" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(sent[0]).toEqual({
        url: "/api/w/ws/alert-email-preference",
        method: "PUT",
        body: { mode: "DIGEST", language: "el" },
      }),
    );
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    await accessible(container);
  });
});
