import type { ReactNode } from "react";
import { ApiError } from "../api/client";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";

/** Shows a server problem (RFC 9457) with its actionable detail and correlation reference. */
export function ProblemMessage({ error }: { error: unknown }) {
  const { t } = useI18n();
  if (!error) {
    return null;
  }
  const problem = error instanceof ApiError ? error.problem : null;
  return (
    <div role="alert" className="problem">
      <strong>{problem?.title ?? t("app.error")}</strong>
      <p>{problem?.detail ?? (error instanceof Error ? error.message : String(error))}</p>
      {problem?.correlation_id ? (
        <p className="muted">
          {t("app.reference")}: <code>{problem.correlation_id}</code>
        </p>
      ) : null}
    </div>
  );
}

/** Field-level error from a problem response, e.g. key "lines.0.debit". */
export function FieldError({ error, field, id }: { error: unknown; field: string; id?: string }) {
  if (!(error instanceof ApiError)) {
    return null;
  }
  const messages = error.fieldErrors()[field];
  if (!messages?.length) {
    return null;
  }
  return (
    <span className="field-error" role="alert" id={id}>
      {messages.join(" ")}
    </span>
  );
}

export function Loading() {
  const { t } = useI18n();
  return (
    <p className="muted" aria-live="polite">
      {t("app.loading")}
    </p>
  );
}

export function StatusBadge({ prefix, status }: { prefix: "je.status" | "per.status"; status: string }) {
  const { t } = useI18n();
  return <span className={`badge badge-${status.toLowerCase()}`}>{t(`${prefix}.${status}` as MessageKey)}</span>;
}

export function Page({ title, actions, children }: { title: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="page">
      <header className="page-header">
        <h1>{title}</h1>
        {actions ? <div className="actions">{actions}</div> : null}
      </header>
      {children}
    </section>
  );
}
