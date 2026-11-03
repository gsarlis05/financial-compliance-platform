import { type SyntheticEvent, useState } from "react";
import { useFiscalYears, usePeriodMutations, useUnlocks } from "../api/hooks";
import type { Period } from "../api/types";
import { Loading, Page, ProblemMessage, StatusBadge } from "../components/common";
import { useI18n } from "../i18n/I18n";

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
