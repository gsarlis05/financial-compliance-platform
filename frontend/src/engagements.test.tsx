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
import { EngagementsPage } from "./pages/Engagements";

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function show(
  kind: string,
  data: Record<string, unknown>,
  sent: { url: string; body: unknown }[],
) {
  document.cookie = "__Host-fcp_csrftoken=test";
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init: RequestInit) => {
      if ((init.method ?? "GET") !== "GET") {
        sent.push({ url, body: JSON.parse(init.body as string) });
        return Promise.resolve(respond({}, 201));
      }
      const key = Object.keys(data).find((k) => url.endsWith(k));
      if (key) return Promise.resolve(respond(data[key]));
      if (url.endsWith("/w/ws"))
        return Promise.resolve(
          respond({ id: "t", slug: "ws", name: "Workspace", kind, roles: [] }),
        );
      return Promise.resolve(respond([]));
    }),
  );
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <I18nProvider locale="en">
        <MemoryRouter initialEntries={["/w/ws/e/e1/engagements"]}>
          <Routes>
            <Route
              path="/w/:slug/e/:entityId/engagements"
              element={<EngagementsPage />}
            />
          </Routes>
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("Engagement grants (M5-4)", () => {
  it("lets a business grant a firm scoped access and end it", async () => {
    const sent: { url: string; body: unknown }[] = [];
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { container } = show(
      "BUSINESS",
      {
        "/engagements": [
          {
            id: "g1",
            firm_name: "Sarlis & Co",
            scope_roles: ["accountant", "read_only"],
            legal_entity_id: null,
            valid_until: "2027-11-10T23:59:59Z",
            created_at: "2026-11-10T00:00:00Z",
            revoked_at: null,
            active: true,
          },
          {
            id: "g0",
            firm_name: "Old Firm",
            scope_roles: ["read_only"],
            legal_entity_id: null,
            valid_until: "2026-01-01T00:00:00Z",
            created_at: "2025-11-10T00:00:00Z",
            revoked_at: null,
            active: false,
          },
        ],
      },
      sent,
    );
    const table = await screen.findByRole("table", {
      name: "Firms with access",
    });
    const current = within(table).getByRole("row", { name: /Sarlis & Co/ });
    expect(current).toHaveTextContent("Accountant, Read only");
    expect(current).toHaveTextContent("Active");
    const old = within(table).getByRole("row", { name: /Old Firm/ });
    expect(old).toHaveTextContent("Ended");
    expect(within(old).queryByRole("button")).toBeNull();

    fireEvent.change(screen.getByLabelText("Firm's address"), {
      target: { value: " sarlis-co-1a2b3c " },
    });
    fireEvent.click(screen.getByLabelText("Accountant"));
    fireEvent.change(screen.getByLabelText("Until"), {
      target: { value: "2027-06-30" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Grant access" }));
    await waitFor(() =>
      expect(sent[0]).toEqual({
        url: "/api/w/ws/engagements",
        body: {
          firm_slug: "sarlis-co-1a2b3c",
          scope_roles: ["read_only", "accountant"],
          valid_until: "2027-06-30T23:59:59Z",
        },
      }),
    );
    fireEvent.click(
      within(current).getByRole("button", { name: "End access" }),
    );
    await waitFor(() =>
      expect(sent[1]?.url).toBe("/api/w/ws/engagements/g1/revoke"),
    );
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => v.id)).toEqual([]);
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("offers a personal workspace read-only access only", async () => {
    show("PERSONAL", { "/engagements": [] }, []);
    expect(await screen.findByLabelText("Read only")).toBeChecked();
    expect(screen.queryByLabelText("Accountant")).toBeNull();
    expect(await screen.findByText("No firm has access.")).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it("lets a firm see its clients and assign its people", async () => {
    const sent: { url: string; body: unknown }[] = [];
    const { container } = show(
      "FIRM",
      {
        "/client-engagements": [
          {
            engagement_id: "g1",
            client_slug: "client-x",
            client_name: "Client X",
            client_kind: "BUSINESS",
            scope_roles: ["accountant"],
            legal_entity_id: null,
            valid_until: "2027-11-10T23:59:59Z",
            staff: [
              {
                id: "s1",
                membership_id: "m1",
                email: "acc@firm.test",
                display_name: "Anna Accountant",
              },
            ],
          },
        ],
        "/members": [
          {
            membership_id: "m1",
            email: "acc@firm.test",
            display_name: "Anna Accountant",
            status: "ACTIVE",
          },
          {
            membership_id: "m2",
            email: "view@firm.test",
            display_name: "",
            status: "ACTIVE",
          },
        ],
      },
      sent,
    );
    const table = await screen.findByRole("table", {
      name: "Clients who let you in",
    });
    const row = within(table).getByRole("row", { name: /Client X/ });
    expect(within(row).getByRole("link", { name: "Client X" })).toHaveAttribute(
      "href",
      "/w/client-x",
    );
    expect(row).toHaveTextContent("Anna Accountant");
    const pick = await within(row).findByRole("combobox", {
      name: "Assign Client X",
    });
    await within(pick).findByRole("option", { name: "view@firm.test" });
    // Someone already on the engagement is not offered again.
    expect(
      within(pick).queryByRole("option", { name: "Anna Accountant" }),
    ).toBeNull();
    fireEvent.change(pick, { target: { value: "m2" } });
    fireEvent.click(within(row).getByRole("button", { name: "Assign" }));
    await waitFor(() =>
      expect(sent[0]).toEqual({
        url: "/api/w/ws/client-engagements/g1/staff",
        body: { membership_id: "m2" },
      }),
    );
    fireEvent.click(within(row).getByRole("button", { name: "Remove" }));
    await waitFor(() =>
      expect(sent[1]?.url).toBe("/api/w/ws/client-engagements/staff/s1/remove"),
    );
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => v.id)).toEqual([]);
    vi.unstubAllGlobals();
  });
});
