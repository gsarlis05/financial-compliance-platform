// The owner's check (brief 27, #254): the projection screens read it from the record, and never
// call it a professional validation.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { EngineReviewNote, dayMonthYear } from "./components/ReviewNote";
import { I18nProvider } from "./i18n/I18n";

function show(reviews: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify(reviews), {
          headers: { "Content-Type": "application/json" },
        }),
      ),
    ),
  );
  render(
    <QueryClientProvider client={new QueryClient()}>
      <I18nProvider locale="en">
        <MemoryRouter initialEntries={["/w/ws/e/e1/projections"]}>
          <Routes>
            <Route
              path="/w/:slug/e/:entityId/projections"
              element={<EngineReviewNote />}
            />
          </Routes>
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("The engine's review note", () => {
  it("says the owner checked it, and that it is not a professional validation", async () => {
    show([
      {
        subject: "PROJECTION_ENGINE",
        status: "OWNER_CHECKED",
        on: "2026-11-27",
        by: "The owner",
        note: "",
        label: "",
      },
    ]);
    expect(
      await screen.findByText(
        /You checked the projection engine on 27\/11\/2026/,
      ),
    ).toHaveTextContent("not been independently validated");
  });

  it("stays pending until someone has checked it", () => {
    show([]);
    expect(screen.getByRole("note")).toHaveTextContent(
      "Pending professional review",
    );
    expect(dayMonthYear("2026-01-05")).toBe("05/01/2026");
  });
});
