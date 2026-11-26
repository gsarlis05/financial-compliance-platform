// Bring your books in (R-2, #245): a file is checked (problems by row, nothing kept), an account
// the chart lacks is mapped, and only a clean check can be imported.
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
import type { ImportOutcome } from "./api/imports";
import { I18nProvider } from "./i18n/I18n";
import { ImportPage } from "./pages/Import";

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const empty: ImportOutcome = {
  kind: "opening-balances",
  committed: false,
  rows: 3,
  problems: [],
  warnings: [],
  unknown_accounts: [],
  accounts: [],
  counterparties: [],
  skipped: [],
  lines: [],
  total_debit: "0.00",
  total_credit: "0.00",
  entry_id: null,
  files: {},
};

const unmapped: ImportOutcome = {
  ...empty,
  problems: [
    {
      file: "tb.csv",
      row: 4,
      column: "Account code",
      message:
        "OLD-30 is not in the chart: map it to an account, or import the chart first.",
    },
  ],
  unknown_accounts: [
    { code: "OLD-30", name: "Capital (old chart)", rows: [4] },
  ],
};

const clean: ImportOutcome = {
  ...empty,
  lines: [
    {
      account_code: "1300",
      account_name: "Bank",
      debit: "1250.00",
      credit: "0.00",
      counterparty_code: "",
      reference: "",
      due_date: null,
    },
    {
      account_code: "3000",
      account_name: "Share capital",
      debit: "0.00",
      credit: "1250.00",
      counterparty_code: "",
      reference: "",
      due_date: null,
    },
  ],
  total_debit: "1250.00",
  total_credit: "1250.00",
};

const checkOpening = () =>
  within(
    screen.getByRole("region", {
      name: "3. Opening balances and open invoices",
    }),
  ).getByRole("button", { name: "Check the file" });

describe("Bring your books in", () => {
  it("lists problems, maps an unknown account and creates the draft after a clean check", async () => {
    const sent: Record<string, FormDataEntryValue>[] = [];
    document.cookie = "__Host-fcp_csrftoken=test";
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init: RequestInit) => {
        if (url.endsWith("/accounts"))
          return Promise.resolve(
            respond([
              {
                id: "a3000",
                code: "3000",
                name: "Share capital",
                is_postable: true,
                status: "ACTIVE",
              },
            ]),
          );
        const form = Object.fromEntries((init.body as FormData).entries());
        sent.push(form);
        if (form.commit === "true")
          return Promise.resolve(
            respond({ ...clean, committed: true, entry_id: "e9" }),
          );
        return Promise.resolve(
          respond(form.account_map === "{}" ? unmapped : clean),
        );
      }),
    );
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider locale="en">
          <MemoryRouter initialEntries={["/w/ws/e/e1/import"]}>
            <Routes>
              <Route
                path="/w/:slug/e/:entityId/import"
                element={<ImportPage />}
              />
            </Routes>
          </MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    );
    expect(screen.getAllByRole("link", { name: "Excel" })[0]).toHaveAttribute(
      "href",
      "/api/w/ws/entities/e1/imports/templates/chart?format=xlsx",
    );
    fireEvent.change(screen.getByLabelText("Trial balance file"), {
      target: { files: [new File(["x"], "tb.csv")] },
    });
    const create = screen.getByRole("button", {
      name: "Create the draft entry",
    });
    expect(create).toBeDisabled();
    fireEvent.click(checkOpening());
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "1 problems found",
    );
    expect(
      screen.getByRole("table", { name: "Problems found" }),
    ).toHaveTextContent("OLD-30 is not in the chart");
    expect(create).toBeDisabled();
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);

    fireEvent.change(screen.getByLabelText(/OLD-30 Capital/), {
      target: { value: "3000" },
    });
    fireEvent.click(checkOpening());
    expect(
      await screen.findByRole("table", { name: "Lines of the opening entry" }),
    ).toHaveTextContent("1,250.00");
    await waitFor(() => expect(create).toBeEnabled());
    fireEvent.click(create);
    expect(
      await screen.findByRole("link", { name: /Open the draft entry/ }),
    ).toHaveAttribute("href", "/w/ws/e/e1/entries/e9");
    expect(sent.map((f) => [f.commit, f.account_map])).toEqual([
      ["false", "{}"],
      ["false", '{"OLD-30":"3000"}'],
      ["true", '{"OLD-30":"3000"}'],
    ]);
  });
});
