// Help for data entry (V1-2i, #231): the VAT code picker (favourites first, most used, search by
// code, name or rate, keyboard, a star per code, the account's usual code offered) and typing
// suggestions for the description, memos and references.
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import axe from "axe-core";
import type { EntryHelpers } from "./api/entryHelpers";
import type { Account, FiscalYear, VatCode } from "./api/types";
import { I18nProvider } from "./i18n/I18n";
import { EntryForm } from "./pages/EntryForm";

function code(id: string, rate: string | null, name: string): VatCode {
  return {
    id: `CY:${id}:open`,
    code: id,
    name,
    name_el: "",
    treatment: "STANDARD",
    category: "DOMESTIC",
    rate,
    valid_from: null,
    valid_to: null,
    verified: true,
    verification_note: "",
  };
}
const codes = [
  code("S19", "0.1900", "Standard rate"),
  code("R9", "0.0900", "Reduced rate"),
  code("R5", "0.0500", "Reduced rate"),
  code("Z0", "0.0000", "Zero rate"),
];
const accounts: Account[] = [
  {
    id: "a1",
    code: "6100",
    name: "Office supplies",
    name_el: "",
    type: "EXPENSE",
    normal_side: "DEBIT",
    parent_id: null,
    is_postable: true,
    status: "ACTIVE",
    currency: "",
    control_type: "",
    vat_role: "",
  },
];
const years: FiscalYear[] = [];

function setup(overrides: Partial<EntryHelpers> = {}) {
  const helpers: EntryHelpers = {
    favourites: ["CY:R5:open"],
    toggleFavourite: vi.fn(),
    uses: { "CY:S19:open": 12, "CY:Z0:open": 3 },
    usual: { a1: "CY:S19:open" },
    suggest: vi.fn().mockResolvedValue([]),
    ...overrides,
  };
  const onSave = vi.fn();
  const utils = render(
    <I18nProvider locale="en">
      <EntryForm
        accounts={accounts}
        vatCodes={codes}
        fiscalYears={years}
        saving={false}
        error={null}
        onSave={onSave}
        helpers={helpers}
      />
    </I18nProvider>,
  );
  return { helpers, onSave, ...utils };
}

const choices = (name: string) =>
  within(screen.getByRole("listbox", { name: `Choices for ${name}` }));
const vat = (n: number) =>
  screen.getByRole<HTMLInputElement>("combobox", { name: `VAT ${n}` });

describe("VAT code picker", () => {
  it("lists favourites, then the most used, then every code", async () => {
    const { container } = setup();
    fireEvent.focus(vat(1));
    const groups = screen
      .getAllByRole("group")
      .map((g) => g.getAttribute("aria-label"));
    expect(groups).toEqual(["★ Favourites", "Most used", "Domestic"]);
    const favourites = screen.getByRole("group", { name: "★ Favourites" });
    expect(favourites).toHaveTextContent("R5 · Reduced rate");
    const used = screen.getByRole("group", { name: "Most used" });
    expect(used.textContent).toMatch(/S19.*\(12\).*Z0.*\(3\)/);
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });

  it("filters by rate or name as you type and chooses with the keyboard", () => {
    setup({ favourites: [], uses: {} });
    fireEvent.change(vat(1), { target: { value: "9%" } });
    expect(
      choices("VAT 1")
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["R9 · Reduced rate"]);
    fireEvent.change(vat(1), { target: { value: "reduced" } });
    expect(choices("VAT 1").getAllByRole("option")).toHaveLength(2);
    fireEvent.keyDown(vat(1), { key: "ArrowDown" });
    fireEvent.keyDown(vat(1), { key: "ArrowDown" });
    expect(vat(1)).toHaveAttribute(
      "aria-activedescendant",
      choices("VAT 1").getAllByRole("option")[1]?.id,
    );
    fireEvent.keyDown(vat(1), { key: "Enter" });
    expect(vat(1)).toHaveValue("R5 · Reduced rate");
    expect(vat(1)).toHaveAttribute("aria-expanded", "false");
    fireEvent.change(vat(1), { target: { value: "nothing like it" } });
    expect(screen.getByText("No VAT code matches.")).toBeInTheDocument();
    fireEvent.blur(vat(1));
    expect(vat(1)).toHaveValue("R5 · Reduced rate");
  });

  it("stars and unstars the chosen code", () => {
    const { helpers } = setup();
    const star = () => screen.getAllByRole("button", { name: /favourites/ })[0];
    expect(star()).toBeDisabled();
    fireEvent.change(vat(1), { target: { value: "S19" } });
    fireEvent.click(
      screen.getByRole("button", { name: "Add S19 to my favourites" }),
    );
    expect(helpers.toggleFavourite).toHaveBeenCalledWith("CY:S19:open", true);
    fireEvent.change(vat(1), { target: { value: "R5" } });
    const remove = screen.getByRole("button", {
      name: "Remove R5 from my favourites",
    });
    expect(remove).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(remove);
    expect(helpers.toggleFavourite).toHaveBeenCalledWith("CY:R5:open", false);
  });

  it("offers the account's usual code and never chooses it alone", () => {
    const { onSave } = setup();
    fireEvent.change(screen.getByLabelText("Account 1"), {
      target: { value: "a1" },
    });
    expect(vat(1)).toHaveValue("");
    fireEvent.click(
      screen.getByRole("button", {
        name: "Use S19, the usual code for this account",
      }),
    );
    expect(vat(1)).toHaveValue("S19 · Standard rate");
    fireEvent.change(screen.getByRole("combobox", { name: "Description" }), {
      target: { value: "Paper" },
    });
    fireEvent.change(screen.getByLabelText("Debit 1"), {
      target: { value: "10" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    const [body] = onSave.mock.calls[0] as [
      { lines: { vat_code_id: string | null }[] },
    ];
    expect(body.lines[0]?.vat_code_id).toBe("CY:S19:open");
  });
});

describe("Typing suggestions", () => {
  it("offers what was typed before and fills the field when chosen", async () => {
    const suggest = vi.fn().mockResolvedValue([
      {
        value: "Office rent March",
        uses: 3,
        last_used: "2026-03-01T10:00:00Z",
      },
      {
        value: "Office rent April",
        uses: 1,
        last_used: "2026-04-01T10:00:00Z",
      },
    ]);
    setup({ suggest });
    const description = screen.getByRole("combobox", { name: "Description" });
    fireEvent.change(description, { target: { value: "off" } });
    await waitFor(() =>
      expect(suggest).toHaveBeenLastCalledWith("description", "off"),
    );
    const option = await screen.findByRole("option", {
      name: /Office rent March/,
    });
    fireEvent.mouseDown(option);
    expect(description).toHaveValue("Office rent March");

    fireEvent.change(screen.getByRole("combobox", { name: "Memo 1" }), {
      target: { value: "o" },
    });
    await waitFor(() => expect(suggest).toHaveBeenLastCalledWith("memo", "o"));
  });

  it("asks once per pause in typing and ignores a failed request", async () => {
    vi.useFakeTimers();
    try {
      const suggest = vi.fn().mockRejectedValue(new Error("offline"));
      setup({ suggest });
      const description = screen.getByRole("combobox", { name: "Description" });
      for (const text of ["o", "of", "off"]) {
        fireEvent.change(description, { target: { value: text } });
      }
      await act(async () => {
        await vi.advanceTimersByTimeAsync(250);
      });
      expect(suggest).toHaveBeenCalledTimes(1);
      expect(suggest).toHaveBeenCalledWith("description", "off");
      expect(description).toHaveValue("off");
    } finally {
      vi.useRealTimers();
    }
  });
});
