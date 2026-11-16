import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import axe from "axe-core";
import { MemoryRouter, Route, Routes } from "react-router";
import { Layout } from "./components/Layout";
import { I18nProvider } from "./i18n/I18n";
import type { Locale } from "./i18n/messages";

function renderAt(path: string, locale: Locale = "en") {
  const workspace = { slug: "demo", name: "Demo", kind: "BUSINESS" };
  const body = (url: string) =>
    url.endsWith("/w/demo") ? workspace : url.endsWith("/me") ? { email: "me@example.test" } : [];
  vi.stubGlobal("fetch", vi.fn((url: string) =>
    Promise.resolve(new Response(JSON.stringify(body(url)), {
      status: 200, headers: { "Content-Type": "application/json" } }))));
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <I18nProvider locale={locale}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route element={<Layout />}>
              <Route path="/w/:slug/e/:entityId/*" element={<p>page</p>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("Grouped navigation (M2-11)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("groups the pages, marks the current group and opens one group at a time", async () => {
    const { container } = renderAt("/w/demo/e/ent/statements");
    const nav = screen.getByRole("navigation", { name: "Main" });
    const groups = Array.from(nav.querySelectorAll(":scope > ul > li > button")).map((b) => b.textContent);
    expect(groups).toEqual(["Bookkeeping ▾", "Customers & suppliers ▾", "Reports ▾", "Setup ▾", "Controls ▾"]);
    expect(nav.querySelector("li.current > button")).toHaveTextContent("Reports");
    expect(screen.queryByRole("link", { name: "Statements" })).not.toBeInTheDocument(); // hidden

    const reports = screen.getByRole("button", { name: /Reports/ });
    fireEvent.click(reports);
    expect(reports).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Statements" })).toHaveAttribute("href", "/w/demo/e/ent/statements");
    expect(screen.getByRole("link", { name: "Trial balance" })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: /Setup/ }));
    expect(reports).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("link", { name: "Statement mapping" })).toBeInTheDocument();
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((v) => v.id)).toEqual([]);

    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("link", { name: "Statement mapping" })).not.toBeInTheDocument();
  });

  it("works with the keyboard", async () => {
    renderAt("/w/demo/e/ent/entries");
    const setup = screen.getByRole("button", { name: /Setup/ });
    setup.focus();
    fireEvent.keyDown(setup, { key: "ArrowDown" });
    await waitFor(() => expect(screen.getByRole("link", { name: "Chart of accounts" })).toHaveFocus());
    fireEvent.keyDown(document.activeElement as Element, { key: "ArrowDown" });
    expect(screen.getByRole("link", { name: "Dimensions" })).toHaveFocus();
    fireEvent.keyDown(document.activeElement as Element, { key: "End" });
    expect(screen.getByRole("link", { name: "Periods" })).toHaveFocus();
    fireEvent.keyDown(document.activeElement as Element, { key: "ArrowDown" });
    expect(screen.getByRole("link", { name: "Chart of accounts" })).toHaveFocus(); // wraps
    fireEvent.keyDown(document.activeElement as Element, { key: "Escape" });
    expect(setup).toHaveAttribute("aria-expanded", "false");
    expect(setup).toHaveFocus();
  });

  it("is translated", () => {
    renderAt("/w/demo/e/ent/entries", "el");
    expect(screen.getByRole("navigation", { name: "Κύρια πλοήγηση" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Αναφορές/ })).toBeInTheDocument();
  });
});
