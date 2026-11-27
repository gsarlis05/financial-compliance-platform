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
  type VatScheduleName,
  type VatScheduleRow,
  type VatReportDetail,
  type VatStatus,
  useVatMutations,
  useVatPeriods,
  useVatReport,
  useVatSchemes,
  vatExportUrl,
} from "../api/vat";
import { VatImports } from "../components/VatImports";
import { VatVies } from "../components/VatVies";
import { Loading, Page, ProblemMessage } from "../components/common";
import { useI18n } from "../i18n/I18n";
import type { MessageKey } from "../i18n/messages";
import { formatAmount } from "../money";
import { dayMonthYear } from "../components/ReviewNote";

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
      <p className="muted">{steps(t, r)}</p>
      {r.status === "DRAFT" && r.review_note ? (
        <p role="note">
          {t("vat.lastReopened")} {r.review_note}
        </p>
      ) : null}
      <Previous report={r} />
      <Differences report={r} />
      {s.unverified_codes.length ? (
        <p role="note">
          {t("vat.unverifiedCodes")} {s.unverified_codes.join(", ")}
        </p>
      ) : null}

      <ReturnView report={r} onBox={setBox} />
      <Adjustments report={r} />

      <VatImports
        periodStart={r.period_start}
        periodEnd={r.period_end}
        editable={r.status === "DRAFT"}
      />
      <VatVies report={r} />
      <Schedules report={r} />
      <Reconciliation report={r} />

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
  const found = report.final_return;
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
      <p role="note">
        {report.snapshot.reviews?.box_rules.status === "OWNER_CHECKED" &&
        report.snapshot.reviews.box_rules.on
          ? t("vat.rulesOwnerChecked")
              .replace("{rules}", found.rules)
              .replace(
                "{on}",
                dayMonthYear(report.snapshot.reviews.box_rules.on),
              )
          : t("vat.rules").replace("{rules}", found.rules)}
      </p>
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
              {found.adjusted ? (
                <>
                  <th scope="col" className="amount">
                    {t("vat.fromBooks")}
                  </th>
                  <th scope="col" className="amount">
                    {t("vat.adjustment")}
                  </th>
                </>
              ) : null}
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
                {found.adjusted ? (
                  <>
                    <td className="amount">
                      {boxAmount({ ...b, amount: b.original }, locale)}
                    </td>
                    <td className="amount">
                      {new Decimal(b.adjustment).isZero()
                        ? ""
                        : formatAmount(b.adjustment, locale)}
                    </td>
                  </>
                ) : null}
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

type Column = Exclude<keyof VatScheduleRow, "boxes" | "lines">;
const SCHEDULES: {
  name: VatScheduleName;
  columns: Column[];
}[] = [
  {
    name: "sales",
    columns: [
      "date",
      "entry_ref",
      "counterparty",
      "country",
      "code",
      "net_sale",
      "output_vat",
    ],
  },
  {
    name: "purchases",
    columns: [
      "date",
      "entry_ref",
      "counterparty",
      "country",
      "code",
      "net_purchase",
      "input_vat",
      "blocked",
    ],
  },
  {
    name: "eu_trade",
    columns: [
      "date",
      "entry_ref",
      "type",
      "counterparty",
      "country",
      "vat_no",
      "net",
    ],
  },
  {
    name: "reverse_charge",
    columns: [
      "date",
      "entry_ref",
      "type",
      "counterparty",
      "country",
      "net_purchase",
      "output_vat",
      "input_vat",
      "blocked",
    ],
  },
  {
    name: "imports",
    columns: [
      "date",
      "entry_ref",
      "reference",
      "counterparty",
      "net_purchase",
      "input_vat",
      "blocked",
    ],
  },
];
const HEADINGS: Partial<Record<Column, MessageKey>> = {
  date: "vat.date",
  entry_ref: "vat.entry",
  counterparty: "vat.party",
  country: "vat.country",
  vat_no: "vat.vatNo",
  code: "vat.code",
  reference: "vat.reference",
  type: "vat.type",
  net: "vat.netValue",
  net_sale: "vat.netValue",
  net_purchase: "vat.netValue",
  output_vat: "vat.outputVat",
  input_vat: "vat.inputVat",
  blocked: "vat.blocked",
};
const MONEY = new Set<Column>([
  "net",
  "net_sale",
  "net_purchase",
  "output_vat",
  "input_vat",
  "blocked",
]);

function Schedules({ report }: { report: VatReportDetail }) {
  const { t, locale } = useI18n();
  const typeText = (v: string) =>
    t((v in EU_TYPES ? `vat.eu.${v}` : `vat.category.${v}`) as MessageKey);
  return (
    <section aria-labelledby="vat-schedules">
      <h3 id="vat-schedules">{t("vat.schedules")}</h3>
      {SCHEDULES.map(({ name, columns }) => {
        const found = report.schedules[name];
        const label = t(`vat.schedule.${name}` as MessageKey);
        return (
          <details key={name}>
            <summary>
              {label} ({found.rows.length})
            </summary>
            {found.rows.length ? (
              <div className="table-scroll">
                <table aria-label={label}>
                  <thead>
                    <tr>
                      {columns.map((c) => (
                        <th
                          scope="col"
                          key={c}
                          className={MONEY.has(c) ? "amount" : undefined}
                        >
                          {t(HEADINGS[c] ?? "vat.amount")}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {found.rows.map((row) => (
                      <tr key={`${row.entry_id}-${row.code}`}>
                        {columns.map((c) => {
                          const value = row[c];
                          if (MONEY.has(c)) {
                            return (
                              <td className="amount" key={c}>
                                {formatAmount(value ?? "0", locale)}
                              </td>
                            );
                          }
                          return (
                            <td key={c}>
                              {c === "type" ? typeText(value ?? "") : value}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      {columns.map((c, i) => (
                        <td
                          key={c}
                          className={MONEY.has(c) ? "amount" : undefined}
                        >
                          {i === 0
                            ? t("vat.total")
                            : MONEY.has(c)
                              ? formatAmount(found.totals[c] ?? "0", locale)
                              : ""}
                        </td>
                      ))}
                    </tr>
                  </tfoot>
                </table>
              </div>
            ) : (
              <p className="muted">{t("vat.scheduleEmpty")}</p>
            )}
          </details>
        );
      })}
    </section>
  );
}

const EU_TYPES = {
  GOODS_SUPPLIED: 1,
  SERVICES_SUPPLIED: 1,
  GOODS_ACQUIRED: 1,
  SERVICES_RECEIVED: 1,
};

function Reconciliation({ report }: { report: VatReportDetail }) {
  const { t, locale } = useI18n();
  const r = report.reconciliation;
  if (!r) {
    return null;
  }
  const money = (v: string) => formatAmount(v, locale);
  return (
    <section aria-labelledby="vat-reconciliation">
      <h3 id="vat-reconciliation">{t("vat.reconciliation")}</h3>
      <p className="muted">{t("vat.reconHelp")}</p>
      <div className="table-scroll">
        <table aria-label={t("vat.accounts")}>
          <thead>
            <tr>
              <th scope="col">{t("vat.account")}</th>
              <th scope="col" className="amount">
                {t("vat.opening")}
              </th>
              <th scope="col" className="amount">
                {t("vat.periodVat")}
              </th>
              <th scope="col" className="amount">
                {t("vat.settled")}
              </th>
              <th scope="col" className="amount">
                {t("vat.closing")}
              </th>
              <th scope="col" className="amount">
                {t("vat.unexplained")}
              </th>
            </tr>
          </thead>
          <tbody>
            {r.accounts.map((a) => (
              <tr key={a.code}>
                <th scope="row">
                  {a.code} {a.name} ({a.role})
                </th>
                <td className="amount">{money(a.opening)}</td>
                <td className="amount">{money(a.vat)}</td>
                <td className="amount">{money(a.settled)}</td>
                <td className="amount">{money(a.closing)}</td>
                <td className="amount">{money(a.unexplained)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="table-scroll">
        <table aria-label={t("vat.inReturn")}>
          <thead>
            <tr>
              <th scope="col">{t("vat.box")}</th>
              <th scope="col" className="amount">
                {t("vat.ledger")}
              </th>
              <th scope="col" className="amount">
                {t("vat.notInBox")}
              </th>
              <th scope="col" className="amount">
                {t("vat.adjustments")}
              </th>
              <th scope="col" className="amount">
                {t("vat.inReturn")}
              </th>
              <th scope="col" className="amount">
                {t("vat.unexplained")}
              </th>
            </tr>
          </thead>
          <tbody>
            {r.bridges.map((b) => {
              const item = (k: string) =>
                b.items.find((i) => i.item === k)?.amount ?? "0";
              return (
                <tr key={b.side}>
                  <th scope="row">{t(`vat.side.${b.side}` as MessageKey)}</th>
                  <td className="amount">{money(b.ledger)}</td>
                  <td className="amount">{money(item("NOT_IN_A_BOX"))}</td>
                  <td className="amount">{money(item("ADJUSTMENTS"))}</td>
                  <td className="amount">{money(b.return)}</td>
                  <td className="amount">{money(b.unexplained)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p role="status">
        {r.balanced ? t("vat.reconciled") : t("vat.notReconciled")}
      </p>
      <p className="muted">
        {t("vat.reconApart")} {money(r.settlements)}
      </p>
    </section>
  );
}

function steps(t: (k: MessageKey) => string, r: VatReportDetail): string {
  const at = (v: string) => v.slice(0, 16).replace("T", " ");
  const parts = [t("vat.steps").replace("{prepared}", at(r.created_at))];
  if (r.reviewed_at) {
    parts.push(t("vat.reviewedAt").replace("{at}", at(r.reviewed_at)));
  }
  if (r.finalised_at) {
    parts.push(t("vat.finalisedAt").replace("{at}", at(r.finalised_at)));
  }
  return parts.join(" · ");
}

function BoxChanges({ boxes }: { boxes: Record<string, string> }) {
  const { locale } = useI18n();
  return (
    <ul className="inline-list">
      {Object.entries(boxes).map(([box, change]) => (
        <li key={box}>
          {box}: {new Decimal(change).isPositive() ? "+" : ""}
          {formatAmount(change, locale)}
        </li>
      ))}
    </ul>
  );
}

function Previous({ report }: { report: VatReportDetail }) {
  const { t } = useI18n();
  const p = report.previous;
  if (!p) {
    return null;
  }
  const version = String(p.version);
  return (
    <div role="note">
      <p>
        {t("vat.amends").replace("{version}", version)}{" "}
        {p.filed_on
          ? t("vat.amendsFiled")
              .replace("{version}", version)
              .replace("{on}", p.filed_on)
              .replace("{ref}", p.filing_reference)
          : ""}
      </p>
      {Object.keys(p.boxes).length ? (
        <>
          <p>{t("vat.changeFromPrevious").replace("{version}", version)}</p>
          <BoxChanges boxes={p.boxes} />
        </>
      ) : null}
    </div>
  );
}

function Differences({ report }: { report: VatReportDetail }) {
  const { t, locale } = useI18n();
  const d = report.differences;
  if (!d?.changed) {
    return null;
  }
  const rows = [
    ...d.added.map((l) => ({ l, key: "vat.added" as const })),
    ...d.removed.map((l) => ({ l, key: "vat.removed" as const })),
  ];
  return (
    <section aria-labelledby="vat-differences" className="notice">
      <h3 id="vat-differences">{t("vat.differences")}</h3>
      <p>{t("vat.differencesHelp")}</p>
      <p>{t("vat.boxChange")}</p>
      <BoxChanges boxes={d.boxes} />
      <ul>
        {rows.map(({ l, key }) => (
          <li key={`${key}-${l.line_id}`}>
            {t(key)}: {l.date} {l.entry_ref} {l.account}{" "}
            {formatAmount(l.amount, locale)}
          </li>
        ))}
      </ul>
    </section>
  );
}

const ADJUSTABLE = [
  "1",
  "2",
  "4",
  "6",
  "7",
  "8A",
  "8B",
  "9",
  "10",
  "11A",
  "11B",
];

function Adjustments({ report }: { report: VatReportDetail }) {
  const { t, locale } = useI18n();
  const m = useVatMutations(report.id);
  const [box, setBox] = useState("1");
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [evidence, setEvidence] = useState("");
  const draft = report.status === "DRAFT";
  if (!draft && report.adjustments.length === 0) {
    return null;
  }
  function propose(event: SyntheticEvent) {
    event.preventDefault();
    m.propose.mutate(
      { box, amount: amount.trim().replace(",", "."), reason, evidence },
      {
        onSuccess: () => {
          setAmount("");
          setReason("");
          setEvidence("");
        },
      },
    );
  }
  return (
    <section aria-labelledby="vat-adjustments">
      <h3 id="vat-adjustments">{t("vat.adjustments")}</h3>
      {report.adjustments.length ? (
        <ul>
          {report.adjustments.map((a) => (
            <li key={a.id}>
              {t("vat.box")} {a.box}: {formatAmount(a.amount, locale)} ·{" "}
              {a.reason} · {a.evidence} ·{" "}
              <span className="badge">
                {t(`vat.adj.${a.status}` as MessageKey)}
              </span>
              {a.self_approved ? (
                <span className="badge">{t("approval.self")}</span>
              ) : null}
              {draft && a.status === "PROPOSED" ? (
                <>
                  {" "}
                  <button
                    type="button"
                    className="link-button"
                    disabled={m.decide.isPending}
                    onClick={() => m.decide.mutate({ id: a.id, approve: true })}
                  >
                    {t("vat.approve")}
                  </button>{" "}
                  <button
                    type="button"
                    className="link-button"
                    disabled={m.decide.isPending}
                    onClick={() =>
                      m.decide.mutate({ id: a.id, approve: false })
                    }
                  >
                    {t("vat.reject")}
                  </button>
                </>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">{t("vat.noAdjustments")}</p>
      )}
      {draft && report.final_return ? (
        <form className="form inline" onSubmit={propose}>
          <p className="muted">{t("vat.adjustmentsHelp")}</p>
          <label>
            {t("vat.box")}
            <select value={box} onChange={(e) => setBox(e.target.value)}>
              {ADJUSTABLE.map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("vat.adjAmount")}
            <input
              inputMode="decimal"
              required
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
          </label>
          <label>
            {t("vat.adjReason")}
            <input
              required
              maxLength={500}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          <label>
            {t("vat.adjEvidence")}
            <input
              required
              maxLength={500}
              value={evidence}
              onChange={(e) => setEvidence(e.target.value)}
            />
          </label>
          <button type="submit" disabled={m.propose.isPending}>
            {t("vat.propose")}
          </button>
        </form>
      ) : null}
      <ProblemMessage error={m.propose.error ?? m.decide.error} />
    </section>
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
  const [evidence, setEvidence] = useState("");
  const [note, setNote] = useState("");
  const done = report.status === "FINALISED" || report.status === "FILED";
  const error =
    m.act.error ??
    m.dueDate.error ??
    m.filed.error ??
    m.settlement.error ??
    m.reopen.error;
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
              onClick={() => m.act.mutate("review")}
            >
              {t("vat.review")}
            </button>
          </>
        ) : null}
        {report.status === "REVIEWED" ? (
          <button
            type="button"
            className="primary"
            disabled={m.act.isPending || report.blockers.length > 0}
            onClick={() => m.act.mutate("finalise")}
          >
            {t("vat.finalise")}
          </button>
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
        <a
          className="button"
          href={vatExportUrl(base, report.id, "csv", locale)}
        >
          {t("vat.csv")}
        </a>
      </div>
      {report.status === "REVIEWED" ? (
        <div className="form inline">
          <label>
            {t("vat.reopenNote")}
            <input
              value={note}
              maxLength={500}
              onChange={(e) => setNote(e.target.value)}
            />
          </label>
          <button
            type="button"
            disabled={!note.trim() || m.reopen.isPending}
            onClick={() => m.reopen.mutate(note)}
          >
            {t("vat.reopen")}
          </button>
        </div>
      ) : null}
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
      {report.status === "FINALISED" ? (
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
          <label>
            {t("vat.evidence")}
            <input
              value={evidence}
              maxLength={500}
              title={t("vat.evidenceHelp")}
              onChange={(e) => setEvidence(e.target.value)}
            />
          </label>
          <button
            type="button"
            className="primary"
            disabled={
              !filedOn ||
              !reference.trim() ||
              !evidence.trim() ||
              m.filed.isPending
            }
            onClick={() =>
              m.filed.mutate({ filed_on: filedOn, reference, evidence })
            }
          >
            {t("vat.markFiled")}
          </button>
        </div>
      ) : null}
      {report.filed_on ? (
        <p>
          {t("vat.filedText")} {report.filed_on} · {report.filing_reference}
          {report.filing_evidence ? ` · ${report.filing_evidence}` : ""}
        </p>
      ) : null}
      {m.settlement.data ? (
        <p role="status">{t("vat.settlementMade")}</p>
      ) : null}
      <ProblemMessage error={error} />
    </section>
  );
}
