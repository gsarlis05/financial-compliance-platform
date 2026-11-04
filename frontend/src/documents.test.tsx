import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import axe from "axe-core";
import { MemoryRouter, Route, Routes } from "react-router";
import { DocumentsPanel } from "./components/Documents";
import { I18nProvider } from "./i18n/I18n";

const doc = {
  id: "d1", filename: "invoice-INV-1.pdf", content_type: "application/pdf", size: 2048, sha256: "x",
  created_at: "2026-03-15T10:00:00Z", uploaded_by_id: "u1", links: [{ id: "l1", entry_id: "e1", line_id: null }],
};

describe("Documents panel (M2-4)", () => {
  const calls: { url: string; method: string; body: unknown }[] = [];
  beforeEach(() => {
    calls.length = 0;
    document.cookie = "__Host-fcp_csrftoken=test";
    vi.stubGlobal("fetch", vi.fn((url: string, init: RequestInit) => {
      calls.push({ url, method: init.method ?? "GET", body: init.body });
      if ((init.method ?? "GET") === "POST") {
        return Promise.resolve(new Response(JSON.stringify({
          type: "x", title: "The file was rejected by the virus scanner", status: 422, code: "documents.malware_detected",
          detail: "The virus scanner found Eicar-Test-Signature in this file, so it was not stored.",
        }), { status: 422, headers: { "Content-Type": "application/problem+json" } }));
      }
      return Promise.resolve(new Response(JSON.stringify([doc]), { status: 200, headers: { "Content-Type": "application/json" } }));
    }));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("lists attached documents and reports a rejected upload", async () => {
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider locale="en">
          <MemoryRouter initialEntries={["/w/demo/e/ent/entries/e1"]}>
            <Routes>
              <Route path="/w/:slug/e/:entityId/entries/:entryId" element={<DocumentsPanel entryId="e1" />} />
            </Routes>
          </MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("link", { name: "invoice-INV-1.pdf" })).toHaveAttribute(
      "href", "/api/w/demo/entities/ent/documents/d1/content");
    const file = new File(["X5O!P%@AP"], "notes.txt", { type: "text/plain" });
    fireEvent.change(screen.getByLabelText("Attach a document"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Eicar-Test-Signature");
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const body = calls.find((c) => c.method === "POST")?.body as FormData;
    expect(body.get("entry_id")).toBe("e1");
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((v) => v.id)).toEqual([]);
  });
});
