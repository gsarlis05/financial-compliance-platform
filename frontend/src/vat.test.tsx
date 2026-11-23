// VAT screen (V1-2): periods set by the company, a report per period, sign-off and filing.
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
import { VatPage } from "./pages/Vat";

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const report = {
  id: "r1",
  period_start: "2026-01-01",
  period_end: "2026-03-31",
  version: 1,
  supersedes_id: null,
  status: "DRAFT",
  snapshot_hash: "h",
  watermark: 7,
  generated_at: "2026-04-02T10:00:00Z",
  created_by_id: "u1",
  due_date: null,
  signed_off_by_id: null,
  signed_off_at: null,
  self_approved: false,
  filed_on: null,
  filing_reference: "",
  settlement_entry_id: null,
  blockers: [],
  snapshot: {
    codes: [
      {
        code: "S19",
        treatment: "STANDARD",
        rate: "0.1900",
        verified: false,
        sales_base: "900.00",
        sales_vat: "171.00",
        sales_expected_vat: "171.00",
        purchase_base: "400.00",
        purchase_vat: "76.00",
        purchase_expected_vat: "76.00",
      },
    ],
    totals: {
      sales_base: "900.00",
      sales_vat: "171.00",
      purchase_base: "400.00",
      purchase_vat: "76.00",
      net: "95.00",
      direction: "PAYABLE",
    },
    accounts: [
      {
        code: "2120",
        name: "VAT payable",
        role: "OUTPUT",
        vat: "171.00",
        settled: "0.00",
      },
    ],
    settlements: "0.00",
    unverified_codes: ["S19"],
    exceptions: [],
    lines: [
      {
        line_id: "l1",
        entry_id: "e1",
        entry_ref: "GJ-1",
        date: "2026-01-10",
        description: "Sale",
        account: "4000 Sales",
        code: "S19",
        kind: "SALE",
        amount: "900.00",
        counterparty: "",
        reference: "",
      },
    ],
  },
};

const BOXES = [
  ["1", "VAT", "171.00"],
  ["2", "VAT", "0.00"],
  ["3", "VAT", "171.00"],
  ["4", "VAT", "76.00"],
  ["5", "VAT", "95.00"],
  ["6", "VALUE", "900.00"],
  ["7", "VALUE", "1400.00"],
  ["8A", "VALUE", "0.00"],
  ["8B", "VALUE", "0.00"],
  ["9", "VALUE", "0.00"],
  ["10", "VALUE", "0.00"],
  ["11A", "VALUE", "1000.00"],
  ["11B", "VALUE", "0.00"],
] as const;
const withReturn = {
  ...report,
  snapshot: {
    ...report.snapshot,
    return: {
      rules: "CY-VAT-BOXES@1",
      status: "PENDING_PROFESSIONAL_VERIFICATION",
      sources: [{ key: "spec", title: "Owner's specification" }],
      boxes: BOXES.map(([box, kind, amount]) => ({
        box,
        label: `Item ${box}`,
        kind,
        amount,
        exact: box === "7" ? "1399.60" : amount,
        rounding: box === "7" ? "0.40" : "0.00",
      })),
      checks: [],
      direction: "PAYABLE",
    },
    lines: [
      {
        ...report.snapshot.lines[0],
        boxes: { "6": "900.00" },
        mapping: "MAPPED",
        rule: "spec §2: domestic taxable sale",
        country: "",
      },
      {
        ...report.snapshot.lines[0],
        line_id: "l2",
        entry_ref: "GJ-2",
        account: "5000 Purchases",
        code: "EUGA19",
        kind: "PURCHASE",
        amount: "1000.00",
        boxes: { "7": "1000.00", "11A": "1000.00" },
        mapping: "MAPPED",
        rule: "spec §2: EU goods acquisition",
        country: "DE",
      },
      {
        ...report.snapshot.lines[0],
        line_id: "l3",
        entry_ref: "GJ-3",
        account: "6100 Insurance",
        code: "EX",
        kind: "PURCHASE",
        amount: "400.00",
        boxes: {},
        mapping: "UNSUPPORTED",
        rule: "Exempt supplies and purchases are not mapped.",
        country: "",
      },
    ],
  },
};

type Sent = { url: string; method: string; body?: unknown };

function stub(shown: unknown = report) {
  const sent: Sent[] = [];
  document.cookie = "__Host-fcp_csrftoken=test";
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init: RequestInit) => {
      const method = init.method ?? "GET";
      if (method !== "GET") {
        sent.push({ url, method, body: JSON.parse(init.body as string) });
        if (url.endsWith("/sign-off"))
          return Promise.resolve(
            respond({ ...report, status: "SIGNED_OFF", self_approved: true }),
          );
        return Promise.resolve(respond({}, 201));
      }
      if (url.endsWith("/vat-period-schemes"))
        return Promise.resolve(
          respond([
            {
              id: "s1",
              months: 3,
              effective_from: "2026-01-01",
              note: "",
              created_at: "2026-01-01T00:00:00Z",
            },
          ]),
        );
      if (url.endsWith("/vat-periods"))
        return Promise.resolve(
          respond([
            {
              start: "2026-04-01",
              end: "2026-06-30",
              months: 3,
              ended: true,
              report: null,
            },
            {
              start: "2026-01-01",
              end: "2026-03-31",
              months: 3,
              ended: true,
              report,
            },
          ]),
        );
      return Promise.resolve(respond(shown));
    }),
  );
  return sent;
}

function mount() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <I18nProvider locale="en">
        <MemoryRouter initialEntries={["/w/ws/e/e1/vat"]}>
          <Routes>
            <Route path="/w/:slug/e/:entityId/vat" element={<VatPage />} />
          </Routes>
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("VAT (V1-2)", () => {
  it("lists the periods, prepares a report and shows it", async () => {
    const sent = stub();
    const { container } = mount();
    expect(await screen.findByText(/every 3/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Prepare report" }));
    await waitFor(() =>
      expect(sent[0]).toEqual({
        url: "/api/w/ws/entities/e1/vat-reports",
        method: "POST",
        body: { period_start: "2026-04-01" },
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(await screen.findByText("Net VAT (payable)")).toBeInTheDocument();
    expect(screen.getByText("95.00")).toBeInTheDocument();
    // A report prepared before the boxes were added says so.
    expect(
      screen.getByText(/prepared before the return's boxes were added/),
    ).toBeInTheDocument();
    expect(screen.getByText("19.00%")).toBeInTheDocument();
    expect(
      screen.getByText(/VAT codes not yet verified by a tax professional/),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download PDF" })).toHaveAttribute(
      "href",
      "/api/w/ws/entities/e1/vat-reports/r1/export?format=pdf&lang=en",
    );
    fireEvent.click(screen.getByRole("button", { name: "Sign off" }));
    await waitFor(() =>
      expect(sent.at(-1)?.url).toBe(
        "/api/w/ws/entities/e1/vat-reports/r1/sign-off",
      ),
    );
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations).toEqual([]);
  });

  it("sets the company's VAT periods", async () => {
    const sent = stub();
    mount();
    await screen.findByText(/every 3/);
    fireEvent.change(screen.getByLabelText("Length"), {
      target: { value: "1" },
    });
    fireEvent.change(screen.getByLabelText("First day of a period"), {
      target: { value: "2026-07-01" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Change from this date" }),
    );
    await waitFor(() =>
      expect(sent[0]?.body).toEqual({
        months: 1,
        effective_from: "2026-07-01",
        note: "",
      }),
    );
  });

  it("shows the return's boxes and the lines behind each box (V1-2c)", async () => {
    stub(withReturn);
    const { container } = mount();
    await screen.findByText(/every 3/);
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    const table = await screen.findByRole("region", { name: "VAT return" });
    const row = (box: string) =>
      within(table).getByRole("row", {
        name: new RegExp(`^${box} Item ${box}`),
      });
    expect(row("5")).toHaveTextContent("Item 5 (payable)95.00");
    // Boxes 6-11B in whole euros, with the rounding shown.
    expect(row("7")).toHaveTextContent("1,400");
    expect(row("7")).toHaveTextContent("0.40");
    expect(row("11A")).toHaveTextContent("1,000");
    expect(
      within(table).getByText(
        /CY-VAT-BOXES@1 are taken from your specification/,
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Lines Box 11A" }));
    expect(
      await screen.findByText(/Lines feeding box 11A: 1 · 1,000.00/),
    ).toBeInTheDocument();
    expect(screen.getByText("GJ-2")).toBeInTheDocument();
    expect(screen.queryByText("GJ-1")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show all lines" }));
    expect(await screen.findByText("not in any box")).toBeInTheDocument();
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations).toEqual([]);
  });
});
