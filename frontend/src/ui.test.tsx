import { fireEvent, render, screen } from "@testing-library/react";
import axe from "axe-core";
import type { ReactNode } from "react";
import { ApiError } from "./api/client";
import type { Account, Counterparty, Dimension, FiscalYear, JournalEntry } from "./api/types";
import { I18nProvider } from "./i18n/I18n";
import { el, en } from "./i18n/messages";
import { formatAmount, isAmount, sum } from "./money";
import { EntryActions } from "./pages/Entries";
import { EntryForm, periodFor } from "./pages/EntryForm";

const accounts: Account[] = [
  { id: "a1", code: "1300", name: "Bank", name_el: "Τράπεζα", type: "ASSET", normal_side: "DEBIT",
    parent_id: null, is_postable: true, status: "ACTIVE", currency: "", control_type: "", vat_role: "" },
  { id: "a2", code: "4000", name: "Sales revenue", name_el: "Πωλήσεις", type: "INCOME",
    normal_side: "CREDIT", parent_id: null, is_postable: true, status: "ACTIVE", currency: "", control_type: "", vat_role: "" },
  { id: "h1", code: "4", name: "Income", name_el: "Έσοδα", type: "INCOME", normal_side: "CREDIT",
    parent_id: null, is_postable: false, status: "ACTIVE", currency: "", control_type: "", vat_role: "" },
];

const years: FiscalYear[] = [
  {
    id: "fy", name: "2026", start_date: "2026-01-01", end_date: "2026-12-31", status: "OPEN",
    periods: [
      { id: "p1", number: 1, start_date: "2026-01-01", end_date: "2026-01-31", is_adjustment: false, status: "LOCKED" },
      { id: "p2", number: 2, start_date: "2026-02-01", end_date: "2026-02-28", is_adjustment: false, status: "SOFT_CLOSED" },
      { id: "p3", number: 3, start_date: "2026-03-01", end_date: "2026-03-31", is_adjustment: false, status: "OPEN" },
    ],
  },
];

function wrap(children: ReactNode, locale: "en" | "el" = "en") {
  return <I18nProvider locale={locale}>{children}</I18nProvider>;
}

async function noAxeViolations(container: HTMLElement) {
  // jsdom cannot compute colours, so contrast is checked in the browser, not here.
  const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

function renderForm(props: Partial<Parameters<typeof EntryForm>[0]> = {}) {
  const onSave = vi.fn();
  const utils = render(
    wrap(
      <EntryForm accounts={accounts} fiscalYears={years} saving={false} error={null} onSave={onSave} {...props} />,
    ),
  );
  return { onSave, ...utils };
}

function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

describe("i18n", () => {
  it("defines the same keys in English and Greek, none empty", () => {
    expect(Object.keys(el).sort()).toEqual(Object.keys(en).sort());
    for (const value of Object.values(el)) {
      expect(value.trim()).not.toBe("");
    }
  });
});

describe("money helpers", () => {
  it("adds decimal strings exactly and never uses binary floats", () => {
    expect(sum(["0.1", "0.2"]).toFixed(2)).toBe("0.30");
    expect(sum(["1190.00", "", "abc"]).toFixed(2)).toBe("1190.00");
    expect(formatAmount("1234567.5")).toBe("1,234,567.50");
    expect(formatAmount("1234567.5", "el")).toBe("1.234.567,50");
    expect(isAmount("10.005")).toBe(true);
    expect(isAmount("-1")).toBe(false);
    expect(isAmount("1e3")).toBe(false);
  });
});

describe("EntryForm (AC-F1)", () => {
  it("shows live totals and blocks submission until debits equal credits", () => {
    const { onSave } = renderForm();
    fill("Description", "Invoice 17");
    fill("Account 1", "a1");
    fill("Debit 1", "100.00");
    fill("Account 2", "a2");
    fill("Credit 2", "99.99");
    expect(screen.getByTestId("total-debit")).toHaveTextContent("100.00");
    expect(screen.getByTestId("total-credit")).toHaveTextContent("99.99");
    expect(screen.getByText("Difference: 0.01")).toBeInTheDocument();
    const submit = screen.getByRole("button", { name: "Save and submit" });
    expect(submit).toBeDisabled();

    fill("Credit 2", "100.00");
    expect(screen.getByText("Balanced")).toBeInTheDocument();
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    expect(onSave).toHaveBeenCalledTimes(1);
    const [body, submitFlag] = onSave.mock.calls[0] as [{ lines: { debit: string; credit: string }[] }, boolean];
    expect(submitFlag).toBe(true);
    expect(body.lines[0]).toMatchObject({ debit: "100.00", credit: "0" });
    expect(typeof body.lines[1]?.credit).toBe("string");
  });

  it("offers only postable accounts", () => {
    renderForm();
    const select = screen.getByLabelText<HTMLSelectElement>("Account 1");
    const options = Array.from(select.options).map((o) => o.text);
    expect(options.some((o) => o.startsWith("4 ·"))).toBe(false);
    expect(options.some((o) => o.startsWith("1300"))).toBe(true);
  });

  it("marks invalid amounts and disables saving", () => {
    renderForm();
    fill("Debit 1", "12,50");
    expect(screen.getByLabelText("Debit 1")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("button", { name: "Save draft" })).toBeDisabled();
  });

  it("shows server field errors next to the field", () => {
    const error = new ApiError({
      type: "urn:fcp:problem:ledger.account.not_postable", title: "Account cannot be posted to",
      status: 422, detail: "Account 4 is a heading.", code: "ledger.account.not_postable",
      correlation_id: "abc12345", errors: { "lines.0.account_id": ["not postable"] },
    });
    renderForm({ error });
    expect(screen.getByText("not postable")).toBeInTheDocument();
    expect(screen.getByText("Account 4 is a heading.")).toBeInTheDocument();
    expect(screen.getByText("abc12345")).toBeInTheDocument();
  });

  it("explains locked and soft-closed periods (AC-F3)", () => {
    renderForm();
    fill("Accounting date", "2026-01-15");
    expect(screen.getByText(/This period is locked/)).toBeInTheDocument();
    fill("Accounting date", "2026-02-15");
    expect(screen.getByText(/This period is soft-closed/)).toBeInTheDocument();
    fill("Accounting date", "2026-03-15");
    expect(screen.queryByText(/This period is/)).not.toBeInTheDocument();
    expect(periodFor(years, "2030-01-01", false)).toBeUndefined();
  });

  it("renders in Greek", () => {
    render(wrap(<EntryForm accounts={accounts} fiscalYears={years} saving={false} error={null} onSave={vi.fn()} />, "el"));
    expect(screen.getByText("Λογιστική ημερομηνία")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Αποθήκευση και υποβολή" })).toBeDisabled();
  });

  it("has no detectable accessibility violations (AC-F4)", async () => {
    const { container } = renderForm();
    await noAxeViolations(container);
  });
});

const posted: JournalEntry = {
  id: "e1", status: "POSTED", entry_type: "STANDARD", journal: "GJ", entry_no: 7, posting_seq: 9,
  accounting_date: "2026-03-15", document_date: null, use_adjustment_period: false,
  description: "Invoice 17", currency: "EUR", period_id: "p3", reverses_entry_id: null,
  reversed_by_entry_id: null, related_entry_id: null, correction_reason: "", prepared_by_id: "u1",
  approved_by_id: "u2", posted_by_id: "u2", rejection_reason: "", unlock_request_id: null,
  content_hash: "x", total_debit: "100.00", total_credit: "100.00", lines: [],
};

const dims: Dimension[] = [
  {
    id: "d1", code: "DEPT", name: "Departments", kind: "DEPARTMENT", status: "ACTIVE",
    values: [
      { id: "v1", code: "SALES", name: "Sales", parent_id: null, status: "ACTIVE" },
      { id: "v2", code: "OLD", name: "Old", parent_id: null, status: "INACTIVE" },
    ],
  },
  { id: "d2", code: "GONE", name: "Retired", kind: "CUSTOM", status: "INACTIVE", values: [] },
];

describe("EntryForm dimensions (M2-1)", () => {
  it("offers active values per line and sends the chosen value ids", () => {
    const { onSave } = renderForm({ dimensions: dims });
    expect(screen.queryByLabelText("GONE 1")).not.toBeInTheDocument(); // inactive dimension hidden
    const picker = screen.getByLabelText<HTMLSelectElement>("DEPT 1");
    expect(Array.from(picker.options).map((o) => o.text)).toEqual(["—", "SALES · Sales"]);
    fill("Description", "Rent");
    fill("Account 1", "a1");
    fill("Debit 1", "10.00");
    fill("DEPT 1", "v1");
    fill("Account 2", "a2");
    fill("Credit 2", "10.00");
    fireEvent.click(screen.getByRole("button", { name: "Save and submit" }));
    const [body] = onSave.mock.calls[0] as [{ lines: { dimension_value_ids: string[] }[] }];
    expect(body.lines.map((l) => l.dimension_value_ids)).toEqual([["v1"], []]);
  });

  it("keeps an inactive value already used on the entry visible", async () => {
    const initial: JournalEntry = {
      ...posted, status: "DRAFT",
      lines: [{
        line_no: 1, account_id: "a1", account_code: "1300", debit: "5.00", credit: "0.00", memo: "",
        dimensions: [{ dimension_id: "d1", dimension_code: "DEPT", value_id: "v2", value_code: "OLD", value_name: "Old" }],
        counterparty_id: null, counterparty_code: null, reference: "", due_date: null,
        vat_code_id: null, vat_code: null,
      }],
    };
    const { container } = renderForm({ dimensions: dims, initial });
    expect(screen.getByLabelText<HTMLSelectElement>("DEPT 1").value).toBe("v2");
    await noAxeViolations(container);
  });
});

const arAccount: Account = {
  id: "ar", code: "1200", name: "Trade receivables", name_el: "", type: "ASSET", normal_side: "DEBIT",
  parent_id: null, is_postable: true, status: "ACTIVE", currency: "", control_type: "RECEIVABLE", vat_role: "",
};
const parties: Counterparty[] = [
  { id: "c1", code: "C1", name: "Alpha (Demo)", kind: "CUSTOMER", vat_no: "", email: "", payment_terms_days: 30, status: "ACTIVE" },
  { id: "s1", code: "S1", name: "Beta (Demo)", kind: "SUPPLIER", vat_no: "", email: "", payment_terms_days: 45, status: "ACTIVE" },
];

describe("EntryForm customers and suppliers (M2-2)", () => {
  it("asks for a customer on receivables lines only and sends it with the invoice number", async () => {
    const { onSave, container } = renderForm({ accounts: [...accounts, arAccount], counterparties: parties });
    fill("Description", "Invoice 17");
    fill("Account 1", "ar");
    fill("Debit 1", "119.00");
    fill("Account 2", "a2");
    fill("Credit 2", "119.00");
    expect(screen.queryByLabelText("Customer / supplier 2")).not.toBeInTheDocument();
    const picker = screen.getByLabelText<HTMLSelectElement>("Customer / supplier 1");
    expect(Array.from(picker.options).map((o) => o.text)).toEqual(["—", "C1 · Alpha (Demo)"]);
    fill("Customer / supplier 1", "c1");
    fill("Invoice no. 1", "INV-17");
    await noAxeViolations(container);
    fireEvent.click(screen.getByRole("button", { name: "Save and submit" }));
    const [body] = onSave.mock.calls[0] as [{ lines: { counterparty_id: string | null; reference: string }[] }];
    expect(body.lines[0]).toMatchObject({ counterparty_id: "c1", reference: "INV-17" });
    expect(body.lines[1]?.counterparty_id).toBeNull();
  });
});

describe("EntryForm VAT codes (M2-3)", () => {
  const vatAccount: Account = {
    id: "vat", code: "2120", name: "VAT payable", name_el: "", type: "LIABILITY", normal_side: "CREDIT",
    parent_id: null, is_postable: true, status: "ACTIVE", currency: "", control_type: "", vat_role: "OUTPUT",
  };
  const codes = [
    { id: "CY:S19:open", code: "S19", name: "Standard rate 19%", name_el: "", treatment: "STANDARD", rate: "0.1900",
      valid_from: null, valid_to: null, verified: false, verification_note: "" },
  ];
  it("marks unverified rates, requires a code on VAT accounts and sends it", async () => {
    const { onSave, container } = renderForm({ accounts: [...accounts, vatAccount], vatCodes: codes });
    fill("Description", "Cash sale");
    fill("Account 1", "a1");
    fill("Debit 1", "19.00");
    fill("Account 2", "vat");
    fill("Credit 2", "19.00");
    const picker = screen.getByLabelText<HTMLSelectElement>("VAT 2");
    expect(picker.required).toBe(true);
    expect(screen.getByLabelText<HTMLSelectElement>("VAT 1").required).toBe(false);
    expect(Array.from(picker.options).map((o) => o.text)).toContain("S19 · Standard rate 19% (unverified)");
    fill("VAT 2", "CY:S19:open");
    expect(screen.getByText(/not yet verified by a Cyprus tax professional/)).toBeInTheDocument();
    await noAxeViolations(container);
    fireEvent.click(screen.getByRole("button", { name: "Save and submit" }));
    const [body] = onSave.mock.calls[0] as [{ lines: { vat_code_id: string | null }[] }];
    expect(body.lines.map((l) => l.vat_code_id)).toEqual([null, "CY:S19:open"]);
  });
});

describe("EntryActions (AC-F2)", () => {
  it("posted entries are read-only with only a reverse action", async () => {
    const onAct = vi.fn();
    const { container } = render(wrap(<EntryActions entry={posted} myId="u1" onAct={onAct} />));
    expect(screen.getByText(/Posted entries cannot be changed/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^(Edit|Submit|Approve|Post|Void)/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reverse" }));
    expect(onAct).not.toHaveBeenCalled(); // a reason is required first
    fireEvent.change(screen.getByLabelText("Reason for reversal"), { target: { value: "Wrong account" } });
    fireEvent.click(screen.getByRole("button", { name: "Reverse" }));
    expect(onAct).toHaveBeenCalledWith("reverse", "Wrong account");
    await noAxeViolations(container);
  });

  it("a reversed entry offers no further actions", () => {
    render(wrap(<EntryActions entry={{ ...posted, reversed_by_entry_id: "e2" }} myId="u1" onAct={vi.fn()} />));
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("the preparer cannot approve their own entry", () => {
    render(wrap(<EntryActions entry={{ ...posted, status: "SUBMITTED" }} myId="u1" onAct={vi.fn()} />));
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
  });
});
