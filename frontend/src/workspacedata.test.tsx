import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import axe from "axe-core";
import { MemoryRouter, Route, Routes } from "react-router";
import { I18nProvider } from "./i18n/I18n";
import { WorkspaceDataPage } from "./pages/WorkspaceData";

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const none = {
  status: "NONE",
  requested_at: null,
  confirmed_at: null,
  purge_after: null,
  grace_days: 30,
};

describe("Workspace export and deletion (M5-6)", () => {
  it("downloads the export and deletes in two steps that can be cancelled", async () => {
    let state: Record<string, unknown> = none;
    const sent: { url: string; body: unknown }[] = [];
    const saved: string[] = [];
    document.cookie = "__Host-fcp_csrftoken=test";
    URL.createObjectURL = vi.fn(() => "blob:export");
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      saved.push(this.download);
    });
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init: RequestInit) => {
        if ((init.method ?? "GET") === "GET") {
          return Promise.resolve(
            url.endsWith("/deletion")
              ? respond(state)
              : respond({
                  id: "t",
                  slug: "ws",
                  name: "Demo Trading",
                  kind: "BUSINESS",
                  roles: ["owner"],
                }),
          );
        }
        sent.push({ url, body: JSON.parse(init.body as string) });
        if (url.endsWith("/export"))
          return Promise.resolve(
            new Response("zip", {
              status: 200,
              headers: {
                "Content-Type": "application/zip",
                "Content-Disposition":
                  'attachment; filename="ws-export-20261110-120000.zip"',
              },
            }),
          );
        if (url.endsWith("/confirm"))
          state = {
            ...none,
            status: "CONFIRMED",
            purge_after: "2026-12-10T12:00:00Z",
          };
        else if (url.endsWith("/cancel")) state = none;
        else state = { ...none, status: "REQUESTED" };
        return Promise.resolve(respond(state, 200));
      }),
    );
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider locale="en">
          <MemoryRouter initialEntries={["/w/ws/data"]}>
            <Routes>
              <Route path="/w/:slug/data" element={<WorkspaceDataPage />} />
            </Routes>
          </MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Download the export" }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Downloaded: ws-export-20261110-120000.zip",
    );
    expect(saved).toEqual(["ws-export-20261110-120000.zip"]);

    // Step 1: request. Step 2: type the name and confirm.
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Start deleting this workspace",
      }),
    );
    const name = await screen.findByLabelText("Workspace name");
    const confirm = screen.getByRole("button", {
      name: "Confirm the deletion",
    });
    expect(confirm).toBeDisabled();
    fireEvent.change(name, { target: { value: "Demo Trading" } });
    fireEvent.click(confirm);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This workspace will be deleted for good after 2026-12-10.",
    );
    expect(sent.map((s) => s.url)).toEqual([
      "/api/w/ws/export",
      "/api/w/ws/deletion",
      "/api/w/ws/deletion/confirm",
    ]);
    expect(sent[2]?.body).toEqual({ workspace_name: "Demo Trading" });
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => v.id)).toEqual([]);

    // Changed their mind inside the grace period.
    fireEvent.click(
      screen.getByRole("button", { name: "Keep this workspace" }),
    );
    await waitFor(() =>
      expect(sent.at(-1)?.url).toBe("/api/w/ws/deletion/cancel"),
    );
    expect(
      await screen.findByRole("button", {
        name: "Start deleting this workspace",
      }),
    ).toBeInTheDocument();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });
});
