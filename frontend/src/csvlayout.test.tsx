// A bank's CSV export recognised from the file (R-1, #244): the columns found, a question the file
// leaves open, a preview, then the layout saved (with the answer) and the import started.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import axe from "axe-core";
import { MemoryRouter, Route, Routes } from "react-router";
import { CsvLayout } from "./components/CsvLayout";
import { I18nProvider } from "./i18n/I18n";

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const detection = {
  mapping: {
    date: "Ημερομηνία",
    amount: "",
    debit: "Χρέωση",
    credit: "Πίστωση",
    description: "Περιγραφή",
    reference: "",
    counterparty: "",
    balance: "Υπόλοιπο",
    date_format: "%d/%m/%Y",
    delimiter: ";",
    decimal_comma: true,
    has_header: true,
    encoding: "cp1253",
    skip_rows: 2,
  },
  columns: {
    date: "Ημερομηνία",
    debit: "Χρέωση",
    credit: "Πίστωση",
    description: "Περιγραφή",
    balance: "Υπόλοιπο",
  },
  questions: [
    {
      field: "date_format",
      message: "Every date fits both orders.",
      options: ["%d/%m/%Y", "%m/%d/%Y"],
      chosen: "%d/%m/%Y",
    },
  ],
  preview: [
    {
      booking_date: "2026-03-04",
      amount: "-1250.00",
      description: "Rent (Demo)",
      reference: "",
      counterparty_name: "",
    },
  ],
  preset: {
    key: "BANK_OF_CYPRUS",
    name: "Bank of Cyprus",
    status: "TO_BE_CONFIRMED",
    note: "",
  },
  error: "",
};

describe("CSV layout", () => {
  it("shows what was recognised, asks the open question and saves the answer", async () => {
    const sent: { url: string; method: string; body: unknown }[] = [];
    document.cookie = "__Host-fcp_csrftoken=test";
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init: RequestInit) => {
        const method = init.method ?? "GET";
        if (url.endsWith("/bank-presets"))
          return Promise.resolve(respond([detection.preset]));
        if (url.endsWith("/csv-detect"))
          return Promise.resolve(respond(detection));
        sent.push({ url, method, body: JSON.parse(init.body as string) });
        return Promise.resolve(respond({}));
      }),
    );
    const onImport = vi.fn();
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider locale="en">
          <MemoryRouter initialEntries={["/w/ws/e/e1/bank"]}>
            <Routes>
              <Route
                path="/w/:slug/e/:entityId/bank"
                element={
                  <CsvLayout
                    accountId="b1"
                    file={new File(["x"], "s.csv")}
                    importing={false}
                    onImport={onImport}
                  />
                }
              />
            </Routes>
          </MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByText(/Columns found:/)).toHaveTextContent(
      "Debit: “Χρέωση”",
    );
    expect(screen.getByText(/still to be confirmed/)).toBeInTheDocument();
    expect(
      screen.getByRole("table", {
        name: "The first lines as they will be imported",
      }),
    ).toHaveTextContent("-1,250.00");
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);

    fireEvent.change(screen.getByLabelText("Dates are written as"), {
      target: { value: "%m/%d/%Y" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save this layout and import" }),
    );
    await waitFor(() => expect(onImport).toHaveBeenCalledTimes(1));
    expect(sent).toEqual([
      {
        url: "/api/w/ws/entities/e1/bank-accounts/b1/csv-mapping",
        method: "PUT",
        body: { ...detection.mapping, date_format: "%m/%d/%Y" },
      },
    ]);
  });
});
