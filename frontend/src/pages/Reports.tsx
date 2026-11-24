import { useState } from "react";
import { useParams } from "react-router";
import { apiUrl } from "../api/client";
import {
  useDimensions,
  useIntegrity,
  useScope,
  useTrialBalance,
} from "../api/hooks";
import { Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import { formatAmount } from "../money";

export function TrialBalancePage() {
  const { t, locale } = useI18n();
  const { base } = useScope();
  const [asOf, setAsOf] = useState(new Date().toISOString().slice(0, 10));
  const [valueId, setValueId] = useState("");
  const tb = useTrialBalance(asOf, valueId);
  const dimensions = useDimensions();
  return (
    <Page
      title={t("tb.title")}
      actions={
        <a
          className="button"
          href={apiUrl(`${base}/reports/trial-balance.csv`, {
            as_of: asOf,
            ...(valueId ? { dimension_value_id: valueId } : {}),
          })}
        >
          {t("tb.export")}
        </a>
      }
    >
      <div className="form inline">
        <label>
          {t("tb.asOf")}
          <input
            type="date"
            value={asOf}
            onChange={(e) => setAsOf(e.target.value)}
          />
        </label>
        {dimensions.data?.length ? (
          <label>
            {t("tb.dimension")}
            <select
              value={valueId}
              onChange={(e) => setValueId(e.target.value)}
            >
              <option value="">{t("tb.allLines")}</option>
              {dimensions.data.map((d) => (
                <optgroup key={d.id} label={`${d.code} · ${d.name}`}>
                  {d.values.map((v) => (
                    <option key={v.id} value={v.id}>
                      {d.code}: {v.code} · {v.name}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </label>
        ) : null}
      </div>
      {valueId ? <p className="notice">{t("tb.partial")}</p> : null}
      {tb.isPending ? <Loading /> : null}
      <ProblemMessage error={tb.error} />
      {tb.data ? (
        <>
          {tb.data.unposted_entries ? (
            <p className="notice">
              {tb.data.unposted_entries} {t("tb.unposted")}
            </p>
          ) : null}
          {tb.data.restated_after_lock ? (
            <p className="notice warn">
              {tb.data.restated_after_lock} {t("tb.restated")}
            </p>
          ) : null}
          {tb.data.rows.length === 0 ? (
            <p className="muted">{t("tb.empty")}</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th scope="col">{t("acc.code")}</th>
                  <th scope="col">{t("acc.name")}</th>
                  <th scope="col" className="amount">
                    {t("je.debit")}
                  </th>
                  <th scope="col" className="amount">
                    {t("je.credit")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {tb.data.rows.map((r) => (
                  <tr key={r.account_id}>
                    <td>{r.code}</td>
                    <td>{r.name}</td>
                    <td className="amount">
                      {r.debit === "0.00" ? "" : formatAmount(r.debit, locale)}
                    </td>
                    <td className="amount">
                      {r.credit === "0.00"
                        ? ""
                        : formatAmount(r.credit, locale)}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th scope="row" colSpan={2}>
                    {t("tb.total")}
                  </th>
                  <td className="amount">
                    {formatAmount(tb.data.total_debit, locale)}
                  </td>
                  <td className="amount">
                    {formatAmount(tb.data.total_credit, locale)}
                  </td>
                </tr>
              </tfoot>
            </table>
          )}
        </>
      ) : null}
    </Page>
  );
}

export function IntegrityPage() {
  const { t, locale } = useI18n();
  const { slug = "" } = useParams();
  const { runs, run } = useIntegrity(slug);
  const latest = runs.data?.[0];
  return (
    <Page
      title={t("int.title")}
      actions={<button onClick={() => run.mutate()}>{t("int.run")}</button>}
    >
      {runs.isPending ? <Loading /> : null}
      <ProblemMessage error={runs.error ?? run.error} />
      {runs.data?.length === 0 ? (
        <p className="muted">{t("int.none")}</p>
      ) : null}
      {latest ? (
        <section
          className={`panel ${latest.status === "PASSED" ? "ok" : "warn"}`}
        >
          <h2>
            {latest.status === "PASSED" ? t("int.passed") : t("int.failed")}
          </h2>
          <p className="muted">
            {new Date(latest.created_at).toLocaleString(
              locale === "el" ? "el-GR" : "en-GB",
            )}
          </p>
          <ul>
            {latest.results.map((r) => (
              <li key={r.check}>
                {r.ok ? "✓" : "✗"} {r.check}
                {r.details.length ? <pre>{r.details.join("\n")}</pre> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </Page>
  );
}
