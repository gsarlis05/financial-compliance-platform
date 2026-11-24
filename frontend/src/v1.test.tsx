// Version 1 (V1-1): the one-person workspace setting and the "sign in again" link.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import axe from "axe-core";
import { MemoryRouter, Route, Routes } from "react-router";
import { ApiError } from "./api/client";
import { ProblemMessage } from "./components/common";
import { I18nProvider } from "./i18n/I18n";
import { WorkspaceDataPage } from "./pages/WorkspaceData";

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

type Sent = { url: string; method: string; body?: unknown };

function stub(onePerson: unknown, saved: unknown) {
  const sent: Sent[] = [];
  document.cookie = "__Host-fcp_csrftoken=test";
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init: RequestInit) => {
      const method = init.method ?? "GET";
      if (method !== "GET") {
        sent.push({ url, method, body: JSON.parse(init.body as string) });
        return Promise.resolve(respond(saved));
      }
      if (url.endsWith("/one-person"))
        return Promise.resolve(respond(onePerson));
      if (url.endsWith("/deletion"))
        return Promise.resolve(
          respond({ status: "NONE", requested_at: null, confirmed_at: null,
                    purge_after: null, grace_days: 30 }), // prettier-ignore
        );
      return Promise.resolve(
        respond({
          id: "w",
          slug: "ws",
          name: "Demo",
          kind: "BUSINESS",
          roles: ["owner"],
        }),
      );
    }),
  );
  return sent;
}

function mount() {
  return render(
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
}

async function accessible(container: HTMLElement) {
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);
}

describe("One-person workspace (V1-1)", () => {
  it("is off by default and turns on", async () => {
    const sent = stub(
      { enabled: false, active: false, blockers: [] },
      { enabled: true, active: true, blockers: [] },
    );
    const { container } = mount();
    expect(
      await screen.findByText("Off: a second person must approve."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Turn on" }));
    await waitFor(() =>
      expect(sent[0]).toEqual({
        url: "/api/w/ws/one-person",
        method: "PUT",
        body: { enabled: true },
      }),
    );
    expect(
      await screen.findByText("On: you can approve your own work."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Turn off" })).toBeEnabled();
    await accessible(container);
  });

  it("says why it cannot be turned on", async () => {
    stub(
      {
        enabled: false,
        active: false,
        blockers: [
          "The workspace has 2 active members; it must have exactly one.",
        ],
      },
      {},
    );
    mount();
    expect(
      await screen.findByText(
        "The workspace has 2 active members; it must have exactly one.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Turn on" })).toBeDisabled();
  });
});

describe("Recent sign-in needed", () => {
  it("offers a link to sign in again and come back", () => {
    const error = new ApiError({
      type: "about:blank",
      title: "Recent authentication required",
      status: 401,
      detail: "This action needs a recent sign-in. Sign in again to continue.",
      code: "auth.step_up_required",
      correlation_id: null,
    });
    render(
      <I18nProvider locale="en">
        <ProblemMessage error={error} />
      </I18nProvider>,
    );
    const link = screen.getByRole("link", { name: "Sign in again" });
    expect(link.getAttribute("href")).toBe("/auth/login?next=%2F&step_up=1");
  });
});
