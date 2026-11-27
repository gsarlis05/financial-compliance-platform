// The Tax Department XML on the VAT screen, as a draft (brief 27, T-3, #256): it explains what it
// waits for and produces nothing.
import { render, screen } from "@testing-library/react";
import axe from "axe-core";
import { I18nProvider } from "./i18n/I18n";
import { XmlDraft } from "./pages/Vat";

describe("Tax Department XML", () => {
  it("is marked draft and cannot be downloaded", async () => {
    const { container } = render(
      <I18nProvider locale="en">
        <XmlDraft />
      </I18nProvider>,
    );
    expect(
      screen.getByRole("heading", { name: "Tax Department XML Draft" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("nothing is ever sent");
    const download = screen.getByRole("button", { name: /Download the XML/ });
    expect(download).toBeDisabled();
    expect(download).toHaveAccessibleDescription(/official schema \(XSD\)/);
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
});
