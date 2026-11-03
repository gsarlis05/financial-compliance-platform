import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider } from "react-router";
import { ApiError, loginUrl } from "./api/client";
import { useMe } from "./api/hooks";
import { Loading, ProblemMessage } from "./components/common";
import { Layout } from "./components/Layout";
import { I18nProvider, useI18n } from "./i18n/I18n";
import { AccountsPage } from "./pages/Accounts";
import { DimensionsPage } from "./pages/Dimensions";
import { ApprovalsPage, EntriesPage, EntryDetailPage, NewEntryPage } from "./pages/Entries";
import { PeriodsPage } from "./pages/Periods";
import { IntegrityPage, TrialBalancePage } from "./pages/Reports";
import { WorkspaceHome, WorkspacesPage } from "./pages/Workspaces";

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { index: true, element: <WorkspacesPage /> },
      { path: "w/:slug", element: <WorkspaceHome /> },
      { path: "w/:slug/e/:entityId/entries", element: <EntriesPage /> },
      { path: "w/:slug/e/:entityId/entries/new", element: <NewEntryPage /> },
      { path: "w/:slug/e/:entityId/entries/:entryId", element: <EntryDetailPage /> },
      { path: "w/:slug/e/:entityId/approvals", element: <ApprovalsPage /> },
      { path: "w/:slug/e/:entityId/accounts", element: <AccountsPage /> },
      { path: "w/:slug/e/:entityId/dimensions", element: <DimensionsPage /> },
      { path: "w/:slug/e/:entityId/periods", element: <PeriodsPage /> },
      { path: "w/:slug/e/:entityId/trial-balance", element: <TrialBalancePage /> },
      { path: "w/:slug/e/:entityId/integrity", element: <IntegrityPage /> },
    ],
  },
]);

/** Everything requires a signed-in user. The session cookie is HttpOnly, so we ask /api/me. */
function AuthGate() {
  const { t } = useI18n();
  const me = useMe();
  if (me.isPending) {
    return <Loading />;
  }
  if (me.error instanceof ApiError && me.error.status === 401) {
    return (
      <main className="signed-out" id="main">
        <h1>{t("app.signedOutTitle")}</h1>
        <p>{t("app.signedOutBody")}</p>
        <a className="button primary" href={loginUrl()}>
          {t("app.signIn")}
        </a>
      </main>
    );
  }
  if (me.error) {
    return <ProblemMessage error={me.error} />;
  }
  return <RouterProvider router={router} />;
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
    },
  },
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <AuthGate />
      </I18nProvider>
    </QueryClientProvider>
  );
}
