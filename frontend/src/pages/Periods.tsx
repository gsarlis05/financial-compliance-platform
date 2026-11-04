import { type SyntheticEvent, useState } from "react";
import { Link } from "react-router";
import {
  useAccounts,
  useCloseStatus,
  useFiscalYears,
  usePeriodMutations,
  useScope,
  useUnlocks,
  useYearEndMutations,
} from "../api/hooks";
import type { FiscalYear, Period } from "../api/types";
import { Loading, Page, ProblemMessage, StatusBadge } from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";
import { formatAmount } from "../money";

/** Year-end close and re-open (M2-9). The status loads when the panel is opened. */
function YearEnd({ year }: { year: FiscalYear }) {
  const { t, locale } = useI18n();
  const { slug, entityId } = useScope();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [chosen, setChosen] = useState("");
  const status = useCloseStatus(year.id, open);
  const accounts = useAccounts();
  const { close, reopen } = useYearEndMutations(year.id);
  const equity = (accounts.data ?? []).filter((a) => a.type === "EQUITY" && a.is_postable && a.status === "ACTIVE");
  const fallback = equity.find((a) => a.code === "3200") ?? equity[0];
  const accountId = chosen || fallback?.id || "";
  const entryLink = (id: string, label: string) => (
    <Link to={`/w/${slug}/e/${entityId}/entries/${id}`}>{label}</Link>
  );
  const s = status.data;
  return (
    <details className="year-end" onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>{t("ye.title")}</summary>
      <p className="muted">{t("ye.help")}</p>
      {status.isPending && open ? <Loading /> : null}
      <ProblemMessage error={status.error ?? close.error ?? reopen.error} />
      {s ? (
        <>
          {s.blockers.length && s.status === "OPEN" ? (
            <div className="notice warn" role="status">
              <p>{t("ye.blocked")}</p>
              <ul>
                {s.blockers.map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {s.closing_entry_id && s.status === "OPEN" ? (
            <p>
              {entryLink(s.closing_entry_id, t("ye.entry"))} · {s.closing_entry_status}
            </p>
          ) : null}
          {s.status === "OPEN" && !s.blockers.length ? (
            <form
              className="form inline"
              onSubmit={(e) => {
                e.preventDefault();
                close.mutate(accountId);
              }}
            >
              <p>
                {t("ye.result")}: <strong>{formatAmount(s.result, locale)}</strong>
              </p>
              <label>
                {t("ye.account")}
                <select value={accountId} onChange={(e) => setChosen(e.target.value)} required>
                  {equity.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.code} · {locale === "el" && a.name_el ? a.name_el : a.name}
                    </option>
                  ))}
                </select>
              </label>
              <button type="submit" className="primary" disabled={close.isPending || !accountId}>
                {t("ye.generate")}
              </button>
            </form>
          ) : null}
          {close.data ? <p>{entryLink(close.data.id, t("ye.entry"))}</p> : null}
          {s.status === "CLOSED" ? (
            <>
              <h3>{t("ye.checks")}</h3>
              <ul>
                {s.checks.map((c) => (
                  <li key={c.code}>
                    {c.ok ? "✓" : "✗"} {t(`ye.check.${c.code}` as MessageKey)}
                  </li>
                ))}
              </ul>
              {s.reopen_entry_id ? (
                <p>{entryLink(s.reopen_entry_id, t("ye.reopenEntry"))}</p>
              ) : (
                <form
                  className="inline-form"
                  onSubmit={(e) => {
                    e.preventDefault();
                    reopen.mutate(reason, { onSuccess: () => setReason("") });
                  }}
                >
                  <label>
                    <span className="visually-hidden">{t("ye.reopenReason")}</span>
                    <input
                      placeholder={t("ye.reopenReason")}
                      value={reason}
                      onChange={(e) => setReason(e.target.value)}
                      minLength={5}
                      required
                    />
                  </label>
                  <button type="submit" disabled={reopen.isPending}>
                    {t("ye.reopen")}
                  </button>
                </form>
              )}
            </>
          ) : null}
        </>
      ) : null}
    </details>
  );
}

function PeriodActions({ period }: { period: Period }) {
  const { t } = useI18n();
  const { setStatus, requestUnlock } = usePeriodMutations();
  const [reason, setReason] = useState("");
  const set = (status: Period["status"]) => setStatus.mutate({ periodId: period.id, status });
  if (period.status === "LOCKED") {
    return (
      <form
        className="inline-form"
        onSubmit={(e) => {
          e.preventDefault();
          requestUnlock.mutate({ periodId: period.id, reason }, { onSuccess: () => setReason("") });
        }}
      >
        <label>
          <span className="visually-hidden">{t("per.unlockReason")}</span>
          <input
            placeholder={t("per.unlockReason")}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            minLength={5}
            required
          />
        </label>
        <button type="submit">{t("per.requestUnlock")}</button>
        <ProblemMessage error={requestUnlock.error} />
      </form>
    );
  }
  return (
    <span className="row-actions">
      {period.status === "OPEN" ? <button onClick={() => set("SOFT_CLOSED")}>{t("per.softClose")}</button> : null}
      {period.status === "SOFT_CLOSED" ? <button onClick={() => set("OPEN")}>{t("per.reopen")}</button> : null}
      <button onClick={() => set("LOCKED")}>{t("per.lock")}</button>
      <ProblemMessage error={setStatus.error} />
    </span>
  );
}

export function PeriodsPage() {
  const { t } = useI18n();
  const years = useFiscalYears();
  const unlocks = useUnlocks();
  const { createYear, decideUnlock } = usePeriodMutations();
  const [start, setStart] = useState(`${new Date().getFullYear()}-01-01`);
  const [months, setMonths] = useState("12");

  function create(event: SyntheticEvent) {
    event.preventDefault();
    createYear.mutate({ start_date: start, months: Number.parseInt(months, 10) });
  }

  const openUnlocks = (unlocks.data ?? []).filter((u) => u.status === "REQUESTED" || u.status === "ACTIVE");
  return (
    <Page title={t("per.title")}>
      {years.isPending ? <Loading /> : null}
      <ProblemMessage error={years.error} />
      {(years.data ?? []).map((year) => (
        <section key={year.id} className="panel">
          <h2>
            {year.name} <span className="muted">({year.start_date} – {year.end_date})</span>
            {year.status === "CLOSED" ? <span className="badge badge-locked">{t("ye.closed")}</span> : null}
          </h2>
          <table>
            <thead>
              <tr>
                <th scope="col">{t("per.period")}</th>
                <th scope="col">{t("per.dates")}</th>
                <th scope="col">{t("per.status")}</th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {year.periods.map((p) => (
                <tr key={p.id}>
                  <td>
                    {p.number}
                    {p.is_adjustment ? ` · ${t("per.adjustment")}` : ""}
                  </td>
                  <td>
                    {p.start_date} – {p.end_date}
                  </td>
                  <td>
                    <StatusBadge prefix="per.status" status={p.status} />
                  </td>
                  <td>
                    <PeriodActions period={p} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <YearEnd year={year} />
        </section>
      ))}
      {openUnlocks.length ? (
        <section className="panel">
          <h2>{t("per.unlocks")}</h2>
          <ul>
            {openUnlocks.map((u) => (
              <li key={u.id}>
                <strong>{u.status}</strong> · {u.reason}{" "}
                {u.status === "REQUESTED" ? (
                  <>
                    <button onClick={() => decideUnlock.mutate({ unlockId: u.id, decision: "approve" })}>
                      {t("per.approveUnlock")}
                    </button>{" "}
                    <button onClick={() => decideUnlock.mutate({ unlockId: u.id, decision: "reject" })}>
                      {t("per.rejectUnlock")}
                    </button>
                  </>
                ) : null}
              </li>
            ))}
          </ul>
          <ProblemMessage error={decideUnlock.error} />
        </section>
      ) : null}
      <form className="panel form inline" onSubmit={create}>
        <h2>{t("per.createYear")}</h2>
        <label>
          {t("per.startDate")}
          <input type="date" value={start} onChange={(e) => setStart(e.target.value)} required />
        </label>
        <label>
          {t("per.months")}
          <input type="number" min={1} max={18} value={months} onChange={(e) => setMonths(e.target.value)} />
        </label>
        <ProblemMessage error={createYear.error} />
        <button type="submit" disabled={createYear.isPending}>
          {t("per.createYear")}
        </button>
      </form>
    </Page>
  );
}
