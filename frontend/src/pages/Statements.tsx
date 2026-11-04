import { Fragment, useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { ApiError, apiUrl } from "../api/client";
import { useGeneralLedger, useScope, useStatements } from "../api/hooks";
import type { Statement, StatementAccount, StatementRow } from "../api/types";
import { Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";
import { formatAmount } from "../money";

type Kind = "PL" | "BS" | "CF";
const TABS: [Kind, MessageKey][] = [
  ["PL", "st.pl"],
  ["BS", "st.bs"],
  ["CF", "st.cf"],
];
type LedgerTarget = { id: string; label: string };

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

/** P&L, balance sheet and cash flow with prior-year comparatives, drill-down and export (M2-8). */
export function StatementsPage() {
  const { t, locale } = useI18n();
  const { slug, entityId, base } = useScope();
  const [dateFrom, setDateFrom] = useState(`${today().slice(0, 4)}-01-01`);
  const [dateTo, setDateTo] = useState(today());
  const [compare, setCompare] = useState(true);
  const [tab, setTab] = useState<Kind>("PL");
  const [ledger, setLedger] = useState<LedgerTarget | null>(null);
  const comparative = compare ? "prior_year" : "none";
  const statements = useStatements(dateFrom, dateTo, comparative);
  const data = statements.data;
  const blocked =
    statements.error instanceof ApiError && statements.error.code === "metrics.statements.mapping_incomplete"
      ? statements.error.fieldErrors()
      : null;
  const shown: Statement | undefined = data
    ? { PL: data.profit_and_loss, BS: data.balance_sheet, CF: data.cash_flow }[tab]
    : undefined;
  const exportUrl = (format: string) =>
    apiUrl(`${base}/statements/export`, { date_from: dateFrom, date_to: dateTo, comparative, format, lang: locale });

  return (
    <Page
      title={t("st.title")}
      actions={
        data ? (
          <span className="actions" aria-label={t("st.export")}>
            {["pdf", "xlsx", "csv"].map((format) => (
              <a key={format} className="button" href={exportUrl(format)}>
                {t("st.export")} {format.toUpperCase()}
              </a>
            ))}
          </span>
        ) : null
      }
    >
      <p className="muted">{t("st.help")}</p>
      <div className="form inline">
        <label>
          {t("st.from")}
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </label>
        <label>
          {t("st.to")}
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </label>
        <label className="checkbox">
          <input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} />
          {t("st.comparative")}
        </label>
      </div>
      {statements.isPending && statements.fetchStatus !== "idle" ? <Loading /> : null}
      {blocked ? (
        <div className="notice warn" role="alert" data-testid="statements-blocked">
          <p>
            {t("st.blocked")} {Object.keys(blocked).join(", ")}
          </p>
          <Link to={`/w/${slug}/e/${entityId}/mapping`}>{t("st.openMapping")}</Link>
        </div>
      ) : (
        <ProblemMessage error={statements.error} />
      )}
      {data && shown ? (
        <>
          <p className={data.ok ? "notice" : "notice warn"} role={data.ok ? undefined : "alert"}>
            {data.ok ? t("st.checksOk") : t("st.checksFailed")} {t("st.watermark")}
            {data.watermark}.
          </p>
          <div role="tablist" aria-label={t("st.title")} className="segmented">
            {TABS.map(([kind, label]) => (
              <button
                key={kind}
                type="button"
                role="tab"
                aria-selected={tab === kind}
                className={tab === kind ? "active" : ""}
                onClick={() => setTab(kind)}
              >
                {t(label)}
              </button>
            ))}
          </div>
          <StatementTable
            statement={shown}
            comparative={data.comparative_from !== null}
            onLedger={(account) => setLedger(account)}
          />
        </>
      ) : null}
      {ledger ? (
        <LedgerPanel target={ledger} dateFrom={dateFrom} dateTo={dateTo} onClose={() => setLedger(null)} />
      ) : null}
    </Page>
  );
}

function StatementTable({
  statement,
  comparative,
  onLedger,
}: {
  statement: Statement;
  comparative: boolean;
  onLedger: (target: LedgerTarget) => void;
}) {
  const { t, locale } = useI18n();
  const [open, setOpen] = useState<Set<string>>(new Set());
  const name = (r: { name: string; name_el: string }) => (locale === "el" && r.name_el ? r.name_el : r.name);
  const money = (value: string | null) => (value === null ? "" : formatAmount(value, locale));
  const toggle = (code: string) =>
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(code)) {
        next.delete(code);
      } else {
        next.add(code);
      }
      return next;
    });
  const columns = comparative ? 3 : 2;
  return (
    <div className="table-scroll">
      <table className="statement" aria-label={name(statement)}>
        <thead>
          <tr>
            <th scope="col">{name(statement)}</th>
            <th scope="col" className="amount">
              {t("st.current")}
            </th>
            {comparative ? (
              <th scope="col" className="amount">
                {t("st.prior")}
              </th>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {statement.rows.map((row: StatementRow) =>
            row.kind === "heading" ? (
              <tr key={row.code} className="heading">
                <th scope="colgroup" colSpan={columns}>
                  {name(row)}
                </th>
              </tr>
            ) : (
              <Fragment key={row.code}>
                <tr className={row.kind}>
                  <th scope="row">
                    {row.accounts.length ? (
                      <button
                        type="button"
                        className="link-button"
                        aria-expanded={open.has(row.code)}
                        title={t("st.drill")}
                        onClick={() => toggle(row.code)}
                      >
                        {open.has(row.code) ? "▾" : "▸"} {name(row)}
                      </button>
                    ) : (
                      name(row)
                    )}
                  </th>
                  <td className="amount">{money(row.current)}</td>
                  {comparative ? <td className="amount">{money(row.comparative)}</td> : null}
                </tr>
                {open.has(row.code)
                  ? row.accounts.map((a: StatementAccount) => (
                      <tr key={`${row.code}:${a.account_id ?? a.name}`} className="account">
                        <td>
                          {a.account_id ? (
                            <button
                              type="button"
                              className="link-button"
                              onClick={() => onLedger({ id: a.account_id ?? "", label: `${a.code} · ${name(a)}` })}
                            >
                              {a.code} · {name(a)}
                            </button>
                          ) : (
                            <span className="muted">
                              {name(a)} ({t("st.computed")})
                            </span>
                          )}
                        </td>
                        <td className="amount">{money(a.current)}</td>
                        {comparative ? <td className="amount">{money(a.comparative)}</td> : null}
                      </tr>
                    ))
                  : null}
              </Fragment>
            ),
          )}
        </tbody>
      </table>
    </div>
  );
}

function LedgerPanel({
  target,
  dateFrom,
  dateTo,
  onClose,
}: {
  target: LedgerTarget;
  dateFrom: string;
  dateTo: string;
  onClose: () => void;
}) {
  const { t, locale } = useI18n();
  const { slug, entityId } = useScope();
  const gl = useGeneralLedger(target.id, dateFrom, dateTo);
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    panel.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [target.id]);
  return (
    <section ref={panel} className="panel" aria-label={`${t("st.ledger")}: ${target.label}`}>
      <header className="page-header">
        <h2>
          {t("st.ledger")}: {target.label}
        </h2>
        <button type="button" onClick={onClose}>
          {t("st.close")}
        </button>
      </header>
      {gl.isPending ? <Loading /> : null}
      <ProblemMessage error={gl.error} />
      {gl.data ? (
        <div className="table-scroll">
          <p>
            {t("st.opening")}: {formatAmount(gl.data.opening_balance, locale)}
          </p>
          {gl.data.lines.length === 0 ? <p className="muted">{t("st.noLines")}</p> : null}
          {gl.data.lines.length ? (
            <table>
              <thead>
                <tr>
                  <th scope="col">{t("je.date")}</th>
                  <th scope="col">{t("je.number")}</th>
                  <th scope="col">{t("je.description")}</th>
                  <th scope="col" className="amount">
                    {t("je.debit")}
                  </th>
                  <th scope="col" className="amount">
                    {t("je.credit")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {gl.data.lines.map((line, index) => (
                  <tr key={`${line.entry_id}:${index}`}>
                    <td>{line.accounting_date}</td>
                    <td>
                      <Link to={`/w/${slug}/e/${entityId}/entries/${line.entry_id}`}>{line.entry_ref}</Link>
                    </td>
                    <td>{line.description}</td>
                    <td className="amount">{line.debit === "0.00" ? "" : formatAmount(line.debit, locale)}</td>
                    <td className="amount">{line.credit === "0.00" ? "" : formatAmount(line.credit, locale)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          <p>
            {t("st.closing")}: {formatAmount(gl.data.closing_balance, locale)}
          </p>
        </div>
      ) : null}
    </section>
  );
}
