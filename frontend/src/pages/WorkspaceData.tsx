// Export and delete (M5-6). Owners download everything the workspace holds, and can delete the
// workspace in two steps with a grace period. The server enforces every rule.
import { useState } from "react";
import { useParams } from "react-router";
import { useWorkspace } from "../api/hooks";
import { useDeletion, useLifecycleMutations } from "../api/lifecycle";
import { Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";

export function WorkspaceDataPage() {
  const { t } = useI18n();
  const { slug = "" } = useParams();
  const ws = useWorkspace(slug);
  const deletion = useDeletion(slug);
  const m = useLifecycleMutations(slug);
  const [name, setName] = useState("");
  const state = deletion.data;
  return (
    <Page title={t("data.title")}>
      <section className="card" aria-labelledby="data-export">
        <h2 id="data-export">{t("data.export")}</h2>
        <p className="muted">{t("data.exportText")}</p>
        <button
          type="button"
          className="primary"
          disabled={m.exportAll.isPending}
          onClick={() => m.exportAll.mutate()}
        >
          {t("data.exportButton")}
        </button>
        {m.exportAll.isPending ? <Loading /> : null}
        {m.exportAll.data ? (
          <p role="status">
            {t("data.exported")} {m.exportAll.data}
          </p>
        ) : null}
        <ProblemMessage error={m.exportAll.error} />
      </section>

      <section className="card" aria-labelledby="data-delete">
        <h2 id="data-delete">{t("data.delete")}</h2>
        {deletion.isPending ? <Loading /> : null}
        <ProblemMessage
          error={
            deletion.error ??
            m.request.error ??
            m.confirm.error ??
            m.cancel.error
          }
        />
        {state?.status === "NONE" ? (
          <>
            <p className="muted">
              {t("data.deleteText")} {state.grace_days} {t("data.days")}
            </p>
            <button
              type="button"
              disabled={m.request.isPending}
              onClick={() => m.request.mutate()}
            >
              {t("data.request")}
            </button>
          </>
        ) : null}
        {state?.status === "REQUESTED" ? (
          <>
            <p>
              {t("data.confirmText")} <strong>{ws.data?.name}</strong>
            </p>
            <div className="form inline">
              <label>
                {t("data.typeName")}
                <input
                  value={name}
                  autoComplete="off"
                  onChange={(e) => setName(e.target.value)}
                />
              </label>
              <button
                type="button"
                className="danger"
                disabled={!name.trim() || m.confirm.isPending}
                onClick={() => m.confirm.mutate(name)}
              >
                {t("data.confirm")}
              </button>
              <button
                type="button"
                disabled={m.cancel.isPending}
                onClick={() => m.cancel.mutate()}
              >
                {t("data.cancel")}
              </button>
            </div>
          </>
        ) : null}
        {state?.status === "CONFIRMED" ? (
          <>
            <p role="alert">
              {t("data.confirmed")}{" "}
              <strong>{state.purge_after?.slice(0, 10)}</strong>.{" "}
              {t("data.confirmedText")}
            </p>
            <button
              type="button"
              className="primary"
              disabled={m.cancel.isPending}
              onClick={() => m.cancel.mutate()}
            >
              {t("data.keep")}
            </button>
          </>
        ) : null}
      </section>
    </Page>
  );
}
