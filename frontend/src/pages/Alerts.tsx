import { useState } from "react";
import { Link } from "react-router";
import { type Alert, useAlertMutations, useAlerts } from "../api/alerts";
import { useScope } from "../api/hooks";
import { Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";

function Acknowledge({ alert }: { alert: Alert }) {
  const { t } = useI18n();
  const m = useAlertMutations();
  const [note, setNote] = useState("");
  return (
    <div className="form inline">
      <label>
        {t("alert.note")}
        <input
          value={note}
          maxLength={300}
          onChange={(e) => setNote(e.target.value)}
        />
      </label>
      <button
        type="button"
        disabled={m.acknowledge.isPending}
        onClick={() => m.acknowledge.mutate({ id: alert.id, note })}
      >
        {t("alert.acknowledge")}
      </button>
      <ProblemMessage error={m.acknowledge.error} />
    </div>
  );
}

export function AlertsPage() {
  const { t } = useI18n();
  const { slug, entityId } = useScope();
  const [all, setAll] = useState(false);
  const found = useAlerts(all);
  const m = useAlertMutations();
  const link = (a: Alert) =>
    `/w/${slug}/e/${entityId}/${a.subject_type === "goal" ? "goals" : "budgets"}`;
  return (
    <Page
      title={t("alert.title")}
      actions={
        <button
          type="button"
          disabled={m.check.isPending}
          onClick={() => m.check.mutate()}
        >
          {t("alert.checkBudgets")}
        </button>
      }
    >
      <p className="muted">{t("alert.intro")}</p>
      {m.check.data ? (
        <p role="status">
          {t("alert.raised")}: {m.check.data.raised}
        </p>
      ) : null}
      <ProblemMessage error={m.check.error ?? found.error} />
      <label className="checkbox">
        <input
          type="checkbox"
          checked={all}
          onChange={(e) => setAll(e.target.checked)}
        />{" "}
        {t("alert.showAcknowledged")}
      </label>
      {found.isPending ? <Loading /> : null}
      {found.data && !found.data.length ? (
        <p className="muted">{t("alert.none")}</p>
      ) : null}
      <ul className="alerts">
        {(found.data ?? []).map((a) => (
          <li key={a.id}>
            <section className="card" aria-labelledby={`alert-${a.id}`}>
              <h2 id={`alert-${a.id}`}>
                <span
                  className={`badge ${a.severity === "CRITICAL" ? "badge-warn" : ""}`}
                >
                  {t(`alert.severity.${a.severity}` as MessageKey)}
                </span>{" "}
                {a.title}
              </h2>
              <p>{a.detail}</p>
              <p className="muted">
                {t(`alert.kind.${a.kind}` as MessageKey)} ·{" "}
                {a.created_at.slice(0, 16).replace("T", " ")} ·{" "}
                <Link to={link(a)}>{t("alert.open")}</Link>
              </p>
              {a.acknowledged_at ? (
                <p>
                  {t("alert.acknowledgedBy")} {a.acknowledged_by_name},{" "}
                  {a.acknowledged_at.slice(0, 10)}
                  {a.acknowledgement_note ? `: ${a.acknowledgement_note}` : ""}
                </p>
              ) : (
                <Acknowledge alert={a} />
              )}
            </section>
          </li>
        ))}
      </ul>
    </Page>
  );
}
