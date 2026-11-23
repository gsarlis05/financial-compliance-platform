// VAT (V1-2): choose the company's VAT periods, then, at the end of each period, a VAT report
// from the posted ledger: totals, figures by VAT code, the VAT accounts, checks and every line.
// Sign it off (never your own, except in a one-person workspace), record that you filed it on
// the Tax Department's portal, prepare the settlement entry, export it. Nothing is ever filed by
// the platform.
import Decimal from "decimal.js";
import { type SyntheticEvent, useState } from "react";
import { useScope } from "../api/hooks";
import {
  type VatBox,
  type VatReportDetail,
  type VatStatus,
  useVatMutations,
  useVatPeriods,
  useVatReport,
  useVatSchemes,
  vatExportUrl,
} from "../api/vat";
import { Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";
import { formatAmount } from "../money";

const LENGTHS = [1, 2, 3, 4, 6, 12];

export function VatPage() {
  const { t } = useI18n();
  const [chosen, setChosen] = useState<string | null>(null);
  return (
    <Page title={t("vat.title")}>
      <p className="muted">{t("vat.intro")}</p>
      <PeriodSettings />
      <Periods onOpen={setChosen} chosen={chosen} />
      {chosen ? <ReportView id={chosen} onOpen={setChosen} /> : null}
    </Page>
  );
}

function PeriodSettings() {
  const { t } = useI18n();
  const schemes = useVatSchemes();
  const m = useVatMutations(null);
  const [months, setMonths] = useState(3);
  const [from, setFrom] = useState("");
  const [note, setNote] = useState("");
  const submit = (e: SyntheticEvent) => {
    e.preventDefault();
    m.addScheme.mutate(
      { months, effective_from: from, note },
      { onSuccess: () => setNote("") },
    );
  };
  const rows = schemes.data ?? [];
  return (
    <section className="card" aria-labelledby="vat-periods-setup">
      <h2 id="vat-periods-setup">{t("vat.setup")}</h2>
      {schemes.isPending ? <Loading /> : null}
      {rows.length ? (
        <ul>
          {rows.map((s) => (
            <li key={s.id}>
              {t("vat.from")} {s.effective_from}: {t("vat.every")} {s.months}{" "}
              {t("vat.months")}
              {s.note ? <span className="muted"> · {s.note}</span> : null}
            </li>
          ))}
        </ul>
      ) : (
        <p>{t("vat.noPeriods")}</p>
      )}
      <form className="form inline" onSubmit={submit}>
        <label>
          {t("vat.length")}
          <select
            value={months}
            onChange={(e) => setMonths(Number(e.target.value))}
          >
            {LENGTHS.map((n) => (
              <option key={n} value={n}>
                {n} {t("vat.months")}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("vat.firstDay")}
          <input
            type="date"
            value={from}
            required
            onChange={(e) => setFrom(e.target.value)}
          />
        </label>
        <label>
          {t("vat.note")}
          <input
            value={note}
            maxLength={500}
            onChange={(e) => setNote(e.target.value)}
          />
        </label>
        <button
          type="submit"
          className="primary"
          disabled={!from || m.addScheme.isPending}
        >
          {rows.length ? t("vat.change") : t("vat.set")}
        </button>
      </form>
      <ProblemMessage error={m.addScheme.error} />
    </section>
  );
}

function statusText(t: (k: MessageKey) => string, status: VatStatus): string {
  return t(`vat.status.${status}` as MessageKey);
}

function Periods({
  onOpen,
  chosen,
}: {
  onOpen: (id: string) => void;
  chosen: string | null;
}) {
  const { t } = useI18n();
  const periods = useVatPeriods();
  const m = useVatMutations(null);
  if (periods.isPending) {
    return <Loading />;
  }
  const rows = periods.data ?? [];
  if (!rows.length) {
    return null;
  }
  return (
    <section className="card" aria-labelledby="vat-list">
      <h2 id="vat-list">{t("vat.periods")}</h2>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">{t("vat.period")}</th>
              <th scope="col">{t("vat.report")}</th>
              <th scope="col">
                <span className="visually-hidden">{t("vat.actions")}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr
                key={p.start}
                aria-current={p.report?.id === chosen || undefined}
              >
                <th scope="row">
                  {p.start} – {p.end}
                  {!p.ended ? (
                    <span className="muted"> ({t("vat.open")})</span>
                  ) : null}
                </th>
                <td>
                  {p.report
                    ? `${statusText(t, p.report.status)} · v${String(p.report.version)}`
                    : t("vat.none")}
                  {p.report?.filing_reference
                    ? ` · ${p.report.filing_reference}`
                    : ""}
                </td>
                <td>
                  {p.report ? (
                    <button
                      type="button"
                      onClick={() => onOpen(p.report?.id ?? "")}
                    >
                      {t("vat.open.report")}
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="primary"
                      disabled={m.generate.isPending}
                      onClick={() =>
                        m.generate.mutate(p.start, {
                          onSuccess: (r) => onOpen(r.id),
                        })
                      }
                    >
                      {t("vat.generate")}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ProblemMessage error={m.generate.error} />
    </section>
  );
}

function ReportView({
  id,
  onOpen,
}: {
  id: string;
  onOpen: (id: string) => void;
}) {
  const { t, locale } = useI18n();
  const report = useVatReport(id);
  const [shownBox, setShownBox] = useState("");
  if (report.isPending) {
    return <Loading />;
  }
  if (!report.data) {
    return <ProblemMessage error={report.error} />;
  }
  const r = report.data;
  const s = r.snapshot;
  const money = (v: string) => formatAmount(v, locale);
  const setBox = setShownBox;
  return (
    <section className="card" aria-labelledby="vat-report">
      <h2 id="vat-report">
        {t("vat.reportFor")} {r.period_start} – {r.period_end}{" "}
        <span className="badge">{statusText(t, r.status)}</span>{" "}
        <span className="badge">v{r.version}</span>{" "}
        {r.self_approved ? (
          <span className="badge">{t("approval.self")}</span>
        ) : null}
      </h2>
      <p className="muted">
        {t("vat.taken")} {r.generated_at.slice(0, 16).replace("T", " ")} ·{" "}
        {t("vat.notice")}
      </p>
      {s.unverified_codes.length ? (
        <p role="note">
          {t("vat.unverifiedCodes")} {s.unverified_codes.join(", ")}
        </p>
      ) : null}

      <ReturnView report={r} onBox={setBox} />

      <h3>{t("vat.totals")}</h3>
      <table>
        <tbody>
          {(
            [
              "sales_base",
              "sales_vat",
              "purchase_base",
              "purchase_vat",
            ] as const
          ).map((k) => (
            <tr key={k}>
              <th scope="row">{t(`vat.${k}` as MessageKey)}</th>
              <td className="amount">{money(s.totals[k])}</td>
            </tr>
          ))}
          <tr>
            <th scope="row">
              {t("vat.net")} ({t(`vat.${s.totals.direction}` as MessageKey)})
            </th>
            <td className="amount">
              <strong>{money(s.totals.net)}</strong>
            </td>
          </tr>
        </tbody>
      </table>

      <h3>{t("vat.byCode")}</h3>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">{t("vat.code")}</th>
              <th scope="col">{t("vat.rate")}</th>
              <th scope="col">{t("vat.sales_base")}</th>
              <th scope="col">{t("vat.sales_vat")}</th>
              <th scope="col">{t("vat.purchase_base")}</th>
              <th scope="col">{t("vat.purchase_vat")}</th>
            </tr>
          </thead>
          <tbody>
            {s.codes.map((c) => (
              <tr key={c.code}>
                <th scope="row">{c.code}</th>
                <td>
                  {c.rate === null
                    ? "–"
                    : `${formatAmount(new Decimal(c.rate).times(100).toFixed(2), locale)}%`}
                </td>
                <td className="amount">{money(c.sales_base)}</td>
                <td className="amount">{money(c.sales_vat)}</td>
                <td className="amount">{money(c.purchase_base)}</td>
                <td className="amount">{money(c.purchase_vat)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3>{t("vat.accounts")}</h3>
      <ul>
        {s.accounts.map((a) => (
          <li key={a.code}>
            {a.code} {a.name} ({a.role}): {money(a.vat)}
            {!new Decimal(a.settled).isZero()
              ? ` · ${t("vat.settled")} ${money(a.settled)}`
              : ""}
          </li>
        ))}
      </ul>

      <h3>{t("vat.checks")}</h3>
      {s.exceptions.length ? (
        <ul>
          {s.exceptions.map((e, i) => (
            <li key={`${e.kind}-${String(i)}`}>{e.detail}</li>
          ))}
        </ul>
      ) : (
        <p>{t("vat.noExceptions")}</p>
      )}

      <Lines report={r} box={shownBox} onBox={setShownBox} />
      <Actions report={r} onOpen={onOpen} />
    </section>
  );
}

/** Boxes 1-5 to the cent; Boxes 6-11B to the nearest euro (the server rounds them). */
export function boxAmount(b: VatBox, locale: string): string {
  const shown = formatAmount(b.amount, locale);
  return b.kind === "VAT" ? shown : shown.slice(0, -3);
}

function ReturnView({
  report,
  onBox,
}: {
  report: VatReportDetail;
  onBox: (box: string) => void;
}) {
  const { t, locale } = useI18n();
  const found = report.snapshot.return;
  if (!found) {
    return (
      <>
        <h3>{t("vat.return")}</h3>
        <p role="note">{t("vat.noReturn")}</p>
      </>
    );
  }
  return (
    <section aria-labelledby="vat-return">
      <h3 id="vat-return">{t("vat.return")}</h3>
      <p role="note">{t("vat.rules").replace("{rules}", found.rules)}</p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">{t("vat.box")}</th>
              <th scope="col">{t("vat.item")}</th>
              <th scope="col" className="amount">
                {t("vat.amount")}
              </th>
              <th scope="col" className="amount">
                {t("vat.rounding")}
              </th>
              <th scope="col">
                <span className="visually-hidden">{t("vat.showLines")}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {found.boxes.map((b) => (
              <tr key={b.box} className={b.box === "5" ? "total" : undefined}>
                <th scope="row">{b.box}</th>
                <td>
                  {b.label}
                  {b.box === "5"
                    ? ` (${t(`vat.${found.direction}` as MessageKey)})`
                    : ""}
                </td>
                <td className="amount">
                  {b.box === "5" ? (
                    <strong>{boxAmount(b, locale)}</strong>
                  ) : (
                    boxAmount(b, locale)
                  )}
                </td>
                <td className="amount">
                  {new Decimal(b.rounding).isZero()
                    ? ""
                    : formatAmount(b.rounding, locale)}
                </td>
                <td>
                  {b.box === "3" || b.box === "5" ? null : (
                    <button
                      type="button"
                      className="link-button"
                      aria-label={`${t("vat.showLines")} ${t("vat.box")} ${b.box}`}
                      onClick={() => onBox(b.box)}
                    >
                      {t("vat.showLines")}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted">{t("vat.wholeEuros")}</p>
    </section>
  );
}

function Lines({
  report,
  box,
  onBox,
}: {
  report: VatReportDetail;
  box: string;
  onBox: (box: string) => void;
}) {
  const { t, locale } = useI18n();
  const [code, setCode] = useState("");
  const lines = report.snapshot.lines.filter(
    (l) =>
      (!code || l.code === code) &&
      (!box || (l.boxes ?? {})[box] !== undefined),
  );
  const boxTotal = box
    ? lines.reduce(
        (acc, l) => acc.plus(new Decimal((l.boxes ?? {})[box] ?? "0")),
        new Decimal(0),
      )
    : null;
  return (
    <details id="vat-lines" open={box ? true : undefined}>
      <summary>
        {t("vat.lines")} ({report.snapshot.lines.length})
      </summary>
      {box && boxTotal ? (
        <p role="status">
          {t("vat.boxLines")} {box}: {lines.length} ·{" "}
          {formatAmount(boxTotal, locale)}{" "}
          <button
            type="button"
            className="link-button"
            onClick={() => onBox("")}
          >
            {t("vat.allLines")}
          </button>
        </p>
      ) : null}
      <label>
        {t("vat.code")}
        <select value={code} onChange={(e) => setCode(e.target.value)}>
          <option value="">{t("vat.allCodes")}</option>
          {report.snapshot.codes.map((c) => (
            <option key={c.code} value={c.code}>
              {c.code}
            </option>
          ))}
        </select>
      </label>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">{t("vat.date")}</th>
              <th scope="col">{t("vat.entry")}</th>
              <th scope="col">{t("vat.account")}</th>
              <th scope="col">{t("vat.kind")}</th>
              <th scope="col">{t("vat.amount")}</th>
              <th scope="col">{t("vat.boxes")}</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((l) => (
              <tr key={l.line_id}>
                <td>{l.date}</td>
                <td>
                  {l.entry_ref}
                  <span className="muted"> {l.description}</span>
                </td>
                <td>{l.account}</td>
                <td>{t(`vat.kind.${l.kind}` as MessageKey)}</td>
                <td className="amount">{formatAmount(l.amount, locale)}</td>
                <td title={l.rule}>
                  {l.mapping && l.mapping !== "MAPPED"
                    ? t(`vat.mapping.${l.mapping}` as MessageKey)
                    : Object.keys(l.boxes ?? {}).join(", ")}
                  {l.country ? (
                    <span className="muted"> {l.country}</span>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function Actions({
  report,
  onOpen,
}: {
  report: VatReportDetail;
  onOpen: (id: string) => void;
}) {
  const { t, locale } = useI18n();
  const { base } = useScope();
  const m = useVatMutations(report.id);
  const [due, setDue] = useState(report.due_date ?? "");
  const [filedOn, setFiledOn] = useState("");
  const [reference, setReference] = useState("");
  const done = report.status === "SIGNED_OFF" || report.status === "FILED";
  const error =
    m.act.error ?? m.dueDate.error ?? m.filed.error ?? m.settlement.error;
  return (
    <section aria-labelledby="vat-actions">
      <h3 id="vat-actions">{t("vat.actions")}</h3>
      {report.blockers.length ? (
        <ul>
          {report.blockers.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      ) : null}
      <div className="actions">
        {report.status === "DRAFT" ? (
          <>
            <button
              type="button"
              disabled={m.act.isPending}
              onClick={() => m.act.mutate("regenerate")}
            >
              {t("vat.regenerate")}
            </button>
            <button
              type="button"
              className="primary"
              disabled={m.act.isPending || report.blockers.length > 0}
              onClick={() => m.act.mutate("sign-off")}
            >
              {t("vat.signOff")}
            </button>
          </>
        ) : null}
        {done ? (
          <>
            <button
              type="button"
              disabled={m.act.isPending}
              onClick={() =>
                m.act.mutate("new-version", { onSuccess: (r) => onOpen(r.id) })
              }
            >
              {t("vat.newVersion")}
            </button>
            <button
              type="button"
              disabled={m.settlement.isPending || !!report.settlement_entry_id}
              onClick={() => m.settlement.mutate()}
            >
              {report.settlement_entry_id
                ? t("vat.settlementDone")
                : t("vat.settlement")}
            </button>
          </>
        ) : null}
        <a
          className="button"
          href={vatExportUrl(base, report.id, "pdf", locale)}
        >
          {t("vat.pdf")}
        </a>
        <a
          className="button"
          href={vatExportUrl(base, report.id, "xlsx", locale)}
        >
          {t("vat.xlsx")}
        </a>
      </div>
      {report.status !== "SUPERSEDED" ? (
        <div className="form inline">
          <label>
            {t("vat.due")}
            <input
              type="date"
              value={due}
              onChange={(e) => setDue(e.target.value)}
            />
          </label>
          <button
            type="button"
            disabled={m.dueDate.isPending}
            onClick={() => m.dueDate.mutate(due || null)}
          >
            {t("vat.saveDue")}
          </button>
        </div>
      ) : null}
      {report.status === "SIGNED_OFF" ? (
        <div className="form inline">
          <label>
            {t("vat.filedOn")}
            <input
              type="date"
              value={filedOn}
              onChange={(e) => setFiledOn(e.target.value)}
            />
          </label>
          <label>
            {t("vat.reference")}
            <input
              value={reference}
              maxLength={100}
              onChange={(e) => setReference(e.target.value)}
            />
          </label>
          <button
            type="button"
            className="primary"
            disabled={!filedOn || !reference.trim() || m.filed.isPending}
            onClick={() => m.filed.mutate({ filed_on: filedOn, reference })}
          >
            {t("vat.markFiled")}
          </button>
        </div>
      ) : null}
      {report.filed_on ? (
        <p>
          {t("vat.filedText")} {report.filed_on} · {report.filing_reference}
        </p>
      ) : null}
      {m.settlement.data ? (
        <p role="status">{t("vat.settlementMade")}</p>
      ) : null}
      <ProblemMessage error={error} />
    </section>
  );
}
